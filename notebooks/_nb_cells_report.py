"""
Cells of notebooks/workflow_walkthrough.ipynb, part 2: the report arc
(Process → results → Background/Summary → publish gate → render → compare →
final state).  Assembled by notebooks/_build_workflow_notebook.py; each step's
explanation must stay true to the code it describes.
"""

from __future__ import annotations

CELLS: list[tuple[str, str]] = []


def _md(text: str) -> None:
    CELLS.append(("md", text))


def _code(src: str) -> None:
    CELLS.append(("code", src))


# ---------------------------------------------------------------------------
_md(r"""
## 12. Process

**Purpose.** Turn the integrated data into report content: the statistics
tables, the BMDs, the genomics tables and charts, and the narratives. This is
the heavy step, and the one the caches exist for.

**How it's implemented.** `generate_report.process_async` →
`workflow.steps.process_step` → `pipeline.process_integrated.run_process(dtxsid, params, store)`.
The notebook awaits it, since a notebook cell already runs inside an event
loop (`process`, the command line's version, starts its own with
`asyncio.run`).

**The context.** `_build_process_context` builds a `ProcessContext` passed
through every layer: the compound name (given, else `identity.json`); the dose
unit (`pipeline.study_design.resolve_dose_unit`: stated, else recorded in the
files, else mg/kg); the method (step 10, with `PROCESS_OVERRIDES` as the
request layer), from which come the GO ranking statistics and the GO display
cutoffs (`go_pct`, `go_min_genes`, `go_max_genes`, `go_min_bmd`); the organ,
sex, assay, gene and gene-set filters of the document template or the
session's view; and `integrated.json` (refused with `StepError` 400 if absent).
Before the work starts, the method pin and the document definition pin are
made current (step 10): a session that tracks moves to the newest profile, and
records a changed definition; a fixed one is told when the templates have moved
on (`definition_pin.drift`, logged).

**Concern [1], the data: `run_data`** (ADR-0021). A pure function of the data
and the method.

- **Layer 1, NTP statistics** (`_build_ntp_stats`, cache `ntp`, a few
  seconds). `bmdx_pipe.build_table_data` over the apical experiments (gene
  expression and internal-dose experiments left out) builds every table row:
  group means and standard errors, then the statistics the profile names: the
  Jonckheere trend test decides which pairwise test applies (p ≤ 0.01 →
  Williams for parametric platforms such as body and organ weights, Shirley
  for nonparametric ones such as clinical pathology; otherwise Dunnett or
  Dunn), with critical values from a seeded simulation; relative organ weights
  too. Groups below the minimum size (2) get no test. Each row's BMD comes
  from the `.bm2`'s `bMDResult`, classified by the acceptance rules
  (`bmdx_pipe.bmd_acceptance`: R² ≥ 0.6, BMD/BMDL ≤ 10, BMD ≤ the highest dose;
  below a third of the lowest dose prints as not reportable). Then the rows are
  partitioned by platform, animals in the study roster but missing from a
  table are noted (`annotate_missing_animals`), and absent dose groups are
  filled with "–" (`backfill_missing_doses`).
- **Layer 2, three units at once** (`asyncio.gather`):
  - `_bmds_then_sections`: **apical BMD modelling** (`_get_bmds`, cache
    `bmds`), every endpoint with an eligible trend, fit with the config its
    `.bm2` analysis recorded (BMR, models; parsed from
    `analysisInfo.notes`), or a per-assay inferred config, which is flagged.
    The engine is the Java `RunApicalBmds`: ToxicR Laplace model averaging of
    the Hill, Power, Exponential 3 and Exponential 5 models, the same code
    BMDExpress runs, so where the `.bm2` has a BMD the two must agree (a
    divergence is a hard stop). `fill_rows_from_toxicr` then fills the BMDs
    the `.bm2` lacks. (NIEHS-10's package has no apical `.bm2`, so all its
    apical BMDs are fills.) Only then the **section cards**
    (`_get_sections`, cache `sections`): one per apical platform, its tables
    (body weights from the sidecars' per-animal values), caption, footnotes and
    a programmatic narrative built from templates.
  - `_get_genomics` (cache `genomics`): from `genomics.sidecar.json`, per
    organ × sex: the BMDExpress GENE and GO Biological Process category
    analyses, the gene sets ranked by each GO ranking statistic (top 20), the
    top genes, probe → gene annotation and prefilter fold changes. The cache
    holds the full set; the GO cutoffs and filters are applied after reading
    it, so changing a cutoff refilters instantly.
  - `_get_methods` (cache `methods`): `narrative.methods_report.extract_methods_context`
    gathers the study's facts (identity, fingerprints, animal report, the
    `.bm2`s' analysis settings, the design, the method), one LLM call
    (`build_methods_prompt`) writes the subsections as JSON, and
    `narrative.methods_design.assemble_methods_sections` puts them together
    with the subsections built from data (Study Design, Dose Selection,
    Chemistry), plus Table 1 (sample counts).
- **Layer 2.5, charts** (`_build_charts`, cache `charts`): for each organ ×
  sex, a UMAP map of the GO categories (a precomputed embedding, HDBSCAN
  clusters) and a cluster scatter (gene sets clustered by Jaccard overlap),
  drawn with Plotly and rendered to PNG/SVG by kaleido in an offline Chromium.
  Clusters are labelled with internal GO terms; Enrichr is used only with
  `BMDX_ALLOW_ENRICHR=1`, since it sends gene lists outside.
- **Layer 3, the BMD summary** (`_build_bmd_summary`, cache `bmd_summary`): the
  apical BMD table, sorted by BMD.

**Concern [2], the content: `prepare_content_if_changed`.** A registry of
content kinds, run in dependency order:

- `genomics-llm`: per organ × sex, `narrative.genomics_llm.generate_genomics_narrative_async`.
  It first builds an interpretation against the knowledge base `bmdx.duckdb`
  (`interpret_analysis.build_genomics_interpretation`: pathway and GO
  enrichment by Fisher's test at FDR < 0.05, the order of BMDs, the organ's
  signature, literature per gene; cached as `_cache_interpretation_<organ>_<sex>_*.json`),
  then one LLM call writes the narrative, citing papers as `[Pn]` from the
  catalogue it was given. The citations are checked against that catalogue.
- `genomics-body`: merges those narratives into the genomics sections. A
  person's edits in `genomics_narrative_overrides.json` win. Whether the
  report prints them is the definition's: the 2023 and earlier eras print each
  tissue's interpretation with its table; the 2026 books (and so a new study)
  print instead the sentences written from the tables at render time
  (step 15), and keep these narratives out (`entry_narrative: false`).
- `apical-bmd`: the BMD summary's narrative, a programmatic descriptive part
  and an LLM analytical part.
- `references`: the report-wide reference list, numbered after the
  Background's own, written to `references.json`.

The whole of concern [2] is skipped when nothing it depends on changed: a
fingerprint of the data hashes, the declarations and the override files is
compared with `.prepare_content.fingerprint`, and the outputs are restored from
`.prepare_content.outputs.json`. A run that lost an output is not cached.

**Then.** `_assemble_payload` returns the result (sections, genomics, methods,
BMD summary, narratives, chart images). `_build_query_substrate` builds
`session.duckdb` and `session_parquet/` for querying the session; a failure
there never fails the report. Finally `process_async` calls
`workflow.steps.materialize_result_sections`, which writes each cached apical
section as `bm2_<slug>.json` (`approved: false`, `source: generated`), the files
rendering and approval work on. If a person had approved a section and a
categorical fact under its wording flipped (an effect now significant, say),
the new file carries a `wording_review` flag.

**Reads → writes.** `integrated.json`, the sidecars, `genomics.sidecar.json`,
`_category_lookup.json`, `animal_report.json`, `method_profile.json`,
`identity.json` → `_cache_*.json`, `.prepare_content.*`, `references.json`,
`session.duckdb`, `bm2_<slug>.json`; `document_definition.json` kept current,
and a method profile that tracks the newest moved to it. Process refuses before
it writes anything when the study is not `INTEGRATED` or `APPROVED`
(`phase_not_allowed`), and when no person has chosen its method profile
(`method_not_chosen`, step 10).

**If it goes wrong.** Any failure in concern [1] raises `StepError` 500. An LLM
failure in Methods leaves Methods empty. A content kind that fails is logged,
and its part of the report stays empty until the next run. **Expect two to
three and a half minutes cold**, a few seconds warm.
""")

