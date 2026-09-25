"""
Dose-response interpretation engine for bmdx.

Takes gene-level BMD results (from BMDExpress) and produces a grounded,
literature-backed narrative by querying the bmdx knowledge base.

Usage:
    python interpret.py <dose_response.csv> [--db bmdx.duckdb] [--output output/interpretation.md] [--fdr 0.05]
"""

import argparse
from pathlib import Path

import pandas as pd

from knowledge_base.enrichment_stats import enrich_pathways, enrich_go_terms
from knowledge_base.extract import normalize_gene
from styling_export.llm_endpoints import AnthropicEndpoint, resolve_anthropic_api_key, resolve_model_name
from knowledge_base.toxkb import ToxKBQuerier
from narrative.interpret_narrative import (
    NarrativeRun,
    synthesize_interpretation,
    generate_all_narratives,
    run_concordance_analysis,
)
from narrative.interpret_analysis import (
    rank_go_sets_by_bmd,
    rank_genes_by_bmd,
    fetch_go_descriptions,
    fetch_gene_descriptions,
    AnalysisResult,
    analyze,
    build_genomics_interpretation,
)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def load_dose_response(csv_path: str) -> pd.DataFrame:
    """Load and validate dose-response CSV."""
    df = pd.read_csv(csv_path)

    # Normalize column names
    df.columns = [c.strip().lower() for c in df.columns]

    # Validate required columns
    if "gene_symbol" not in df.columns:
        raise ValueError("CSV must have a 'gene_symbol' column")
    if "bmd" not in df.columns:
        raise ValueError("CSV must have a 'bmd' column")

    # Normalize gene symbols
    df["gene_symbol"] = df["gene_symbol"].apply(normalize_gene)
    df = df[df["gene_symbol"] != ""].reset_index(drop=True)

    # Ensure BMD is numeric
    df["bmd"] = pd.to_numeric(df["bmd"], errors="coerce")
    df = df.dropna(subset=["bmd"]).reset_index(drop=True)

    return df


