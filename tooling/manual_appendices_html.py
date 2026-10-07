"""tooling/manual_appendices_html.py — render the headless manual's appendices
(docs/headless-report-generation.md, a markdown subset: headings, paragraphs,
two-level lists, tables, code fences) into the hand-built HTML manual.

Replaces everything from the first appendix <h2> up to <footer>, and the
appendix entries of the contents rail; the rest of the HTML is untouched.

    python tooling/manual_appendices_html.py docs/headless-report-generation.md \
        docs/headless-report-generation.html
"""
import html, re, sys

md_path, html_path = sys.argv[1], sys.argv[2]
md = open(md_path).read()
app = md[md.index("## Appendix A."):]
PIPE = "\x00"

def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    # YAML source labels: [`profile.yaml`] -> a chip.
    t = re.sub(r"\[<code>([a-z]+\.yaml)</code>\]", r'<span class="chip yaml">\1</span>', t)
    return t.replace(PIPE, "|")

out, toc, lines, i = [], [], app.splitlines(), 0
while i < len(lines):
    ln = lines[i]
    m = re.match(r"## Appendix ([A-Z])\. (.*)", ln)
    if m:
        letter, title = m.groups()
        anchor = f"appendix-{letter.lower()}"
        out.append("<!-- ============================================================ -->")
        out.append(f'<h2 id="{anchor}"><span class="num">{letter}</span>{inline(title)}</h2>')
        toc.append((letter, anchor, title))
    elif ln.startswith("### "):
        out.append("<h3>" + inline(ln[4:]) + "</h3>")
    elif ln.startswith("```"):
        lang = ln[3:].strip() or "text"
        body = []
        i += 1
        while i < len(lines) and not lines[i].startswith("```"):
            body.append(lines[i]); i += 1
        out.append(f'<div class="code"><div class="bar"><span>{lang}</span><button type="button">Copy</button></div>'
                   f'<pre>{html.escape(chr(10).join(body), quote=False)}</pre></div>')
    elif ln.startswith("|"):
        rows = []
        while i < len(lines) and lines[i].startswith("|"):
            row = lines[i].replace("\\|", PIPE).strip().strip("|")
            rows.append([c.strip() for c in row.split("|")]); i += 1
        head, body = rows[0], rows[2:]
        out.append('<div class="tablewrap"><table>')
        out.append("  <thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead>")
        out.append("  <tbody>")
        for r in body:
            out.append("    <tr>" + "".join(
                (f'<td class="wrap">{inline(c)}</td>' if k == 0 else f"<td>{inline(c)}</td>")
                for k, c in enumerate(r)) + "</tr>")
        out.append("  </tbody>\n</table></div>")
        continue
    elif ln.startswith("- "):
        items = []
        while i < len(lines) and (lines[i].startswith("- ") or lines[i].startswith("  ")):
            l = lines[i]
            if l.startswith("- "):
                items.append([l[2:], []])
            elif l.strip().startswith("- "):
                items[-1][1].append(l.strip()[2:])
            elif items[-1][1]:
                items[-1][1][-1] += " " + l.strip()
            else:
                items[-1][0] += " " + l.strip()
            i += 1
        out.append("<ul>")
        for text, subs in items:
            sub = ("<ul>" + "".join(f"<li>{inline(s)}</li>" for s in subs) + "</ul>") if subs else ""
            out.append(f"  <li>{inline(text)}{sub}</li>")
        out.append("</ul>")
        continue
    elif ln.strip() and ln.strip() != "---":
        para = [ln]
        while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r"(#|\||- |```)", lines[i + 1]):
            i += 1; para.append(lines[i])
        out.append("<p>" + inline(" ".join(p.strip() for p in para)) + "</p>")
    i += 1

h = open(html_path).read()
start = h.find('<!-- ============================================================ -->\n<h2 id="appendix-')
if start != -1:
    h = h[:start] + h[h.index("<footer>"):]
h = re.sub(r'\n    <li class="appendix"[^\n]*</li>', "", h)
h = h.replace("\n<footer>", "\n" + "\n".join(out) + "\n\n<footer>", 1)
items = "".join(f'\n    <li class="appendix"><a href="#{a}" data-letter="{l}">{html.escape(t)}</a></li>'
                for l, a, t in toc)
h = h.replace('    <li><a href="#gaps">Known gaps</a></li>', '    <li><a href="#gaps">Known gaps</a></li>' + items, 1)
open(html_path, "w").write(h)