_code(r"""
import time

params = {"compound_name": SHORT_NAME or identity.get("name") or DTXSID, "dose_unit": DOSE_UNIT,
          **PROCESS_OVERRIDES}
t0 = time.monotonic()
payload = await gr.process_async(DTXSID, params, store)
print(f"  {time.monotonic() - t0:.0f} s")

print("\ncaches (unit — input hash — size):")
for p in sorted(session.glob("_cache_*.json")):
    unit, _, digest = p.stem[len("_cache_"):].rpartition("_")
    print(f"  {unit:34} {digest}  {p.stat().st_size:>12,} bytes")
print("\npayload:", ", ".join(f"{k} ({len(v) if hasattr(v, '__len__') else v})" for k, v in payload.items()))
show_state();
""")

# ---------------------------------------------------------------------------
_md(r"""
### 12b. A look at the results

The apical sections Process just wrote as `bm2_<slug>.json`, with the sexes
their tables cover and the start of each narrative; then the apical BMD summary's
first rows; then each organ × sex section's charts (`payload["chart_images"]`,
base64 PNGs, cached in `_cache_charts_*.json`).
""")

_code(r"""
import base64
from IPython.display import Image, Markdown, display

for key, sec in sorted(store.read_section_dicts(DTXSID).items()):
    if key.startswith("bm2_"):
        sexes = ", ".join(sec.get("tables_json") or {})
        first = (sec.get("narrative") or [""])[0]
        print(f"  {sec.get('title', key)[:26]:26} {sexes:13} {str(first)[:90]}")

rows = (payload.get("apical_bmd_summary") or [])[:8]
if rows:
    print(f"\nmost sensitive apical endpoints ({DOSE_UNIT or 'the unit the data records'}):")
    for r in rows:
        print(f"  {r.get('endpoint', '')[:30]:30} {r.get('sex', ''):6} {r.get('platform', '')[:18]:18} "
              f"BMD {r.get('bmd')!s:>6}  BMDL {r.get('bmdl')!s:>6}  {r.get('bmd_status', '')}  "
              f"({r.get('source')}{', BMR inferred' if r.get('bmr_config') == 'inferred' else ''})")

for sec in payload.get("chart_images") or []:
    display(Markdown(f"**{sec.get('label') or sec.get('organ', '?') + ' / ' + sec.get('sex', '?')}**"))
    for kind in ("umap", "cluster"):
        if sec.get(f"{kind}_png"):
            display(Image(data=base64.b64decode(sec[f"{kind}_png"]), width=520))
if not payload.get("chart_images"):
    print("no genomics charts in this study")
""")

