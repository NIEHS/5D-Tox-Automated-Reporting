"""
safeguards.acts — whether a person may do an act on a study now.

The workflow derives what is legal (workflow.phases: the phase of a study and
its table of acts; workflow.engine: the state). This module enforces it, before
a step reads or writes anything, and refuses in a person's terms:

  * R6: no data act on a session whose data is not its own — a published
    book's companion (``read_only_session``) or a report over several studies
    (``report_has_no_data``);
  * C1: an act outside the legal acts of the study's phase
    (``phase_not_allowed``: adding files before anything, integrating before
    the file check passed, approving or processing before integrating …);
  * C1: Process before a person has chosen the study's analysis method
    (``method_not_chosen``: never chosen for them);
  * deleting a session a person may not delete: a published book's companion
    (``read_only_session``) or one of the studies a report composes
    (``member_of_report``). A report session itself may go; its studies stay.

The workflow core (workflow.steps, pipeline.process_integrated) does not call
this: the notebook drives the core directly, unguarded. Front ends go through
safeguards.guarded, which calls ``require`` first.
"""

from __future__ import annotations

from safeguards.refusals import MethodNotChosen, PhaseRefusal, StudyRefusal
from workflow.phases import NEXT_STEP, Action


def require_data_session(dtxsid: str, store=None) -> None:
    """R6: refuse a data act (bringing in files, validating, integrating, the
    data approval, Process) on a session whose data is not its own. Reads
    through ``store`` when given, else the session folder, which it never
    creates. A session that does not exist yet passes."""
    import common.paths
    from common.session_files import read_json_file
    from rendering.published_clone import CLONE_FILE
    from rendering.report_compose import STUDIES_FILE

    if store is not None:
        clone = store.read_json(dtxsid, CLONE_FILE)
        listed = store.read_json(dtxsid, STUDIES_FILE)
    else:
        # Read at call time, so a redirected SESSIONS_DIR (tests, workspaces) is honoured.
        session = common.paths.SESSIONS_DIR / dtxsid
        clone = (session / CLONE_FILE).is_file() or None
        listed = read_json_file(session / STUDIES_FILE) if (session / STUDIES_FILE).is_file() else None
    if clone is not None:
        raise StudyRefusal("read_only_session",
                           f"{dtxsid} is a published book's companion ({CLONE_FILE}); "
                           "no data act is done on it", 409, {"id": dtxsid})
    if listed is not None:
        ids = [str(v) for v in listed.values()] if isinstance(listed, dict) else []
        raise StudyRefusal("report_has_no_data",
                           f"{dtxsid} is a report over several studies ({STUDIES_FILE}: "
                           f"{', '.join(ids)}); its data is prepared in those studies", 409,
                           {"id": dtxsid, "members": ids})


def require_deletable(dtxsid: str) -> None:
    """Refuse removing a session's folder when it is a published book's
    companion (``read_only_session``: a tool rebuilds it from the book) or one
    of the studies a report over several studies composes
    (``member_of_report``: deleting it would break that report). A report
    session may be deleted (its member studies stay), and so may any other
    session. Reads two small files and the reports' ``studies.json``; writes
    nothing. Every route or step that removes a session's folder calls this."""
    import common.paths
    from common.session_files import read_json_file
    from document_model.document_definition import report_of_member
    from rendering.published_clone import CLONE_FILE
    from rendering.report_compose import STUDIES_FILE

    session = common.paths.SESSIONS_DIR / dtxsid
    if (session / CLONE_FILE).is_file():
        raise StudyRefusal("read_only_session",
                           f"{dtxsid} is a published book's companion ({CLONE_FILE}); "
                           "it is not deleted here", 409, {"id": dtxsid})
    parent = report_of_member(dtxsid)
    if parent and parent != dtxsid:
        listed = read_json_file(common.paths.SESSIONS_DIR / parent / STUDIES_FILE) or {}
        key = next((str(k) for k, v in listed.items() if v == dtxsid), "")
        raise StudyRefusal("member_of_report",
                           f"{dtxsid} is the {key or 'member'} study of the report {parent} "
                           f"({STUDIES_FILE}); deleting it would break that report", 409,
                           {"parent": parent, "key": key, "species": key or "member"})


def require_legal(dtxsid: str, act, store=None):
    """C1: the study's derived state, when ``act`` is legal in its phase; else
    PhaseRefusal (409 ``phase_not_allowed``), which names the phase and the act
    that moves it forward."""
    from workflow.engine import WorkflowEngine

    act = Action(act)
    st = WorkflowEngine(dtxsid, store).state()
    if act not in st.legal_actions:
        nxt = NEXT_STEP.get(st.phase)
        raise PhaseRefusal(
            dtxsid, act.value, st.phase.value, [a.value for a in st.legal_actions],
            integration=st.artifacts.get("integration"),
            next_action=nxt.value if nxt else None)
    return st


def require_method_chosen(dtxsid: str) -> dict:
    """C1 D1: the study's method pin when a person chose it; else
    MethodNotChosen (409 ``method_not_chosen``): Process never runs under a
    method nobody chose. Writes nothing."""
    from pipeline.method_profile import chosen_by_person, read_pin

    pin = read_pin(dtxsid)
    if not chosen_by_person(pin):
        raise MethodNotChosen(dtxsid, pin)
    return pin


# The acts on a study's data: every one is refused on a session whose data is
# not its own (R6).
_DATA_ACTS = frozenset(Action)


def require(dtxsid: str, act, store=None, *, method: bool = False):
    """Every check an act on a study's data must pass, in order: R6, the
    phase (C1), and with ``method`` (running Process: the statistics, the BMDs,
    the text) the person's method choice (C1 D1). Returns the derived state."""
    act = Action(act)
    if act in _DATA_ACTS:
        require_data_session(dtxsid, store)
    st = require_legal(dtxsid, act, store)
    if method:
        require_method_chosen(dtxsid)
    return st
