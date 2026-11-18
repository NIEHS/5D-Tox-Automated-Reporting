"""Save the Written sections page's mock fixtures FROM A RUNNING BACKEND.

The fixtures are the backend's own answers ({status, body}), never
hand-written.  Run the backend on a scratch copy of the store that holds the
finished NIEHS-12 report and its live copy (never the real store), then:

    python fetch_fixtures.py http://127.0.0.1:9520

Three answers are shortened so the fixtures stay small; nothing else is
changed, and no key is added or removed:
  * a gene-level interpretation's recorded text (57,000 characters) is cut to
    its first 3,000, and its papers offered to the first eight;
  * a reference list keeps the Background's sources and the first five papers
    of each study.
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
    kept, seen = [], {}
    for entry in answer["body"]["entries"]:
        if entry["kind"] == "paper":
            seen[entry["study_id"]] = seen.get(entry["study_id"], 0) + 1
            if seen[entry["study_id"]] > 5:
                continue
        kept.append(entry)
    answer["body"]["entries"] = kept
    return answer


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


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9520")