# ---------------------------------------------------------------------------
_md(r"""
## 13. Background and Summary

**The Background.** *Purpose:* what was known about the chemical before this
study, with references. It is about the chemical, not about this data.
*Implementation* (`generate_report.background`, mirroring the browser's
generate-then-save):

1. Resolves the chemical's PubChem CID when `identity.json` lacks it
   (`narrative.chem_resolver.resolve_chemical`).
2. `narrative.data_gatherer.gather_all` queries, in order: PubChem, EPA CompTox
   hazard, ATSDR, IRIS, OSHA/NIOSH limits, drinking-water regulations,
   mechanism papers (Semantic Scholar), and CPDat use data, then lists what is
   missing. It records the sources it couldn't reach.
3. **Refuses** if ATSDR or IRIS couldn't be reached: without the authoritative
   hazard sources the section can't say what is known, or what isn't.
4. `narrative.background_writer.generate_background`: one LLM call writes the
   paragraphs, citing the gathered sources by number; the citations are
   checked.
5. **Refuses** to save prose with no references (its citations would point
   nowhere). Otherwise saves `background.json` unapproved.

With `BACKGROUND = False`, the reference session's Background is copied when
it has one, as `build_published_reports` keeps it across rebuilds.

**The Summary.** *Purpose:* the report's Summary section, from this study's
results. *Implementation:* `workflow.steps.materialize_summary` →
`narrative.report_summary.build_report_summary(**narrative.summary_llm.summary_inputs(session))`,
with no LLM: the same inputs as the Abstract, in NIEHS-10's fixed five-part
shape (a study with apical results only names its single "most sensitive"
endpoint, as NIEHS-05 does). It
writes `summary.json` (`source: generated`, unapproved), and **never** replaces
a Summary a person approved or wrote.

**Reads → writes.** → `background.json`, `summary.json`.
""")

