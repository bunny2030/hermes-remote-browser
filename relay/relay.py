"""Hermes Remote Browser relay: lets a Hermes agent drive a Chrome on another machine through the
Hermes Remote Browser extension.

Two listeners:
- 127.0.0.1:9178 by default, published on a public HTTPS hostname by a reverse proxy or tunnel
  (for example Cloudflare Tunnel): only the extension's websocket at /ext. The extension dials
  out, so the browser's machine needs no open port.
- control.sock (unix socket, owner-only): the remote-browser Hermes plugin and the remote-browser
  CLI send commands, list pairing requests and approve or revoke devices here. Never public.

Pairing: the extension asks to pair and shows a short code; the code is approved on the server
(remote-browser approve CODE, or the agent's approve_pairing action). The extension then gets a
long random device token, of which the server keeps only the SHA-256. Nothing secret is ever
typed or copied by hand.

Environment: REMOTE_BROWSER_HOME (state directory), REMOTE_BROWSER_HOST / REMOTE_BROWSER_PORT
(websocket listener).
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path

from aiohttp import WSMsgType, web

HOME = Path(os.environ.get("REMOTE_BROWSER_HOME", Path.home() / ".local/share/hermes-remote-browser"))
DEVICES = HOME / "devices.json"
SOCK = HOME / "control.sock"
PUBLIC_HOST = os.environ.get("REMOTE_BROWSER_HOST", "127.0.0.1")
PUBLIC_PORT = int(os.environ.get("REMOTE_BROWSER_PORT", "9178"))

HELLO_TIMEOUT_S = 10
PAIR_TTL_S = 300
MAX_PENDING = 3
PAIR_RATE = (10, 600)            # at most 10 pairing requests per 10 minutes
CMD_TIMEOUT_S = 45
MAX_MSG = 12 * 1024 * 1024       # screenshots come back as data URLs
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I/L

log = logging.getLogger("hermes-remote-browser")


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _load_devices() -> list[dict]:
    try:
        return json.loads(DEVICES.read_text())
    except FileNotFoundError:
        return []


def _save_devices(devices: list[dict]) -> None:
    tmp = DEVICES.with_suffix(".tmp")
    tmp.write_text(json.dumps(devices, indent=2))
    tmp.chmod(0o600)
    tmp.replace(DEVICES)


class Bridge:
    def __init__(self) -> None:
        self.ext: web.WebSocketResponse | None = None
        self.ext_device: dict | None = None
        self.ext_since = 0.0
        self.pending: dict[str, dict] = {}      # code -> {ws, name, created, future}
        self.pair_times: list[float] = []
        self.waiters: dict[int, asyncio.Future] = {}
        self.next_id = 1

    # ---- extension side -------------------------------------------------------------------

    async def ext_handler(self, request: web.Request) -> web.StreamResponse:
        ws = web.WebSocketResponse(heartbeat=25, max_msg_size=MAX_MSG)
        await ws.prepare(request)
        try:
            msg = await asyncio.wait_for(ws.receive(), HELLO_TIMEOUT_S)
            hello = json.loads(msg.data) if msg.type == WSMsgType.TEXT else {}
        except (asyncio.TimeoutError, ValueError):
            await ws.close(code=4001, message=b"hello expected")
            return ws
        if hello.get("type") != "hello":
            await ws.close(code=4001, message=b"hello expected")
            return ws

        device = None
        if hello.get("device_token"):
            device = self._device_for(str(hello["device_token"]))
            if device is None:
                await ws.send_json({"type": "unpaired"})
                await ws.close(code=4003, message=b"unknown device")
                return ws
        elif hello.get("pair"):
            device = await self._pair(ws, str(hello.get("name") or "Chrome")[:60])
            if device is None:
                if not ws.closed:
                    await ws.close(code=4004, message=b"pairing not approved")
                return ws
        else:
            await ws.close(code=4001, message=b"hello expected")
            return ws

        if self.ext is not None and not self.ext.closed:
            await self.ext.close(code=4000, message=b"replaced by a newer connection")
        self.ext, self.ext_device, self.ext_since = ws, device, time.time()
        log.info("extension connected: %s (%s)", device["name"], device["id"])
        await ws.send_json({"type": "ready", "device_id": device["id"]})
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if data.get("type") == "result":
                    fut = self.waiters.pop(int(data.get("id", -1)), None)
                    if fut and not fut.done():
                        fut.set_result(data)
                # "ping" keepalives need no answer; they keep Chrome's service worker awake.
        finally:
            if self.ext is ws:
                self.ext = self.ext_device = None
                for fut in self.waiters.values():
                    if not fut.done():
                        fut.set_result({"ok": False, "error": "The extension disconnected."})
                self.waiters.clear()
                log.info("extension disconnected: %s", device["name"])
        return ws

    def _device_for(self, token: str) -> dict | None:
        digest = _sha(token)
        for d in _load_devices():
            if hmac.compare_digest(d["sha256"], digest):
                return d
        return None

    async def _pair(self, ws: web.WebSocketResponse, name: str) -> dict | None:
        now = time.time()
        self._expire_pending()
        self.pair_times = [t for t in self.pair_times if now - t < PAIR_RATE[1]]
        if len(self.pending) >= MAX_PENDING or len(self.pair_times) >= PAIR_RATE[0]:
            await ws.send_json({"type": "error", "error": "Too many pairing requests. Try again later."})
            return None
        self.pair_times.append(now)
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        code = f"{code[:3]}-{code[3:]}"
        fut = asyncio.get_running_loop().create_future()
        self.pending[code] = {"ws": ws, "name": name, "created": now, "future": fut}
        await ws.send_json({"type": "pair_code", "code": code, "expires_in": PAIR_TTL_S})
        log.info("pairing requested: %s code %s", name, code)
        # Keep reading so a dropped socket is noticed while we wait; keepalive pings are skipped.
        reader = asyncio.ensure_future(ws.receive())
        try:
            deadline = now + PAIR_TTL_S
            while not fut.done():
                done, _ = await asyncio.wait({fut, reader}, timeout=max(0.0, deadline - time.time()),
                                             return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    return None
                if reader in done and not fut.done():
                    if reader.result().type != WSMsgType.TEXT:
                        return None
                    reader = asyncio.ensure_future(ws.receive())
            token = secrets.token_urlsafe(32)
            device = {"id": secrets.token_hex(4), "name": name, "sha256": _sha(token),
                      "created": time.strftime("%Y-%m-%d %H:%M:%S")}
            devices = _load_devices()
            devices.append(device)
            _save_devices(devices)
            await ws.send_json({"type": "paired", "device_token": token, "device_id": device["id"]})
            log.info("paired: %s (%s)", name, device["id"])
            return device
        finally:
            # Let the cancelled receive() finish before the caller reads the socket again;
            # aiohttp refuses a second concurrent receive().
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await reader
            self.pending.pop(code, None)

    def _expire_pending(self) -> None:
        now = time.time()
        for code in [c for c, p in self.pending.items() if now - p["created"] > PAIR_TTL_S]:
            self.pending.pop(code, None)

    # ---- control side (unix socket) -------------------------------------------------------

    async def status(self, request: web.Request) -> web.Response:
        self._expire_pending()
        return web.json_response({
            "connected": self.ext is not None and not self.ext.closed,
            "device": {k: self.ext_device[k] for k in ("id", "name")} if self.ext_device else None,
            "connected_for_s": int(time.time() - self.ext_since) if self.ext else None,
            "pending_pairings": [{"code": c, "name": p["name"],
                                  "expires_in": int(PAIR_TTL_S - (time.time() - p["created"]))}
                                 for c, p in self.pending.items()],
            "devices": [{k: d[k] for k in ("id", "name", "created")} for d in _load_devices()],
        })

    async def approve(self, request: web.Request) -> web.Response:
        body = await request.json()
        code = str(body.get("code", "")).strip().upper().replace(" ", "")
        if len(code) == 6:
            code = f"{code[:3]}-{code[3:]}"
        self._expire_pending()
        p = self.pending.get(code)
        if p is None:
            return web.json_response({"ok": False, "error": "No pending pairing with that code."}, status=404)
        if not p["future"].done():
            p["future"].set_result(True)
        return web.json_response({"ok": True, "name": p["name"]})

    async def revoke(self, request: web.Request) -> web.Response:
        body = await request.json()
        dev_id = str(body.get("id", ""))
        devices = _load_devices()
        kept = [d for d in devices if d["id"] != dev_id]
        if len(kept) == len(devices):
            return web.json_response({"ok": False, "error": "No device with that id."}, status=404)
        _save_devices(kept)
        if self.ext_device and self.ext_device["id"] == dev_id and self.ext:
            # Tell the extension first, so it forgets its token instead of retrying.
            with contextlib.suppress(Exception):
                await self.ext.send_json({"type": "unpaired"})
            await self.ext.close(code=4003, message=b"device revoked")
        return web.json_response({"ok": True})

    async def cmd(self, request: web.Request) -> web.Response:
        body = await request.json()
        ws = self.ext
        if ws is None or ws.closed:
            return web.json_response({"ok": False, "error": (
                "The remote browser is not connected. Ask the user to open the Hermes Remote "
                "Browser extension in Chrome and switch it on.")})
        cid = self.next_id
        self.next_id += 1
        fut = asyncio.get_running_loop().create_future()
        self.waiters[cid] = fut
        await ws.send_json({"type": "cmd", "id": cid, "action": body.get("action"),
                            "params": body.get("params") or {}})
        try:
            res = await asyncio.wait_for(fut, CMD_TIMEOUT_S)
        except asyncio.TimeoutError:
            self.waiters.pop(cid, None)
            return web.json_response({"ok": False, "error": f"No answer from the browser in {CMD_TIMEOUT_S}s."})
        return web.json_response({k: v for k, v in res.items() if k in ("ok", "data", "error")})


async def _root(request: web.Request) -> web.Response:
    return web.Response(text="Hermes Remote Browser relay\n")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    HOME.mkdir(parents=True, exist_ok=True)
    if len(str(SOCK).encode()) > 107:   # Linux limit for unix socket paths
        raise SystemExit(f"{SOCK} is too long for a unix socket; set REMOTE_BROWSER_HOME to a shorter path.")
    os.umask(0o077)
    bridge = Bridge()

    public = web.Application(client_max_size=1024)
    public.router.add_get("/", _root)
    public.router.add_get("/ext", bridge.ext_handler)

    control = web.Application(client_max_size=64 * 1024)
    control.router.add_get("/status", bridge.status)
    control.router.add_post("/approve", bridge.approve)
    control.router.add_post("/revoke", bridge.revoke)
    control.router.add_post("/cmd", bridge.cmd)

    pub_runner, ctl_runner = web.AppRunner(public, access_log=None), web.AppRunner(control, access_log=None)
    await pub_runner.setup()
    await ctl_runner.setup()
    await web.TCPSite(pub_runner, PUBLIC_HOST, PUBLIC_PORT).start()
    SOCK.unlink(missing_ok=True)
    await web.UnixSite(ctl_runner, str(SOCK)).start()
    SOCK.chmod(0o600)
    log.info("listening on %s:%s (extension) and %s (control)", PUBLIC_HOST, PUBLIC_PORT, SOCK)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
