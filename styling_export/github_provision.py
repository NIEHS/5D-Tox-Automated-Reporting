"""
github_provision.py — originate (or adopt) a report's GitHub repo (ADR-0005 Am.1a).

App-side, GitHub-specific provisioning (parallels overleaf_provision.py).  A
report's repo identity is *automatic*: the name is derived from the test-article
id by convention, so the same DTXSID always maps to the same repo.  "Adopt" (use
an existing convention-named repo) and "create" (make a fresh one) are the same
entry point — `ensure_repo` — so the first provision originates it and later
ones reuse it.

Uses the `gh` CLI (the server inherits the host's gh auth).  In a real
deployment this would use a configured token with repo-create scope; the
`gh`-shell form is the dev path.
"""

from __future__ import annotations

import os
import subprocess

# Owner the app originates report repos under.  Per-deployment config; defaults
# to the dev account.  (Overridable via env so prod can point at an org.)
DEFAULT_OWNER = os.environ.get("RLM_GITHUB_OWNER", "daniel-sciome")

# Report-series suffix in the repo name.  One series for now; a parameter so a
# different study type can vary it without touching the convention.
DEFAULT_REPORT_TYPE = "5D-Tox"


def repo_slug(dtxsid: str, report_type: str = DEFAULT_REPORT_TYPE) -> str:
    """
    Convention repo name: "<DTXSID>-<report-type>" (e.g. DTXSID50469320-5D-Tox).

    Chosen to also be a valid GitHub name (no spaces) AND the string Overleaf
    will use as the project title on import, so repo and Overleaf project read
    the same.
    """
    return f"{dtxsid}-{report_type}"


def html_url(owner: str, slug: str) -> str:
    """The repo URL we push/pull and store as the binding's git_remote."""
    return f"https://github.com/{owner}/{slug}"


def _gh(args: "list[str]") -> "tuple[int, str, str]":
    """Run a gh command; return (returncode, stdout, stderr)."""
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def repo_exists(owner: str, slug: str) -> bool:
    """True if owner/slug is visible to the authenticated gh account."""
    code, _, _ = _gh(["repo", "view", f"{owner}/{slug}", "--json", "name"])
    return code == 0


def ensure_repo(
    dtxsid: str,
    *,
    owner: str = DEFAULT_OWNER,
    report_type: str = DEFAULT_REPORT_TYPE,
    private: bool = True,
    description: str = "",
) -> "tuple[bool, str]":
    """
    Adopt the convention-named repo if it already exists, else create it.

    Returns (created, html_url): created=False means it was adopted (already
    there), True means a fresh repo was made.  Raises on a create failure.
    """
    slug = repo_slug(dtxsid, report_type)
    if repo_exists(owner, slug):
        return False, html_url(owner, slug)
    args = ["repo", "create", f"{owner}/{slug}", "--private" if private else "--public"]
    if description:
        args += ["--description", description]
    code, _out, err = _gh(args)
    if code != 0:
        raise RuntimeError(f"gh repo create {owner}/{slug} failed: {err}")
    return True, html_url(owner, slug)