_code(r"""
if BACKGROUND:
    gr.background(DTXSID, identity, "", store)
elif not (session / "background.json").exists():
    src = REFERENCE / "background.json" if REFERENCE else None
    if src and src.exists():
        shutil.copy2(src, session / "background.json")
        print(f"  Background copied from sessions/{SOURCE}/ (unapproved, as written there)")
    else:
        print("  no Background (set BACKGROUND = True to write one)")
gr.summary(DTXSID, store)
for name in ("background.json", "summary.json"):
    sec = store.read_json(DTXSID, name) or {}
    print(f"  {name:16} {len(sec.get('paragraphs') or [])} paragraph(s), "
          f"{len(sec.get('references') or [])} reference(s), approved={bool(sec.get('approved'))}")
""")

# ---------------------------------------------------------------------------
_md(r"""
## 14. Sections and the publish gate

**Purpose.** The report's authorable sections are files, each with an
approval. A first report needs no approvals: unapproved sections render as
drafts. Approval matters once the data changes under a section a person has
already accepted.

**How it's implemented.**

- `store.read_section_dicts(dtxsid)` reads every section file (`background`,
  `summary`, `bm2_<slug>`, …).
- `WorkflowEngine.publish_readiness()` → `workflow.reprocess.blocking_llm_sections`:
  a reprocess marks the **LLM-written** sections stale (their text may no longer
  match the data) and records why. Each stale one blocks publishing until a
  person accepts it again. Programmatic sections never block; they are rebuilt
  from the data.
- `workflow.steps.accept_section_step(dtxsid, key, store)` approves a section:
  `approved: true`, `approved_at`, clears `stale` and `wording_review`, promotes
  its facts to FINAL (ADR-0015), and records a "blessed" event on the
  section's version history without minting a new version.
- `workflow.steps.release_section_step(dtxsid, key, store, reason=…)` reopens
  one: `approved: false`, FINAL withdrawn (PROTECTED stays), and the reason
  recorded.

**Reads → writes.** Section files (only when accepting or releasing).
""")

_code(r"""
from workflow.steps import accept_section_step, release_section_step

for key, sec in sorted(store.read_section_dicts(DTXSID).items()):
    flags = [f for f in ("approved", "stale", "wording_review") if sec.get(f)]
    print(f"  {key:32} {', '.join(flags) or 'draft'}")

readiness = WorkflowEngine(DTXSID, store).publish_readiness()
print("\ncan publish:", readiness["can_publish"], readiness["blocking"] or "")
# accept_section_step(DTXSID, "bm2_body-weight", store)    # approve one section
# release_section_step(DTXSID, "bm2_body-weight", store)   # and reopen it
""")

