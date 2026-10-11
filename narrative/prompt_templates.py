"""
narrative/prompt_templates.py — a section's prompt as an editable, versioned file.

A model-written section is generated from a TEMPLATE: Markdown with YAML front
matter (`system`, and optionally `model`, `temperature`, `max_tokens`) and a
Jinja2 body. The study's material — the facts code picked, the chemical, the
design — arrives as template variables, so editing the wording can never edit
the data. Undefined variables fail loudly (StrictUndefined), and both the
system text and the body are rendered.

One template per section TYPE, used for every report. Version 1 is the shipped
default (narrative/prompts/<section>.md); edits are saved as new immutable
versions by pipeline.prompt_store.

    ---
    system: |
      You are …
    temperature: 0.3
    ---
    Rewrite this draft for {{ chemical_name }}: …
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import jinja2
import yaml

from pipeline import prompt_store

PROMPTS_DIR = Path(__file__).parent / "prompts"

# The sections whose prompt is a template. Each entry documents the variables
# its input builder supplies, for the editor's reference panel.
SECTIONS: dict[str, dict] = {
    "summary": {
        "label": "Summary",
        "variables": {
            "draft_paragraphs": "The Summary built from the data with fixed wording "
                                "(narrative.report_summary): the facts code picked, as a list "
                                "of paragraphs. Every number the output may state is here.",
            "chemical_name": "The test article's name.",
            "species": "The species, plural (e.g. \"rats\").",
            "strain": "The strain, when the data records it (else empty).",
            "route": "The route, when the data records it (e.g. \"gavage\", \"inhaled\"; else empty).",
            "duration_days": "The dosing duration in days, when recorded (else empty).",
            "sexes": "The sexes studied, e.g. [\"Male\", \"Female\"].",
            "dose_unit": "The dose unit (e.g. \"mg/kg\", \"ppm\").",
            "dose_groups": "The dose levels, control included.",
            "abstract_background": "The Background's two-sentence abstract (may be empty).",
            "apical_evaluated": "Whether the study measured apical endpoints.",
            "has_genomics": "Whether the study has transcriptomic results.",
        },
    },
}

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 4096

_ENV = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=False,
                          autoescape=False)


class UnknownSection(ValueError):
    """A section name with no prompt template."""


class TemplateError(ValueError):
    """A template that cannot be parsed or rendered; the message says where."""


@dataclass
class RenderedPrompt:
    """Exactly what is sent to the model."""
    system: str
    user: str
    model: str
    temperature: float
    max_tokens: int

    def to_dict(self) -> dict:
        return asdict(self)


def validate_section(section: str) -> str:
    if section not in SECTIONS:
        raise UnknownSection(f"no prompt template for section {section!r}")
    return section


def default_text(section: str) -> str:
    return (PROMPTS_DIR / f"{validate_section(section)}.md").read_text(encoding="utf-8")


def template_text(section: str, version: int | None = None) -> tuple[str, int]:
    """(text, version) — the given version, or the current one."""
    validate_section(section)
    v = prompt_store.current_version(section) if version is None else int(version)
    text = prompt_store.read_version_file(section, v)
    return (default_text(section) if text is None else text), v


def parse(text: str) -> tuple[dict, str]:
    """Split front matter from body. Raises TemplateError."""
    if not text.startswith("---"):
        raise TemplateError("The template must start with a '---' front-matter block "
                            "holding at least `system:`.")
    parts = text.split("\n---", 2)
    if len(parts) < 2:
        raise TemplateError("The front matter has no closing '---' line.")
    head = parts[0][3:]
    body = parts[1].split("\n", 1)[1] if "\n" in parts[1] else ""
    if len(parts) == 3:  # a '---' inside the body: keep it
        body += "\n---" + parts[2]
    try:
        meta = yaml.safe_load(head) or {}
    except yaml.YAMLError as e:
        raise TemplateError(f"Front matter is not valid YAML: {e}") from e
    if not isinstance(meta, dict) or not str(meta.get("system") or "").strip():
        raise TemplateError("The front matter needs a non-empty `system:`.")
    unknown = set(meta) - {"system", "model", "temperature", "max_tokens"}
    if unknown:
        raise TemplateError(f"Unknown front-matter keys: {', '.join(sorted(unknown))}.")
    return meta, body.strip("\n")


def _render_one(source: str, variables: dict, where: str) -> str:
    try:
        return _ENV.from_string(source).render(**variables).strip()
    except jinja2.TemplateSyntaxError as e:
        raise TemplateError(f"{where}, line {e.lineno}: {e.message}") from e
    except jinja2.UndefinedError as e:
        raise TemplateError(f"{where}: {e.message} (see the variable list)") from e
    except Exception as e:  # a filter or expression failing on the data
        raise TemplateError(f"{where}: {e}") from e


def render(text: str, variables: dict) -> RenderedPrompt:
    """Render a template against a section's variables. Raises TemplateError."""
    meta, body = parse(text)
    try:
        temperature = float(meta.get("temperature", DEFAULT_TEMPERATURE))
        max_tokens = int(meta.get("max_tokens", DEFAULT_MAX_TOKENS))
    except (TypeError, ValueError) as e:
        raise TemplateError(f"temperature/max_tokens must be numbers: {e}") from e
    return RenderedPrompt(
        system=_render_one(str(meta["system"]), variables, "system"),
        user=_render_one(body, variables, "body"),
        model=str(meta.get("model") or DEFAULT_MODEL),
        temperature=temperature,
        max_tokens=max_tokens,
    )
