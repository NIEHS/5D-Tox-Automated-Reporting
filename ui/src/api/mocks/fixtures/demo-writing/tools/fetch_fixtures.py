"""Save the Written sections page's mock fixtures FROM A RUNNING BACKEND.

The fixtures are the backend's own answers ({status, body}), never
hand-written.  Run the backend on a scratch copy of the store that holds the
finished NIEHS-12 report and its live copy (never the real store), then:

    python fetch_fixtures.py http://127.0.0.1:9520

Three answers are shortened so the fixtures stay small; nothing else is
changed, and no key is added or removed:
  * a gene-level interpretation's recorded text (57,000 characters) is cut to
    its first 3,000, and its papers offered to the first eight;
  * of the recorded sources a report does not list, the first five are kept,
    and of a paper's extracted statements the first three. The reference list
    itself (the last citation check's) is kept whole.

``--references`` saves only the Citations tab's answers (the references of
the four sessions and the refusal of a check on a study of a report).
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent
FINISHED, LIVE = "DTXSID6020430", "DTXSID6020430_live"
SESSIONS = (FINISHED, f"{FINISHED}_rat", LIVE, f"{LIVE}_rat")
STUDY_PARTS = ("methods", "results", "bmd_summary", "genomics_liver_female", "summary")
CUT = 3000


def fetch(base: str, path: str, method: str = "GET") -> dict:
    request = urllib.request.Request(base.rstrip("/") + path, method=method)
    try:
        with urllib.request.urlopen(request) as response:
            return {"status": response.status, "body": json.load(response)}
    except urllib.error.HTTPError as error:
        return {"status": error.code, "body": json.load(error)}


def save(name: str, answer: dict) -> None:
    (OUT / name).write_text(json.dumps(answer, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(answer["status"], name)


def shorten_part(answer: dict) -> dict:
    body = answer["body"]
    for given in body.get("given", []):
        if given.get("text") and len(given["text"]) > 3 * CUT:
            given["text"] = given["text"][:CUT]
    if "papers_offered" in body:
        body["papers_offered"] = body["papers_offered"][:8]
    return answer


def shorten_references(answer: dict) -> dict:
    """The list as printed is kept whole; of the recorded sources not listed,
    the first five; a paper's extracted statements, the first three."""
    body = answer["body"]
    body["not_listed"] = body.get("not_listed", [])[:5]
    for entry in body.get("entries", []) + body["not_listed"]:
        if entry.get("statements"):
            entry["statements"] = entry["statements"][:3]
    return answer


def references_only(base: str) -> None:
    for session in SESSIONS:
        save(f"references.{session}.json",
             shorten_references(fetch(base, f"/api/v2/studies/{session}/references")))
    save("refusal.citations_are_the_reports.json",
         fetch(base, f"/api/v2/studies/{LIVE}_rat/citations/check", "POST"))


def main(base: str) -> None:
    for session in SESSIONS:
        save(f"state.{session}.json", fetch(base, f"/api/v2/studies/{session}/state"))
        save(f"writing.{session}.json", fetch(base, f"/api/v2/studies/{session}/writing"))
        save(f"references.{session}.json",
             shorten_references(fetch(base, f"/api/v2/studies/{session}/references")))
    for report in (FINISHED, LIVE):
        save(f"part.{report}.background.json", fetch(base, f"/api/v2/studies/{report}/writing/background"))
    for part in STUDY_PARTS:
        save(f"part.{FINISHED}_rat.{part}.json",
             shorten_part(fetch(base, f"/api/v2/studies/{FINISHED}_rat/writing/{part}")))
    save(f"part.{LIVE}_rat.summary.json", fetch(base, f"/api/v2/studies/{LIVE}_rat/writing/summary"))
    # Refusals, as the backend answers them (each is refused before any work).
    save("refusal.demo_reference.json",
         fetch(base, f"/api/v2/studies/{FINISHED}/writing/background", "POST"))
    save("refusal.background_is_the_reports.json",
         fetch(base, f"/api/v2/studies/{LIVE}_rat/writing/background", "POST"))
    save("refusal.writing_part_not_found.json",
         fetch(base, f"/api/v2/studies/{FINISHED}/writing/methods"))
    save("refusal.citations_are_the_reports.json",
         fetch(base, f"/api/v2/studies/{LIVE}_rat/citations/check", "POST"))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    base = args[0] if args else "http://127.0.0.1:9520"
    references_only(base) if "--references" in sys.argv else main(base)
