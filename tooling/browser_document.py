"""
tooling/browser_document.py — fetch one public address with a real browser window.

Some public agency sites turn a plain program away (HTTP 403, or no answer)
and serve a browser: ATSDR's document host, OSHA, NIOSH, ECHA.  This script
is the browser.  It is run as its own process by ``narrative.source_fetch``,
with the image's Playwright environment and a virtual display:

    with-display /opt/playwright/venv/bin/python tooling/browser_document.py \
        <url> <out file> [page|file]

``page``: open the address and write the page's HTML.  ``file``: open the
site's front page, then download the address from inside the page (a PDF,
which a browser would otherwise show in its viewer) and write its bytes.
The last line printed is a JSON object: {"status", "content_type", "bytes"}.
It imports nothing of the project.
"""

from __future__ import annotations

import base64
import json
import sys
from urllib.parse import urlsplit

_IN_PAGE = """
async (url) => {
  const r = await fetch(url, {credentials: 'include'});
  const buf = new Uint8Array(await r.arrayBuffer());
  let s = '';
  for (let i = 0; i < buf.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  }
  return {status: r.status, type: r.headers.get('content-type') || '', b64: btoa(s)};
}
"""


def main(url: str, out: str, mode: str) -> dict:
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        Stealth().apply_stealth_sync(context)
        page = context.new_page()
        try:
            if mode == "file":
                parts = urlsplit(url)
                page.goto(f"{parts.scheme}://{parts.netloc}/", timeout=60000, wait_until="commit")
                page.wait_for_timeout(4000)
                got = page.evaluate(_IN_PAGE, url)
                body = base64.b64decode(got["b64"])
                status, content_type = got["status"], got["type"]
            else:
                response = page.goto(url, timeout=60000, wait_until="commit")
                # A bot check answers 403 first and lets the page through a
                # few seconds later: wait for the page to settle, then read it.
                try:
                    page.wait_for_load_state("networkidle", timeout=25000)
                except Exception:  # noqa: BLE001 — a page that never idles is read as it is
                    pass
                page.wait_for_timeout(1500)
                body = page.content().encode("utf-8")
                status = response.status if response else 0
                content_type = "text/html; charset=utf-8"
                if status in (403, 429, 503) and len(page.inner_text("body")) > 1500:
                    status = 200          # the check passed and the page is there
        finally:
            browser.close()
    with open(out, "wb") as handle:
        handle.write(body)
    return {"status": status, "content_type": content_type, "bytes": len(body)}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    try:
        result = main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "page")
    except Exception as exc:  # noqa: BLE001 — the caller reads the JSON line
        result = {"status": 0, "error": f"{type(exc).__name__}: {exc}"[:300]}
    print(json.dumps(result))