def interpret(
    csv_path: str,
    db_path: str = "bmdx.duckdb",
    output_path: str = "output/interpretation.md",
    fdr_cutoff: float = 0.05,
    models: list[str] | None = None,
    n_runs: int = 3,
    concordance_model: str = "claude-sonnet-4-6",
) -> str:
    """Full interpretation pipeline."""
    print(f"Loading dose-response data from {csv_path}...")
    df = load_dose_response(csv_path)
    print(f"  {len(df)} genes loaded (BMD range: {df['bmd'].min():.3g} - {df['bmd'].max():.3g})")

    print(f"Connecting to knowledge base: {db_path}")
    # The KB connection is only needed to build `result`; the context manager
    # releases the duckdb handle as soon as that's done (and even if a query
    # raises), so the long narrative/output phase below holds no DB connection.
    with ToxKBQuerier(db_path) as kb:
        # Check how many genes are in the KB
        in_kb = sum(1 for g in df["gene_symbol"] if kb.gene_evidence(g)["evidence"] is not None)
        print(f"  {in_kb}/{len(df)} genes found in KB")

        print("Building interpretation context...")
        result = analyze(df, kb, fdr_cutoff)

    # --- Multi-model mode ---
    if models:
        print(f"Multi-model mode: {len(models)} models x {n_runs} runs = {len(models) * n_runs} narratives")
        result.narrative_runs = generate_all_narratives(
            context=result.context_text,
            models=models,
            n_runs=n_runs,
            base_md=output_path,
        )
        print(f"  {len(result.narrative_runs)} narratives generated.")

        # Run concordance analysis
        if result.narrative_runs:
            print("Running concordance analysis...")
            result.concordance_text, result.concordance_model = run_concordance_analysis(
                result.narrative_runs,
                concordance_model=concordance_model,
            )

        # Write combined "all" outputs
        md_path = Path(output_path)
        all_md = md_path.parent / f"{md_path.stem}_all{md_path.suffix}"
        lines = ["# All Narratives\n"]
        for run in result.narrative_runs:
            lines.append(f"## {run.model} — Run {run.run_index + 1} ({run.elapsed_seconds:.1f}s)\n")
            lines.append(run.narrative)
            lines.append("\n---\n")
        # Insert concordance before appendix
        if result.concordance_text:
            lines.append(f"\n# Concordance Analysis\n\n*Analyzed by {result.concordance_model}*\n")
            lines.append(result.concordance_text)
            lines.append("\n---\n")
        lines.append("\n# Appendix: Structured Analysis\n\n```\n" + result.context_text + "\n```\n")
        all_md_text = "\n".join(lines)
        all_md.parent.mkdir(parents=True, exist_ok=True)
        all_md.write_text(all_md_text)
        print(f"Combined markdown saved to {all_md}")

        # Write separate concordance output files
        if result.concordance_text:
            conc_md = md_path.parent / f"{md_path.stem}_concordance{md_path.suffix}"
            conc_md_text = (
                f"# Concordance Analysis\n\n"
                f"*Analyzed by {result.concordance_model}*\n\n"
                f"{result.concordance_text}\n"
            )
            conc_md.write_text(conc_md_text)
            print(f"Concordance markdown saved to {conc_md}")

        return all_md_text

    # --- Single-model mode (backward compatible) ---
    print("Running LLM synthesis...")
    result.llm_narrative = synthesize_interpretation(result.context_text)

    # Write markdown output
    report = result.llm_narrative
    report += "\n\n---\n\n# Appendix: Structured Analysis\n\n```\n" + result.context_text + "\n```\n"

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    print(f"Markdown saved to {output_path}")

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def concordance_only(
    all_md_path: str = "output/interpretation_all.md",
    concordance_model: str = "claude-sonnet-4-6",
    output_dir: str | None = None,
) -> str:
    """
    Run concordance analysis on existing narratives without re-generating them.

    Parses the combined all-narratives markdown to reconstruct NarrativeRun
    objects, then feeds them to run_concordance_analysis().
    """
    import re as _re

    all_md = Path(all_md_path)
    if not all_md.exists():
        print(f"Error: {all_md_path} not found")
        print("Run the full pipeline first to generate narratives.")
        return ""

    text = all_md.read_text()

    # Parse "## model_name — Run N (Xs)" headers and their narrative bodies
    # Pattern: ## <model> — Run <N> (<elapsed>s)
    header_pattern = _re.compile(
        r'^## (.+?) — Run (\d+) \((\d+(?:\.\d+)?)s\)\s*$',
        _re.MULTILINE,
    )
    matches = list(header_pattern.finditer(text))
    if not matches:
        print(f"Error: no narrative headers found in {all_md_path}")
        print("Expected format: '## model_name — Run N (Xs)'")
        return ""

    runs: list[NarrativeRun] = []
    for i, m in enumerate(matches):
        model = m.group(1)
        run_index = int(m.group(2)) - 1  # 0-indexed
        elapsed = float(m.group(3))

        # Narrative body is everything between this header and the next (or end)
        start = m.end()
        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            # Stop at concordance section or appendix if present
            end_marker = _re.search(r'^# (?:Concordance|Appendix)', text[start:], _re.MULTILINE)
            end = start + end_marker.start() if end_marker else len(text)

        narrative = text[start:end].strip().rstrip("-").strip()
        runs.append(NarrativeRun(
            model=model,
            endpoint_name="(loaded from file)",
            run_index=run_index,
            narrative=narrative,
            elapsed_seconds=elapsed,
        ))

    print(f"Loaded {len(runs)} narratives from {all_md_path}")
    models_found = sorted(set(r.model for r in runs))
    for model in models_found:
        n = sum(1 for r in runs if r.model == model)
        print(f"  {model}: {n} runs")

    # Run concordance
    print(f"\nRunning concordance analysis with {concordance_model}...")
    conc_text, conc_model = run_concordance_analysis(runs, concordance_model)

    if not conc_text or conc_text.startswith("["):
        print(f"Concordance failed: {conc_text}")
        return conc_text

    # Write output
    out_dir = Path(output_dir) if output_dir else all_md.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    conc_md_path = out_dir / "interpretation_concordance.md"
    conc_md_text = (
        f"# Concordance Analysis\n\n"
        f"*Analyzed by {conc_model}*\n\n"
        f"{conc_text}\n"
    )
    conc_md_path.write_text(conc_md_text)
    print(f"\nConcordance markdown saved to {conc_md_path}")

    return conc_text


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Interpret dose-response BMD results against the bmdx knowledge base",
    )
    sub = parser.add_subparsers(dest="command")

    # Default: full pipeline (no subcommand, uses --csv or positional)
    parser.add_argument("csv", nargs="?", default=None, help="Path to gene-level BMD results CSV")
    parser.add_argument("--csv", dest="csv_flag", default=None, help="Path to gene-level BMD results CSV (alternative to positional)")
    parser.add_argument("--db", default="bmdx.duckdb", help="Path to bmdx.duckdb")
    parser.add_argument("--output", default="output/interpretation.md", help="Output markdown path")
    parser.add_argument("--fdr", type=float, default=0.05, help="FDR cutoff for enrichment")
    parser.add_argument(
        "--models", nargs="+", default=None,
        help="Models for multi-narrative generation (e.g. qwen2.5:14b gemma2:9b claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--runs", type=int, default=3,
        help="Number of narrative runs per model (default: 3)",
    )
    parser.add_argument(
        "--concordance-model", default="claude-sonnet-4-6",
        help="Model for concordance analysis (default: claude-sonnet-4-6)",
    )

    # Subcommand: concordance-only
    conc_parser = sub.add_parser(
        "concordance",
        help="Run concordance analysis on existing narratives",
    )
    conc_parser.add_argument(
        "--input", default="output/interpretation_all.md",
        help="Path to combined all-narratives markdown (default: output/interpretation_all.md)",
    )
    conc_parser.add_argument(
        "--concordance-model", default="claude-sonnet-4-6",
        help="Model for concordance analysis (default: claude-sonnet-4-6)",
    )
    conc_parser.add_argument(
        "--output-dir", default=None,
        help="Output directory for concordance files (default: same as input)",
    )

    args = parser.parse_args()

    if args.command == "concordance":
        concordance_only(
            all_md_path=args.input,
            concordance_model=args.concordance_model,
            output_dir=args.output_dir,
        )
    else:
        csv_path = args.csv_flag or args.csv
        if not csv_path:
            parser.error("csv argument is required for the full pipeline")
        interpret(
            csv_path,
            db_path=args.db,
            output_path=args.output,
            fdr_cutoff=args.fdr,
            models=args.models,
            n_runs=args.runs,
            concordance_model=args.concordance_model,
        )
