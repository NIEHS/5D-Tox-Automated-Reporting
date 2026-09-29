"""
Export Claude Code session JSONL transcripts to readable Markdown.

Usage:
    python export_sessions.py                          # export all sessions
    python export_sessions.py <session_id>.jsonl       # export one session
    python export_sessions.py --output-dir /path/to/   # custom output dir
"""

import json
import sys
from pathlib import Path


SESSION_DIR = Path.home() / ".claude/projects/-home-svobodadl-AI-ai"

# Max chars for inline tool result display; longer results get collapsed
RESULT_INLINE_MAX = 500
RESULT_COLLAPSED_MAX = 3000


def classify_user_content(content) -> tuple[str, str]:
    """
    Classify user message content into human text and tool results.
    Returns (human_text, tool_results_text).
    """
    if isinstance(content, str):
        return content, ""

    if not isinstance(content, list):
        return str(content), ""

    human_parts = []
    result_parts = []

    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            human_parts.append(item.get("text", ""))
        elif item.get("type") == "tool_result":
            rc = item.get("content", "")
            is_error = item.get("is_error", False)
            prefix = "**Error:**\n" if is_error else ""
            if isinstance(rc, str) and rc.strip():
                result_parts.append(prefix + rc)
            elif isinstance(rc, list):
                for sub in rc:
                    if isinstance(sub, dict) and sub.get("type") == "text":
                        result_parts.append(prefix + sub.get("text", ""))

    return "\n\n".join(human_parts), "\n\n".join(result_parts)


def format_tool_result(text: str) -> str:
    """Format a tool result for markdown, collapsing long ones."""
    if not text.strip():
        return ""
    if len(text) <= RESULT_INLINE_MAX:
        return f"```\n{text}\n```"
    truncated = text[:RESULT_COLLAPSED_MAX]
    if len(text) > RESULT_COLLAPSED_MAX:
        truncated += "\n... (truncated)"
    return f"<details><summary>Tool output ({len(text)} chars)</summary>\n\n```\n{truncated}\n```\n</details>"


def format_tool_use(item: dict) -> str:
    """Format a tool_use block as a readable summary."""
    name = item.get("name", "?")
    inp = item.get("input", {})

    if name == "Read":
        fp = inp.get("file_path", "?")
        extra = ""
        if inp.get("offset"):
            extra = f" lines {inp['offset']}-{inp['offset'] + inp.get('limit', 0)}"
        return f"> **Read** `{fp}`{extra}"
    elif name == "Write":
        fp = inp.get("file_path", "?")
        size = len(inp.get("content", ""))
        return f"> **Write** `{fp}` ({size} chars)"
    elif name == "Edit":
        fp = inp.get("file_path", "?")
        old = (inp.get("old_string", "") or "")[:60]
        return f"> **Edit** `{fp}` — replacing `{old}...`"
    elif name == "Bash":
        cmd = inp.get("command", "?")
        desc = inp.get("description", "")
        label = f" — {desc}" if desc else ""
        return f"> **Bash**{label}\n> ```\n> {cmd}\n> ```"
    elif name == "Glob":
        return f"> **Glob** `{inp.get('pattern', '?')}`"
    elif name == "Grep":
        pat = inp.get("pattern", "?")
        path = inp.get("path", "")
        return f"> **Grep** `{pat}`" + (f" in `{path}`" if path else "")
    elif name == "Task":
        desc = inp.get("description", "")
        return f"> **Task** — {desc}"
    elif name == "Skill":
        return f"> **Skill** `{inp.get('skill', '?')}`"
    else:
        summary = json.dumps(inp)[:120]
        return f"> **{name}** {summary}"


def format_assistant_content(content) -> str:
    """Extract readable text from assistant message content."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = item.get("text", "")
            if text.strip():
                parts.append(text)
        elif item.get("type") == "tool_use":
            parts.append(format_tool_use(item))

    return "\n\n".join(parts)


def session_to_markdown(jsonl_path: Path) -> str:
    """Convert a single session JSONL to markdown."""
    events = []
    with open(jsonl_path) as f:
        for line in f:
            if not line.strip():
                continue
            events.append(json.loads(line))

    lines = []
    session_id = jsonl_path.stem

    # Find first timestamp
    first_ts = ""
    for ev in events:
        ts = ev.get("timestamp", "")
        if ts:
            first_ts = ts
            break

    lines.append(f"# Session: {session_id}")
    if first_ts:
        lines.append(f"\n*Started: {first_ts}*\n")
    lines.append("---\n")

    msg_count = 0
    for ev in events:
        ev_type = ev.get("type")

        if ev_type == "user":
            msg = ev.get("message", {})
            content = msg.get("content", "")
            human_text, tool_results = classify_user_content(content)
            ts = ev.get("timestamp", "")

            if human_text.strip():
                # Real human message (may also include tool results)
                msg_count += 1
                lines.append(f"## User ({ts})\n")
                lines.append(human_text)
                if tool_results.strip():
                    lines.append("\n" + format_tool_result(tool_results))
                lines.append("")
            elif tool_results.strip():
                # Tool-result-only message — show compactly to maintain flow
                lines.append(f"*[Tool results returned at {ts}]*\n")
                lines.append(format_tool_result(tool_results))
                lines.append("")

        elif ev_type == "assistant":
            msg = ev.get("message", {})
            content = msg.get("content", [])
            text = format_assistant_content(content)
            if not text.strip():
                continue
            msg_count += 1
            model = msg.get("model", "")
            lines.append(f"## Assistant ({model})\n")
            lines.append(text)
            lines.append("")

        elif ev_type == "system":
            msg = ev.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                lines.append(f"*[System: {content[:200]}]*\n")
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        lines.append(f"*[System: {item['text'][:200]}]*\n")

    lines.append(f"\n---\n*{msg_count} messages total*\n")
    return "\n".join(lines)


def main():
    output_dir = Path("/home/svobodadl/AI/bmdx/output/session_exports")
    specific_file = None

    for arg in sys.argv[1:]:
        if arg.startswith("--output-dir"):
            continue
        elif arg.endswith(".jsonl"):
            specific_file = arg
        elif sys.argv[sys.argv.index(arg) - 1] == "--output-dir":
            output_dir = Path(arg)

    output_dir.mkdir(parents=True, exist_ok=True)

    if specific_file:
        files = [SESSION_DIR / specific_file if not Path(specific_file).is_absolute()
                 else Path(specific_file)]
    else:
        files = sorted(SESSION_DIR.glob("*.jsonl"))

    for jsonl_path in files:
        if not jsonl_path.exists():
            print(f"Not found: {jsonl_path}")
            continue
        print(f"Exporting: {jsonl_path.name}...")
        md = session_to_markdown(jsonl_path)
        out_path = output_dir / f"{jsonl_path.stem}.md"
        out_path.write_text(md)
        print(f"  -> {out_path} ({len(md)} chars)")


if __name__ == "__main__":
    main()
