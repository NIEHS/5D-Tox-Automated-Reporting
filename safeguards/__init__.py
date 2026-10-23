"""
safeguards — idiot-proofing, as its own layer (ADR-0031).

The application's users are not programmers, and the workflow's mistakes are
expensive. The workflow core (workflow/, pipeline/) does the work and keeps its
invariants for every caller — derived state, atomic integration, a history of
every section write, path safety, the LLM egress guard. This package keeps a
person from going wrong:

  refusals   every refusal in plain words: what happened, what to do, where
             (``explain``, ``error_body``), and the safeguards' own refusals
  acts       whether an act is allowed now: R6 (no data act on a companion or
             a report), C1 (the phase's legal acts; Process only under a
             method a person chose)
  sections   C2: content a person owns is never overwritten by a machine; the
             reasons a person's act on a section needs
  guarded    the workflow's acts, guarded — what a front end calls

Front ends (the web routes, the command line) go through ``safeguards.guarded``.
The notebook drives the core directly: the same workflow, without the guarding.
The core never imports this package (tests/unit/test_safeguards_layering.py).
"""
