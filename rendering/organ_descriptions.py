"""
rendering/organ_descriptions.py — the appendix "Organ Weight Descriptions":
one paragraph per organ the study weighed, "**Liver:** The liver carries out
…" (NIEHS-02 … 13).

Which organs: those the study weighed (the organ-weight endpoints of its
integrated dataset, "Liver", "Kidney-Left" …; the paired kidneys are one
Kidney — the dataset, not the report's organ-weight table, which a view may
narrow: NIEHS-10's shows the liver only, yet the book describes the kidney
and heart it weighed) and the tissues it sequenced (its genomic sections) —
never a fixed list, so a study that neither weighed nor sequenced a heart
describes none.
That rule gives every published book's list: NIEHS-02 … 06 Brain, Liver;
NIEHS-07 … 10 Liver, Kidney, Heart; NIEHS-12, 13 the five tissues, the ovary
sequenced but not weighed.
The words: the document definition's ``organ_descriptions`` (an organ's text,
the books' own) in its ``organ_description_order`` (the 2023 books describe
Liver, Kidney, Heart; the 2026 books go alphabetically), organs the order
does not name after it alphabetically.  An organ the definition has no text
for prints a visible placeholder, never nothing.
"""

from __future__ import annotations

from rendering.render_common import make_bold

DATA_KEY = "organ_weight_descriptions"

# A paired organ weighed side by side is described once (NIEHS-07 … 13:
# "Kidney" for Kidney-Left and Kidney-Right); "Lungs" is the Lung.
_SAME_ORGAN = {"kidney-left": "Kidney", "kidney-right": "Kidney", "left kidney": "Kidney",
               "right kidney": "Kidney", "kidneys": "Kidney", "lungs": "Lung",
               "ovaries": "Ovary", "testes": "Testis"}
# The organ-weight endpoints that are not an organ.
_NOT_ORGANS = {"terminal body weight", "terminal body wt.", "body weight"}


def _organ_name(name: str) -> str:
    return _SAME_ORGAN.get(name.lower(), name[:1].upper() + name[1:].lower())


def described_organs(weighed: list[str], data: dict) -> list[str]:
    """The organs the study weighed, then the tissues it sequenced, each once,
    as the descriptions name them ("Liver", "Kidney")."""
    out: list[str] = []
    for name in weighed:
        if name.strip().lower() not in _NOT_ORGANS and _organ_name(name.strip()) not in out:
            out.append(_organ_name(name.strip()))
    for entry in data.get("genomics_sections") or []:
        organ = str((entry or {}).get("organ") or "").strip()
        if organ and _organ_name(organ) not in out:
            out.append(_organ_name(organ))
    return out


def weighed_organs(integrated: dict | None) -> list[str]:
    """The endpoints of the integrated dataset's organ-weight experiments
    ("Kidney-Left", "Liver", "Terminal Body Weight"), in their order."""
    out: list[str] = []
    for exp in (integrated or {}).get("doseResponseExperiments") or []:
        if ((exp.get("experimentDescription") or {}).get("platform")) != "Organ Weight":
            continue
        for resp in exp.get("probeResponses") or []:
            probe = resp.get("probe") if isinstance(resp, dict) else None
            name = probe.get("id") if isinstance(probe, dict) else None
            if name and name not in out:
                out.append(str(name))
    return out


def study_weighed_organs(dtxsid: str) -> list[str]:
    """The organ-weight endpoints of a session's integrated dataset; for a
    report over several studies (rendering.report_compose), its studies'."""
    import json

    from pipeline.session_store import session_path
    from rendering.report_compose import member_sessions

    out: list[str] = []
    for session in [m for _, m in member_sessions(dtxsid)] or [dtxsid]:
        try:
            integrated = json.loads((session_path(session) / "integrated.json")
                                    .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out += [n for n in weighed_organs(integrated) if n not in out]
    return out


def organ_description_paragraphs(organs: list[str], texts: dict, order: list[str]) -> list:
    """The appendix's paragraphs (inline content) for ``organs``, in ``order``
    then alphabetically, from the definition's ``texts``."""
    rank = {o.lower(): i for i, o in enumerate(order or [])}
    ordered = sorted(organs, key=lambda o: (rank.get(o.lower(), len(rank)), o.lower()))
    by_name = {k.lower(): v for k, v in (texts or {}).items()}
    out = []
    for organ in ordered:
        text = by_name.get(organ.lower()) or (
            f"[Placeholder: the document definition has no description of the {organ.lower()}]")
        out.append([make_bold(f"{organ}:"), f" {text}"])
    return out


def attach_organ_descriptions(data: dict, weighed: list[str], texts: dict,
                              order: list[str]) -> None:
    """``data[DATA_KEY]``: the paragraphs for the organs the study weighed
    (``weighed``, study_weighed_organs) or sequenced.  Nothing when the
    definition declares no descriptions (it binds no node to them) or the
    study has no organ."""
    if not texts:
        return
    organs = described_organs(weighed, data)
    if organs:
        data[DATA_KEY] = {"paragraphs": organ_description_paragraphs(organs, texts, order)}