# ---------------------------------------------------------------------------
_md(r"""
## 15. Render the deliverables

**Purpose.** Write the report in the formats it is delivered in. Every surface
is a projection of the same data and the same document tree, so they can't
disagree about content or numbering.

**How it's implemented.** `generate_report.render(dtxsid, surfaces, out, view, strict)`
writes each surface to `OUT/<DTXSID><suffix>`. For all but LaTeX/PDF it calls
`rendering.preview_surface.render_preview(dtxsid, surface)`:

1. **The data** (`_preview_inputs` → `rendering.latex_export.load_session_data`):
   a scaffold with every part of a report, overlaid with what the session has:
   the caches (sections, BMD summary, genomics, methods), the section files
   (Background, Summary, apical sections), the front matter, the deposit.
   Anything missing shows as a visible "[pending]" placeholder, never as
   silence. A report over several studies (`studies.json`) is composed from
   its member sessions (`rendering.report_compose`). A published report's
   companion (step 16) has none of a study's data: the published book's
   content is laid over the scaffold instead (`rendering.published_clone.apply_clone`).
2. **The tree** (`document_model.view_config.build_view_tree`): the first of
   the session view's own structure, the session's `document.yaml`, or the
   study's document definition (step 10): its pinned snapshot when the
   session fixes it, else its own (`templates/studies/<DTXSID>/document.yaml`,
   its era's base plus the study's alterations, ADR-0029), else the
   definition of a new study (`templates/eras/niehs-2026.yaml`). The shared
   template `templates/niehs-5day-report.yaml` is the base grammar every era
   extends. `study_tree` then fits the tree to the study: tables of domains it
   didn't collect drop out, sections gated on another route
   (`requires_route: inhaled`) drop out, and repeated sections are copied per
   study, per tissue or per deposited species (`repeat`).
   `study_document_facts` adds the definition's series details, packaging,
   object placement, tissue order, abstract convention and **phrasing**.
3. **The prose written from the tables**, once the tree has numbered them
   (`latex_export._number_and_list`), in the words the definition's
   `phrasing:` block declares (ADR-0029 §11; nothing when it declares none,
   as the 2023 and earlier eras don't):
   - `rendering.genomics_results`: the gene set and gene analyses' openings,
     each tissue's results per study and the gene set summary, by the books'
     rules (the lower limit of extrapolation, the two most potent gene sets
     and any tied, the "One gene / All N / Half / Only N" forms). Gene names
     come from `assets/gene_names.json` (NCBI, looked up only with
     `BMDX_ALLOW_NCBI_GENE=1`); the short name from `identity.json`'s
     `abbreviation` (step 9).
   - `rendering.genomics_appendix`: Appendix D.2's eFDR methods, results and
     table from `efdr.json` (step 9) and the method profile's `genomics.efdr`;
     Appendix E's gene set definitions (GO definitions from
     `resources/go/go-basic.obo`, or `BMDX_GO_OBO`) and gene identifiers.
     What no source supplies (the gene definitions; GO definitions without
     the file) prints as a visible placeholder.
   The appendix and tables those sentences cite are the nodes the definition
   declares `cited_as`.
4. **The surface** (`render_surface`, with cross-references numbered from the
   tree), over the shared intermediate form in `rendering.render_common`:
   - `docx`: `rendering.docx_generator.generate_docx`, on the styles of
     `assets/templates/niehs-10-base.docx` (the NTP report template's styles);
   - `html`: `rendering.html_generator.generate_html`;
   - `jats`: `rendering.jats_generator.generate_bits`, one BITS XML book;
   - `bits`: the same book split into Bookshelf's parts
     (`rendering.bits_bundle.bundle_zip`: `TOC.nxml`, one `.nxml` per part,
     the chart images), zipped. It is what the Bookshelf ingests;
   - `bookshelf`: the BITS book rendered as a Bookshelf page
     (`rendering.bookshelf_preview`). The page says what it is: a preview of
     how the report will read on NCBI Bookshelf (a study not yet published);
     a version of a report already published, generated by the pipeline, to
     evaluate the pipeline by (a published study's generated report); or the
     report as published (a companion, step 16). Served by the app at
     `/Bookshelf/<dtxsid>`, its "Bookshelf" wordmark and the "rlm-bmdx Report
     Series" panel lead back to the shelf;
   - `latex` / `pdf`: the Overleaf bundle (`rendering.latex_export`), compiled
     with `tect` for the PDF.

In a workspace of your own the session is the study's own id, so it renders
from NIEHS-10's own definition (`templates/studies/DTXSID50469320/`, the 2023
books'), as the reference session does. The scratch session in the
repository's sessions (`<SOURCE>_nb`) has no definition of its own, so it
renders as a **new study** would: from the 2026 books' definition, not
NIEHS-10's 2023 one. The structure is the 2026 books': Chemistry first, the
apical results under "Apical Endpoint Analysis", each tissue's gene set and
gene results under its own heading written from the tables, the eFDR and
definitions appendices. The inhalation-only sections drop out, since NIEHS-10
was a gavage study. So the next step's comparison with the NIEHS-10 book shows
those era differences, which the reference session (and a workspace's session)
doesn't have.

**Reads → writes.** The session → `OUTPUT_DIR/<DTXSID>/<DTXSID>.docx`, `.html`,
`-bits.zip`, ….
""")

