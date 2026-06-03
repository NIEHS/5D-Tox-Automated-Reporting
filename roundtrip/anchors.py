"""
roundtrip.anchors — the sentinel convention for anchored regions (ADR-0005).

A "generated document a human edits in a git-backed editor" is round-tripped by
wrapping each editable region in a pair of begin/end **comment** sentinels keyed
to a stable id.  The generator (writer) and the reconciler (reader) MUST agree
on this format exactly, so it lives here — owned by the library, imported by
both sides — rather than being duplicated.

Format (today, LaTeX comments):

    %% rlm:begin <kind> <id>
    … region body …
    %% rlm:end <kind> <id>

`kind` is "node" or "item" (a sub-addressable content item); `id` is the stable
region key.  Because they're comments they produce no typeset output, so adding
them leaves the compiled document byte-identical.

The comment prefix is the only LaTeX-specific bit; a future consumer using a
different markup (HTML/Markdown) would parameterize PREFIX + the line patterns
here without touching the reconciler.
"""

from __future__ import annotations

import re

# The comment prefix that makes a sentinel inert in the target markup.
PREFIX = "%% rlm:"

# Recognise begin/end sentinel lines: group(1) = kind, group(2) = id.
BEGIN_RE = re.compile(r"^%% rlm:begin (node|item) (.+)$")
END_RE = re.compile(r"^%% rlm:end (node|item) (.+)$")


def begin_line(kind: str, anchor_id: str) -> str:
    """The opening sentinel line for a region."""
    return f"{PREFIX}begin {kind} {anchor_id}"


def end_line(kind: str, anchor_id: str) -> str:
    """The closing sentinel line for a region."""
    return f"{PREFIX}end {kind} {anchor_id}"


def wrap(kind: str, anchor_id: str, body: str) -> str:
    """
    Bracket a rendered chunk in begin/end sentinels keyed to `anchor_id`.

    `kind` is the grain ("node" / "item"); `anchor_id` is the stable key
    (e.g. a node id, or "<node-id>::<item-id>").  The result is inert in the
    compiled document (the sentinels are comments).
    """
    return f"{begin_line(kind, anchor_id)}\n{body}\n{end_line(kind, anchor_id)}"
