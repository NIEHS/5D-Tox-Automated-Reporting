"""
ui_api — the new interface's server side (MODULES.md §4): what its screens
read and the study acts of its Studies module.

  read_model    one study's derived state in one read (GET /api/v2/…/state)
  studies       the studies on disk, what each one is, where it stands (M1)
  study_steps   creating a study, recording its identity, deleting it (M1)
  vocabularies  the controlled vocabularies and id formats a field is bound to
  refusals      the interface's own refusal codes, and the explanation in its
                terms (``fix`` is the module that clears it)

A front end, like web_routes: it reads the core and acts through the
safeguards (safeguards.guarded, ADR-0031). The core never imports it.
"""
