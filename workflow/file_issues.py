"""
workflow.file_issues — what the file check found, in words a toxicologist reads.

``validate_step`` writes ``validation_report.json``: a list of issues, each with
a ``severity``, an ``issue_type``, the names of the files it involves, and a
message written for whoever is reading a log.  This module turns one of those
into the three things a person needs:

  * **which group it belongs in** — what must be fixed before the files can be
    combined, what is worth a look, and what is expected of this kind of
    package.  The group follows the severity the check gave, except where a
    type is always one or the other;
  * **what it says**, in plain words, with the files named as the person
    brought them in;
  * **what to do about it**, where there is something to do.

An issue type this module does not know keeps the check's own message and is
marked as not recognized, rather than being dropped or guessed at.

The words live here, in the core, so the command line and the interface say the
same thing about the same finding.  Nobody is addressed, and the spelling is
American (the rules for text the study team reads).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: The groups an issue falls in, worst first.
GROUPS = ("fix", "look", "expected", "elsewhere")

GROUP_SAY = {
    "fix": "Must be fixed before the files can be combined",
    "look": "Worth a look",
    "expected": "Expected for this kind of package",
    "elsewhere": "Shown with the analysis method",
}


@dataclass(frozen=True)
class Words:
    """What a kind of finding means."""
    say: str
    what_to_do: str | None = None
    #: The group, when the type is always in one; otherwise the severity decides.
    group: str | None = None
    #: The module that accounts for it instead, where one does.
    feeds: str | None = None
    #: Whether the app settles it, or a person settles it outside the app.
    settle: str | None = None


#: The severity the check gives, where the type does not fix the group itself.
BY_SEVERITY = {"error": "fix", "warning": "look", "info": "expected"}

ISSUES: dict[str, Words] = {
    # --- the files against each other (bmdx_pipe.file_integrator) ------------
    "unassigned_file": Words(
        say="The check cannot tell what {files} holds, from its name.",
        what_to_do="Say what it is, or remove it if it is not this study's data.",
        group="fix"),
    "dose_mismatch": Words(
        say="{platform}: {files} do not agree on the dose groups.",
        what_to_do="Only one of them can be this study's data. Remove the other, "
                   "or correct it outside the application and check again.",
        settle="outside"),
    "animal_count_mismatch": Words(
        say="{platform}: the study workbook records {xlsx_count} animals and the "
            "tables {txt_csv_count}.",
        what_to_do="An animal the tables leave out is accounted for in the data "
                   "review. An animal the study workbook does not have must be "
                   "corrected outside the application.",
        feeds="M6"),
    "workbook_conflict": Words(
        say="Two study workbooks describe {platform}: {files}. Only one can be "
            "the study's.",
        what_to_do="Remove the one that is not this study's.",
        group="fix"),
    "dose_not_in_study": Words(
        say="{files} records a dose group the study's workbooks do not have: {message}",
        what_to_do="The workbook states the study. Correct the file outside the "
                   "application, or remove it.",
        group="fix"),
    "sex_not_in_study": Words(
        say="{files} records animals of a sex the study's workbooks do not have: {message}",
        what_to_do="The workbook states the study. Correct the file outside the "
                   "application, or remove it.",
        group="fix"),
    "endpoint_not_in_study": Words(
        say="{files} measures something the study's workbook does not record: {message}",
        what_to_do="Correct the file outside the application, or remove it.",
        group="fix"),
    "redundant_files": Words(
        say="{files} look alike: the same assay, the same sexes, the same "
            "doses, the same measurements.",
        what_to_do="Looking alike is not proof of being the same. Read both; "
                   "if one of them is not this study's, remove it.",
        settle="outside"),
    "duplicate_files": Words(
        say="{files} are the same file under different names. Combining both "
            "would count the same data twice.",
        what_to_do="Remove either one — they are the same file.",
        group="fix"),
    "several_test_articles": Words(
        say="{files} holds experiments of more than one test article: "
            "{test_articles}. Only one of them is this study's.",
        what_to_do="A project of two chemicals carries another study's data, "
                   "and its benchmark doses would be read as this study's. "
                   "Narrow the project to this study's experiments outside the "
                   "application, or remove it.",
        settle="outside"),
    "name_disagrees_with_contents": Words(
        say="{files} is named for {named}, but what it measures matches "
            "{contents_match} better.",
        what_to_do="A file is recognized from its name, so this one is taken "
                   "for something it may not be. Say what it is, or remove it "
                   "if it is not this study's data.",
        group="fix"),
    "sex_mismatch": Words(
        say="{platform}: {message}"),
    "file_not_checked": Words(
        say="{files} could not be checked against the study's workbooks: {message}"),
    "missing_tier": Words(
        say="{platform}: {message}"),
    "roster_subset": Words(
        say="{files} holds {file_count} of the study's {roster_count} {sex} "
            "animals; {missing_count} are not in it.",
        what_to_do=None,
        feeds="M6"),
    "samples_unresolved": Words(
        say="{files}: {message}",
        what_to_do="A sample that cannot be traced to an animal is left out of "
                   "the dataset. A sample sheet naming them would place them."),

    # --- the values against the workbook (pipeline.value_validation) ---------
    "value_mismatch": Words(
        say="{platform}: {count} of {total} values in {files} differ from the "
            "study workbook. For example {example}.",
        what_to_do="A table has to be an exact copy of the workbook's data. "
                   "Correct it outside the application, or remove it and let the "
                   "check write it from the workbook.",
        group="fix"),
    "value_dose_mismatch": Words(
        say="{platform}: {count} values in {files} are filed under a different "
            "dose than the study workbook gives. For example {example}.",
        what_to_do="Correct the file outside the application, or remove it.",
        group="fix"),
    "value_selection_mismatch": Words(
        say="{platform}: {count} values in {files} mark an animal as core or "
            "biosampling differently from the study workbook. For example {example}.",
        what_to_do="Correct the file outside the application, or remove it.",
        group="fix"),
    "value_terminal_mismatch": Words(
        say="{platform}: {count} values in {files} are marked terminal "
            "differently from the study workbook. For example {example}.",
        what_to_do="Correct the file outside the application, or remove it.",
        group="fix"),
    "value_missing_in_csv": Words(
        say="{platform}: {count} values the study workbook records are not in "
            "{files}. For example {example}.",
        what_to_do="A dropped measurement would be missing from the report. "
                   "Correct the file outside the application, or remove it.",
        group="fix"),
    "value_missing_in_xlsx": Words(
        say="{platform}: {count} values in {files} are not in the study "
            "workbook. For example {example}.",
        what_to_do="A value the study does not record cannot go in the report. "
                   "Correct the file outside the application, or remove it.",
        group="fix"),
    "unverified_derived_data": Words(
        say="{platform}: there is no study workbook to check the values in "
            "{files} against, so they are used as given.",
        what_to_do="Bringing in the platform's study workbook would check them."),

    # --- the values the package says were left out (ADR-0037) ----------------
    "excluded_value_not_found": Words(
        say="{files} names a value left out of the analysis that the study's "
            "tables still hold: {message}",
        what_to_do="Either the file or the table is wrong. Correct one outside "
                   "the application and check again.",
        group="fix"),
    "excluded_values_applied": Words(
        say="{message}",
        group="expected"),
    "excluded_values_unreadable": Words(
        say="{files} names the values left out of the analysis, but it cannot "
            "be read: {message}",
        what_to_do="Correct the file outside the application, or remove it."),
}

#: Findings about the analysis method, shown with the method rather than here.
ELSEWHERE = {"method_mismatch"}


# ---------------------------------------------------------------------------
# Turning one into words
# ---------------------------------------------------------------------------

class _Fields(dict):
    """A format mapping that leaves an unknown field visible instead of raising."""

    def __missing__(self, key):  # pragma: no cover - a guard, not a path
        logger.warning("the words for a file issue name %r, which it does not carry", key)
        return f"[{key} not recorded]"


def _listed(things: list) -> str:
    """A list as a person reads one: "a", "a and b", "a, b and c"."""
    said = [str(one) for one in things if one is not None]
    if not said:
        return "none"
    if len(said) == 1:
        return said[0]
    return ", ".join(said[:-1]) + " and " + said[-1]


def _files_say(issue: dict, names: dict[str, str]) -> str:
    """The files an issue involves, by the names a person brought them in under."""
    involved = [names.get(f, f) for f in (issue.get("files_involved") or [])]
    if not involved:
        return "the study's files"
    return _listed(involved)


def _platform_say(platform: str | None) -> str:
    """The assay, as a person names it.

    The check files its findings under the coverage key — "Body Weight|tox_study",
    or "gene_expression" — which is how the dataset is indexed, not how an assay
    is spoken of.
    """
    if not platform:
        return "This assay"
    if platform == "gene_expression":
        return "Gene expression"
    return platform.split("|", 1)[0]


def _bare_message(issue: dict, names: dict[str, str]) -> str:
    """The check's message without the prefix the words already say.

    The check writes "Body Weight|tox_study: no .bm2 … found" and
    "project.bm2: 198 samples …" — printing the platform or the file name
    again around that reads as a stutter.
    """
    message = issue.get("message") or ""
    prefixes = [issue.get("platform") or "", _platform_say(issue.get("platform"))]
    prefixes += [names.get(f, f) for f in (issue.get("files_involved") or [])]
    for prefix in prefixes:
        if prefix and message.startswith(f"{prefix}: "):
            return message[len(prefix) + 2:]
    return message


#: The tiers `missing_tier` reports, by the phrase the check writes for each.
#: A BMDExpress project is not required for an apical platform (the maintainer,
#: 2026-10-16): Process computes its benchmark doses itself.
_MISSING_TIER = {
    # Gene expression comes as a BMDExpress project; there is no workbook and
    # no table behind it, so neither is a gap.
    "gene expression input data": Words(
        say="Gene expression: the BMDExpress project is the only record of it. "
            "The table it was analyzed from is not in the study.",
        group="expected"),
    "no .bm2": Words(
        say="{platform}: no BMDExpress project. Process computes this assay's "
            "benchmark doses itself.",
        group="expected"),
    "no xlsx": Words(
        say="{platform}: no study workbook. Its tables are used as they are, "
            "and their values are not checked against one.",
        group="expected"),
    "no txt/csv": Words(
        say="{platform}: there is a study workbook but no table was written "
            "from it, so nothing of this assay would be combined.",
        what_to_do="Check the files again, which writes the tables from the "
                   "workbook.",
        group="look"),
}


def _words_for(issue: dict) -> Words | None:
    """The words for this finding, or None when it is not one this module knows."""
    issue_type = issue.get("issue_type") or ""
    if issue_type == "missing_tier":
        message = issue.get("message") or ""
        for phrase, words in _MISSING_TIER.items():
            if phrase in message:
                return words
    return ISSUES.get(issue_type)


def _example_say(details: dict) -> str:
    """One value-level difference, as a person would read it."""
    examples = details.get("examples") or []
    first = examples[0] if isinstance(examples, list) and examples else None
    if not isinstance(first, dict):
        return "no example was recorded"
    where = f"animal {first.get('animal_id')}"
    if first.get("day"):
        where += f" on {first['day']}"
    what = first.get("endpoint") or "a measurement"
    return (f"{where}, {what}: the workbook says {first.get('xlsx')!r} and the "
            f"table {first.get('csv')!r}")


def issue_id(issue: dict, names: dict[str, str]) -> str:
    """A name for this finding that is the same every time it is found, and
    different once what it says changes."""
    parts = [str(issue.get("issue_type") or ""), str(issue.get("platform") or ""),
             "|".join(sorted(names.get(f, f) for f in (issue.get("files_involved") or []))),
             str(issue.get("message") or "")]
    return "iss_" + hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:10]


def say(issue: dict, names: dict[str, str]) -> dict:
    """One finding of the file check, in words, with its group and its files.

    ``names`` maps the file ids the check records to the names a person brought
    the files in under.
    """
    issue_type = issue.get("issue_type") or ""
    severity = issue.get("severity") or "warning"
    details = issue.get("details") if isinstance(issue.get("details"), dict) else {}
    files = [names.get(f, f) for f in (issue.get("files_involved") or [])]

    if issue_type in ELSEWHERE:
        group, known, words = "elsewhere", True, None
    else:
        words = _words_for(issue)
        known = words is not None
        group = (words.group if words and words.group else BY_SEVERITY.get(severity, "look"))

    if words is None:
        # Not a finding this module has words for: the check's own message
        # stands, said as it was written.
        said = issue.get("message") or "The file check reported something this page cannot word."
        what_to_do = None
    else:
        fields = _Fields(
            platform=_platform_say(issue.get("platform")),
            files=_files_say(issue, names),
            message=_bare_message(issue, names),
            example=_example_say(details),
            # A detail the check recorded as a list is said as a list of
            # things ("Triclosan and Bisphenol AF"), not as its repr.
            **{k: (_listed(v) if isinstance(v, list) else v)
               for k, v in details.items()
               if isinstance(v, (str, int, float, list))},
        )
        said = words.say.format_map(fields)
        what_to_do = words.what_to_do

    return {
        "id": issue_id(issue, names),
        "type": issue_type,
        "group": group,
        "severity": severity,
        "say": said,
        "what_to_do": what_to_do,
        "files": files,
        "feeds": words.feeds if words else None,
        "settle": words.settle if words else None,
        "known": known,
        "message": issue.get("message") or "",
        "details": details,
    }


def counts(said: list[dict]) -> dict[str, int]:
    """How many findings are in each group."""
    return {group: sum(1 for one in said if one["group"] == group) for group in GROUPS}
