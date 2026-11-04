"""
document_model/knowledge_base_assignment.py — name the knowledge base a
report reads, in its document definition.

A report reads the knowledge base its document definition names
(``knowledge_base:``, document_model.document_definition), else the default
(knowledge_base.registry).  Assigning one writes that key into the report's
own definition, ``templates/studies/<id>/document.yaml``:

* a study a report composes (NIEHS-12/13's ``<id>_rat``) is assigned through
  its report: one report, one knowledge base;
* a report with no definition of its own gets one, extending the definition
  it renders from now, so nothing else about it changes;
* the line is replaced in place, so the file's comments stay; assigning
  ``None`` removes it, and the report reads the default again.

A session that FIXES its definition (document_model.definition_pin) renders
from its snapshot and does not see the change until it is pinned again.
This core step assigns whatever it is given; safeguards.knowledge refuses a
knowledge base that cannot ground the report's genomics interpretation, and
a fixed definition.  The next Process takes the change up
(pipeline.kb_currency).
"""

from __future__ import annotations

import re

from document_model.document_definition import (
    _templates_dir,
    current_definition_name,
    report_of_member,
    study_definition_name,
)

_KEY_LINE = re.compile(r"^knowledge_base:.*\n?", re.MULTILINE)


def report_id(dtxsid: str) -> str:
    """The session whose definition holds the report's knowledge base."""
    report = report_of_member(dtxsid)
    return report if report and report != dtxsid else dtxsid


def assign(dtxsid: str, name: str | None) -> dict:
    """Write ``knowledge_base: <name>`` into the report's definition (None
    removes it).  Returns ``{report, definition, path, created, previous}``."""
    from document_model.document_template import load_knowledge_base
    from knowledge_base.registry import check_name

    if name is not None:
        check_name(name)
    report = report_id(dtxsid)
    own = study_definition_name(report)
    definition = own or f"studies/{report}/document"
    path = _templates_dir() / f"{definition}.yaml"
    previous = load_knowledge_base(own) if own else None
    if own:
        text = path.read_text(encoding="utf-8")
    else:
        text = (f"# The document definition of {report}: the one it rendered from, "
                f"with its knowledge base\n# named (document_model.knowledge_base_assignment).\n"
                f"extends: {current_definition_name(report)}\n")
    line = f"knowledge_base: {name}\n" if name is not None else ""
    if _KEY_LINE.search(text):
        text = _KEY_LINE.sub(line, text, count=1)
    elif line:
        text = text if text.endswith("\n") else text + "\n"
        text += line
    if own or name is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return {"report": report, "definition": definition, "path": str(path),
            "created": not own and name is not None, "previous": previous}
