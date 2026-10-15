"""Save the documents an agent of the new-UI team returned (docs/ui-redesign/TEAM.md).

The harness doesn't let subagents write report files, so they return each document
as a ````markdown fence in their final message. This finds the last such message in
an agent's transcript (JSONL) and writes each fence to <outdir>: a fence whose first
line is "# <file>.md" is saved under that name, the others under the names given.

    python -m tooling.ui_team_save_report TRANSCRIPT OUTDIR [NAME ...]
"""
import json
import re
import sys
from pathlib import Path


def main(src: str, outdir: str, names: list[str]) -> None:
    last = None
    for line in open(src):
        try:
            msg = json.loads(line).get("message") or {}
        except Exception:
            continue
        if msg.get("role") != "assistant" or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if isinstance(block, dict) and block.get("type") == "text" and "````markdown" in block.get("text", ""):
                last = block["text"]
    if last is None:
        sys.exit("no fenced document in the transcript")
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    for i, body in enumerate(re.findall(r"````markdown\n(.*?)\n````", last, re.S)):
        lines = body.splitlines()
        m = re.match(r"#\s+([\w.-]+\.md)\b", lines[0].strip())
        if m:
            name, body = m.group(1), "\n".join(lines[1:]).lstrip("\n")
        else:
            name = names[i]
        (out / name).write_text(body.rstrip("\n") + "\n")
        print(name, len(body.splitlines()), "lines")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