_code(r"""
written = gr.render(DTXSID, SURFACES, OUT, None, False)
for p in written:
    print(f"  {p}  ({p.stat().st_size / 1024:.0f} KB)")
""")

# ---------------------------------------------------------------------------
_md(r"""
## 16. Compare with the published report

**Purpose.** See how far the generated report is from the one NIEHS
published: the QC loop for the whole tool.

**How it's implemented.** `rendering.bits_compare`:

1. `load_book` reads both books as BITS: the published one from
   `assets/cebs/_bookshelf/<REPORT>/` (the Bookshelf package), ours from the
   `-bits.zip` above, with their images.
2. `compare` flattens each into **sections** keyed by heading path, and pairs
   the sections by path (renamed ones by similarity). Within a pair it aligns
   the **blocks** (paragraphs, list items, table rows, figures, references) by
   content, then diffs paired blocks word by word. Each pair is classed as
   same, typography only (quotes, dashes, spacing), changed, moved, added or
   removed.
3. Tables are aligned by meaning, not position
   (`rendering.bits_compare_tables`): columns by header (abbreviations
   allowed), rows by group and label (`Female › Liver › Weight`), so a reordered
   or renumbered table still lines up.
4. `rendering.bits_compare_page.render_page` writes the self-contained page:
   side-by-side or unified view, hide unchanged, mute typography, `j`/`k` to
   step through changes. `unified_diff` writes a conventional `.diff`.

The same comparison runs for every published report with
`python -m tooling.report_compare` (written to `output/QC/compare/`) and in the
browser at `/Compare/<dtxsid>`.

**The published book as a session.** Each published report's generated
session has a companion, `sessions/<DTXSID>_published`: the published book's
own content (not the Bookshelf page around it) as an ordinary report, so it
renders through every surface and can be compared node for node.
`tooling.published_clone.build(report, twin)` reads the book's Bookshelf
package (`rendering.published_clone.clone_book`). Its parts, headings,
paragraphs, tables (header rows, inline marks, lettered notes), figures with
their notes, appendices, references, authors and abstract become the
session's `document.yaml` (checked as a full tree build) and
`published_content.json`. `published_clone.json` records the report, the
twin, the package's hash and the clone's format, and the companion is rebuilt
only when one of them changes. The tree numbers the companion's tables and
figures as in any report; `check` renders its BITS, compares it with the book
the same way as above, and lists any table or figure whose number differs from
the book's. On `/Bookshelf` the generated report's card links it
("Published content →"), and its page links back.

**Reads → writes.** → `output/<DTXSID>/<DTXSID>-compare.html`,
`<DTXSID>-compare.diff`; `sessions/<SOURCE>_published/` (the companion of the
reference session, the one the shelf shows). The table lists the sections that differ most. For
this scratch session they include the era differences step 15 describes; the
reference session, rendered from NIEHS-10's own definition, is the measure of
how close the tool gets to the book.
""")

