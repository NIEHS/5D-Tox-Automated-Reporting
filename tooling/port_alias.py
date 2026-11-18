#!/usr/bin/env python3
"""tooling/port_alias.py — give one page of the app its own port.

The app is one process: the API, the new interface (/app) and the Bookshelf
(/Bookshelf) are routes of the same server.  To open one of them at its own
address (http://localhost:9300 for the Bookshelf), this relays a second port
to the app's port, byte for byte, and sends a request for "/" to the page.

    python tooling/port_alias.py --listen 9300 --to 9000 --landing /Bookshelf

One process serves the data, so two addresses can never disagree or write at
once; a second copy of the app on another port could.  The relay is plain TCP
(streamed responses and uploads pass untouched).  Only the first request of a
connection is read, to redirect "/"; it is sent on with "Connection: close",
so every request arrives on its own connection and "/" is always seen.
"""

from __future__ import annotations

import argparse
import asyncio


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


def _wants_root(head: bytes) -> bool:
    line = head.split(b"\r\n", 1)[0].split(b" ")
    return len(line) >= 2 and line[0] in (b"GET", b"HEAD") and line[1] == b"/"


def _one_request_per_connection(head: bytes) -> bytes:
    """``head`` with "Connection: close" in its header block, so the app closes
    after this response and the browser opens a connection for its next
    request.  Unchanged when the block is not complete in ``head`` or the
    request asks to upgrade the connection (a WebSocket)."""
    block, sep, rest = head.partition(b"\r\n\r\n")
    if not sep:
        return head
    lines = block.split(b"\r\n")
    if any(ln.lower().startswith(b"upgrade:") for ln in lines[1:]):
        return head
    kept = [ln for ln in lines if not ln.lower().startswith(b"connection:")]
    return b"\r\n".join(kept + [b"Connection: close"]) + sep + rest


async def _serve(client_r, client_w, *, upstream: tuple[str, int], landing: str) -> None:
    try:
        head = await client_r.read(65536)
        if not head:
            return
        if _wants_root(head):
            client_w.write(f"HTTP/1.1 302 Found\r\nLocation: {landing}\r\nContent-Length: 0\r\n"
                           "Connection: close\r\n\r\n".encode())
            await client_w.drain()
            return
        try:
            up_r, up_w = await asyncio.open_connection(*upstream)
        except OSError:
            body = b"The app is not running on its port.\n"
            client_w.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain\r\n"
                           + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
            await client_w.drain()
            return
        up_w.write(_one_request_per_connection(head))
        await up_w.drain()
        await asyncio.gather(_pipe(client_r, up_w), _pipe(up_r, client_w))
    except ConnectionError:
        pass
    finally:
        try:
            client_w.close()
        except Exception:
            pass


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--listen", type=int, required=True, help="the port to open")
    ap.add_argument("--to", type=int, required=True, help="the app's port")
    ap.add_argument("--landing", required=True, help='the page "/" goes to, e.g. /Bookshelf')
    ap.add_argument("--host", default="0.0.0.0")
    a = ap.parse_args()
    server = await asyncio.start_server(
        lambda r, w: _serve(r, w, upstream=("127.0.0.1", a.to), landing=a.landing),
        a.host, a.listen)
    print(f"port {a.listen} -> 127.0.0.1:{a.to}, / -> {a.landing}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
