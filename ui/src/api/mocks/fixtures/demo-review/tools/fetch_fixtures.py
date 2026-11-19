"""Save the review page's mock fixtures FROM A RUNNING BACKEND.

The fixtures are the backend's own answers ({status, body}), never
hand-written.  Run the backend on a scratch copy of the store that holds the
finished NIEHS-12 report and its live copy, both processed (never the real
store: the acts below change a section of the live mouse study), then:

    python fetch_fixtures.py http://127.0.0.1:9530

Saved:
  * review.<id>.json: GET …/review of the finished report, the live report and
    the live rat study, read before any act;
  * the section acts, played on one results section of the live mouse study:
    approving it, approving it again (a success that did nothing), reopening
    it without a reason (refused), reopening it with one, and its history
    after that; and an approval on the finished side (refused);
  * what the Bookshelf answers for a report it does not have: its page and
    its Word document.
Nothing is shortened.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent
FINISHED, LIVE = "DTXSID6020430", "DTXSID6020430_live"
ACTED_ON, KEY = f"{LIVE}_mouse", "bm2_organ-weight"
NO_REPORT = "DTXSID0000000"


def fetch(base: str, path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    request = urllib.request.Request(base.rstrip("/") + path, method=method, data=data,
                                     headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            status, text = response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        status, text = error.code, error.read().decode("utf-8")
    try:
        return {"status": status, "body": json.loads(text)}
    except ValueError:
        return {"status": status, "body": text}       # a page


def save(name: str, answer: dict) -> None:
    (OUT / name).write_text(json.dumps(answer, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(answer["status"], name)


def main(base: str) -> None:
    for session in (FINISHED, LIVE, f"{LIVE}_rat"):
        save(f"review.{session}.json", fetch(base, f"/api/v2/studies/{session}/review"))
    section = f"/api/v2/studies/{ACTED_ON}/sections/{KEY}"
    save("accept.json", fetch(base, f"{section}/accept", "POST"))
    save("accept.again.json", fetch(base, f"{section}/accept", "POST"))
    save("refusal.release_without_reason.json", fetch(base, f"{section}/release", "POST", {"reason": ""}))
    save("release.json", fetch(base, f"{section}/release", "POST",
                               {"reason": "The footnote on the liver weights is to be checked."}))
    save("history.json", fetch(base, f"{section}/history"))
    save("refusal.demo_reference.json",
         fetch(base, f"/api/v2/studies/{FINISHED}_rat/sections/bm2_body-weight/accept", "POST"))
    save("book.no_report.json", fetch(base, f"/Bookshelf/{NO_REPORT}"))
    save("docx.no_report.json", fetch(base, f"/Bookshelf/{NO_REPORT}/report.docx"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9530")