_code(r"""
from rendering.bits_compare import compare, load_book, unified_diff
from rendering.bits_compare_page import render_page

if not REPORT:
    print("Your own study has no published book to compare with; the report is in", OUT)
else:
    if "bits" not in SURFACES:
        gr.render(DTXSID, ["bits"], OUT, None, False)
    pub_book, pub_images = load_book(BOOKSHELF / REPORT)
    our_book, our_images = load_book(OUT / f"{DTXSID}-bits.zip")
    cmp = compare(pub_book, our_book, left_images=pub_images, right_images=our_images)

    page = OUT / f"{DTXSID}-compare.html"
    page.write_text(render_page(cmp, title=f"{REPORT} · {NAME} — published vs this notebook",
                                left_label=f"Published — {REPORT}", right_label=f"Generated — {DTXSID}"),
                    encoding="utf-8")
    (OUT / f"{DTXSID}-compare.diff").write_text(
        unified_diff(cmp, f"published/{REPORT}", f"generated/{DTXSID}"), encoding="utf-8")

    print(f"{cmp.sim:.0%} of the words match;", ", ".join(f"{n} {s}" for s, n in sorted(cmp.counts().items())))
    print("by kind:", "; ".join(f"{g} {v:.0%}" for g, (v, w) in cmp.by_kind().items() if w))
    print("page:", page)

    rows = [(sp, sim) for sp, (sim, st) in zip(cmp.sections, cmp.subtree()) if sp.changes]
    rows.sort(key=lambda r: r[1])
    display(Markdown("| section | words match | changed blocks | status |\n|---|---|---|---|\n" + "\n".join(
        f"| {' › '.join(sp.section.path)} | {sim:.0%} | {sp.changes} | {sp.status} |" for sp, sim in rows[:15])))
""")

_code(r"""
# The published book as a session: the companion of the reference session.
from tooling.published_clone import build, check

if REPORT:
    companion, rebuilt = build(REPORT, SOURCE)
    print(f"{companion}: {'built' if rebuilt else 'up to date'}")
    res = check(REPORT, companion)
    print(f"{res['sim']:.1%} of the book's words match;",
          ", ".join(f"{n} {s} {k}" for (s, k), n in sorted(res["off"].items())) or "every block the same")
    print("tables and figures numbered as the book:", "yes" if not res["numbered"] else res["numbered"])
""")

# ---------------------------------------------------------------------------
_md(r"""
## 17. Where things stand

The final derived state and the session's files. The session is an ordinary
one: it shows in the browser's session list and on `/Bookshelf`. In a
workspace of your own it is the study's own session, so the workspace's
Bookshelf (port 9300 by default) shows it as the published report's generated version,
its card linking the published content. The scratch session in the
repository's sessions is listed among the unpublished reports instead, since
the shelf counts as published only the study's own session (`SOURCE`), whose
card links the companion. To remove it, delete `SESSIONS_DIR/<DTXSID>/` and
`OUTPUT_DIR/<DTXSID>/`; the companion (`SESSIONS_DIR/<SOURCE>_published/`)
belongs to the shelf and stays.
""")

_code(r"""
show_state()
print()
for p in sorted(session.glob("*.json")):
    print(f"  {p.name:42} {p.stat().st_size:>10,} bytes")
print("\ndeliverables:")
for p in sorted(OUT.iterdir()):
    print(f"  {p}  ({p.stat().st_size / 1024:.0f} KB)")
""")
