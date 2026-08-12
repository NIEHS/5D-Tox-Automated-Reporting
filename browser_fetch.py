"""Headed-browser recovery fetcher for the walled/missed papers.

Uses the baked headed Chromium (run me via `browse browser_fetch.py`) with
stealth, to fetch papers the requests-based crawl couldn't (Cloudflare/CDN
interstitials). Rides NIH-IP institutional access. Reuses the same GUID-keyed
.fulltext_cache/ as the main crawl, so the manifest picks results up on rebuild.

Reality (per CLAUDE.md): this clears browser-layer bot checks but NOT TLS/JA3 or
datacenter-IP reputation. Hard-Cloudflare publishers (OUP/Wiley/Cell/T&F) will
stay blocked; lenient ones (Elsevier-class) yield. We harvest what we can and
log the rest.

Success is judged by CONTENT, not HTTP/title: a Cloudflare "Just a moment..."
interstitial is ~28 KB, real articles are >60 KB — and a served PDF is detected
by the %PDF magic bytes on a direct download.
"""
from __future__ import annotations
import json, re, sys, time, urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# Helpers inlined from fulltext.py so this runs under the baked playwright venv
# (which lacks `requests`, imported at fulltext module load).
_REF_PATTERNS = [
    re.compile(r'\n\s*References\s*\n.*', re.DOTALL | re.IGNORECASE),
    re.compile(r'\n\s*Bibliography\s*\n.*', re.DOTALL | re.IGNORECASE),
    re.compile(r'\n\s*Literature Cited\s*\n.*', re.DOTALL | re.IGNORECASE),
]


def _clean_text(text, max_chars=500_000):
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    for pat in _REF_PATTERNS:
        text = pat.sub('', text)
    text = text.strip()
    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars]; truncated = True
    return text, truncated


def _extract_text_from_html(html):
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<(?:p|div|br|h[1-6]|li|tr)[^>]*>', '\n', html, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', html)
    for a, b in (('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
                 ('&nbsp;', ' '), ('&#39;', "'"), ('&quot;', '"')):
        text = text.replace(a, b)
    return text


def _extract_text_from_pdf(pdf_bytes):
    try:
        sys.path.insert(0, '/workspace/rlm-bmdx')
        from pdf_text import parse_pdf_bytes, chunks_to_text
        return chunks_to_text(parse_pdf_bytes(pdf_bytes, detect_tables=False))
    except Exception:
        return ''

CACHE = Path('/workspace/rlm-bmdx/.fulltext_cache')
CATALOG = '/workspace/rlm-bmdx/catalog.json'
MANIFEST = '/workspace/rlm-bmdx/manifest.json'
LOG = Path('/workspace/rlm-bmdx/browser_fetch_results.jsonl')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36')

CHALLENGE_MARKERS = ('just a moment', 'checking your browser', 'cf-challenge',
                     'enable javascript and cookies', 'client challenge',
                     'verifying you are human')
MIN_HTML = 60_000      # interstitials are ~28KB; real articles are bigger
MIN_TEXT = 800         # cleaned-text floor to count as a real body


def _safe(guid): return re.sub(r'[^\w\-]', '_', guid)


def already_cached(guid) -> bool:
    return (CACHE / f'{_safe(guid)}.txt').exists()


def save(guid, source, text, raw_bytes, raw_kind, resolved_url):
    stem = _safe(guid)
    text, truncated = _clean_text(text)
    (CACHE / f'{stem}.txt').write_text(text, encoding='utf-8')
    raw_file = ''
    if raw_bytes and raw_kind:
        ext = {'pdf': 'pdf', 'html': 'html'}.get(raw_kind, 'bin')
        (CACHE / f'{stem}.{ext}').write_bytes(raw_bytes)
        raw_file = f'{stem}.{ext}'
    (CACHE / f'{stem}.meta.json').write_text(json.dumps({
        'source': source, 'char_count': len(text), 'truncated': truncated,
        'raw_kind': raw_kind, 'raw_file': raw_file, 'resolved_url': resolved_url,
    }), encoding='utf-8')
    return len(text)


def try_url(page, url):
    """Return (ok, kind, text, raw_bytes, resolved_url, note)."""
    # Direct-PDF URLs: fetch bytes via the page's request context (rides cookies)
    resp = page.goto(url, timeout=45000, wait_until='domcontentloaded')
    # let a challenge attempt to resolve
    page.wait_for_timeout(8000)
    final = page.url
    status = resp.status if resp else 0
    ctype = ''
    try:
        ctype = (resp.headers.get('content-type', '') if resp else '').lower()
    except Exception:
        pass

    # PDF served directly
    if 'pdf' in ctype:
        try:
            body = resp.body()
            if body[:5] == b'%PDF-' or b'%PDF' in body[:1024]:
                txt = _extract_text_from_pdf(body)
                if len(txt.strip()) > 200:
                    return True, 'pdf', txt, body, final, 'pdf-direct'
        except Exception:
            pass

    html = page.content()
    title = page.title()
    low = (title + html[:3000]).lower()
    if any(m in low for m in CHALLENGE_MARKERS) and len(html) < MIN_HTML:
        return False, '', '', None, final, f'challenged({status})'

    text = _extract_text_from_html(html)
    if len(text.strip()) > MIN_TEXT:
        return True, 'html', text, html.encode('utf-8'), final, 'html-body'
    return False, '', '', None, final, f'thin({len(html)}b,{status})'


def main():
    catalog = json.load(open(CATALOG))
    hits = {h['guid'] for h in json.load(open(MANIFEST))}
    targets = [(g, v) for g, v in catalog.items()
               if g not in hits and not already_cached(g)
               and (v.get('open_access_pdf') or v.get('doi'))]

    # --host X: only papers whose OA-pdf host contains X (for targeted testing)
    if '--host' in sys.argv:
        hfilt = sys.argv[sys.argv.index('--host') + 1]
        targets = [(g, v) for g, v in targets
                   if hfilt in (v.get('open_access_pdf') or '')]
    if '--limit' in sys.argv:
        limit = int(sys.argv[sys.argv.index('--limit') + 1])
        targets = targets[:limit]

    print(f'browser harvest: {len(targets)} targets', flush=True)
    got = failed = 0
    logf = LOG.open('a')

    with sync_playwright() as p:
        b = p.chromium.launch(headless=False,
                              args=['--no-sandbox', '--disable-dev-shm-usage'])
        ctx = b.new_context(user_agent=UA)
        Stealth().apply_stealth_sync(ctx)
        page = ctx.new_page()

        for i, (guid, v) in enumerate(targets, 1):
            # candidate URLs: direct OA pdf first, then DOI landing
            urls = []
            if v.get('open_access_pdf'):
                urls.append(v['open_access_pdf'])
            if v.get('doi'):
                urls.append(f"https://doi.org/{v['doi']}")

            outcome = 'miss'
            for u in urls:
                try:
                    ok, kind, text, raw, final, note = try_url(page, u)
                except Exception as e:
                    note = f'{type(e).__name__}'
                    ok = False
                if ok:
                    n = save(guid, 'browser', text, raw, kind, final)
                    outcome = f'{kind}:{n}c'
                    got += 1
                    break
            else:
                failed += 1

            title = (v.get('title') or '')[:45]
            print(f'[{i}/{len(targets)}] {outcome:14} {title}', flush=True)
            logf.write(json.dumps({'guid': guid, 'outcome': outcome,
                                   'title': v.get('title')}) + '\n')
            logf.flush()

        b.close()
    logf.close()
    print(f'\nDONE: recovered {got}, failed {failed} of {len(targets)}', flush=True)


if __name__ == '__main__':
    main()
