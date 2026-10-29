"""remote-browser for Hermes Agent: one ``remote_browser`` tool that drives a Chrome on another machine.

The Hermes Remote Browser extension in that Chrome keeps a websocket open to the relay on this
server (remote-browser-relay.service, ~/.local/share/hermes-remote-browser). This plugin talks to
the relay's owner-only unix socket; the relay forwards each command to the extension and returns
its answer.

Safety:
- The extension only exposes tabs in its "Hermes" tab group, refuses password fields, and is
  off until the user switches it on (it switches itself off again after a set time).
- Browsing actions run without a prompt (the extension switch and tab group are the gate);
  approve_pairing always asks the user, once per code.
"""
from __future__ import annotations

import base64
import http.client
import json
import logging
import os
import socket
import time
from pathlib import Path

log = logging.getLogger("remote_browser.hermes")

PLUGIN = "remote-browser"
SOCK = Path(os.environ.get("REMOTE_BROWSER_HOME", Path.home() / ".local/share/hermes-remote-browser")) / "control.sock"
TIMEOUT_S = 60

ACTIONS = ["status", "pairing_requests", "approve_pairing", "tabs", "open", "snapshot", "click", "type", "select", "scroll", "key",
           "back", "screenshot", "close"]

DESCRIPTION = (
    "Use the Chrome browser on the user's own computer (their logged-in sessions) through the Hermes "
    "Remote Browser extension. You can only see and use tabs in the purple \"Hermes\" tab group in that "
    "Chrome; 'open' creates new tabs there. Works only while the user has the extension switched on: "
    "if it says not connected, ask them to open the extension in Chrome and switch it on. Typical loop: "
    "open a url -> snapshot (page text plus numbered elements [ref]) -> click/type by ref -> snapshot "
    "again (refs change when the page changes). Use screenshot when the layout matters. Never enter "
    "passwords, payment details or 2FA codes (password fields are blocked); ask the user before anything "
    "outward-facing or hard to undo (sending, posting, buying, deleting, changing settings). "
    "For browsing that doesn't need the user's logins, prefer the normal browser tools."
)

SCHEMA = {
    "name": "remote_browser",
    "description": DESCRIPTION,
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ACTIONS, "description": (
                "status: is the bridge connected. pairing_requests: codes waiting for approval. "
                "approve_pairing: approve the code the user read to you from the extension (code; the "
                "user confirms on screen; only when the user asked you to pair). tabs: list Hermes-group tabs. open: load url (new tab "
                "unless tab_id or new_tab=false). snapshot: text + numbered elements. click/type/select "
                "by ref. scroll: direction up/down/top/bottom. key: press a key (Enter, Escape, Tab) on "
                "the focused element. back. screenshot: image of the tab (brings it to front). close.")},
            "url": {"type": "string", "description": "open: http(s) URL."},
            "code": {"type": "string", "description": "approve_pairing: code shown in the extension, e.g. ABC-123."},
            "tab_id": {"type": "integer", "description": "Tab to act on; defaults to the last one used."},
            "new_tab": {"type": "boolean", "description": "open: false reuses the current Hermes-group tab."},
            "ref": {"type": "integer", "description": "click/type/select: element number from the latest snapshot."},
            "text": {"type": "string", "description": "type: text to enter."},
            "clear": {"type": "boolean", "description": "type: replace existing text (default true)."},
            "submit": {"type": "boolean", "description": "type: press Enter / submit the form afterwards."},
            "value": {"type": "string", "description": "select: option value or visible text."},
            "direction": {"type": "string", "enum": ["up", "down", "top", "bottom"]},
            "pixels": {"type": "integer", "description": "scroll: distance (default ~one screen)."},
            "key": {"type": "string", "description": "key: key name, e.g. Enter."},
            "max_chars": {"type": "integer", "description": "snapshot: page text limit (default 6000)."},
        },
        "required": ["action"],
    },
}


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def _relay(method: str, path: str, body: dict | None = None) -> dict:
    conn = _UnixHTTPConnection(str(SOCK), TIMEOUT_S)
    try:
        payload = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, body=payload, headers={"Content-Type": "application/json"})
        return json.loads(conn.getresponse().read() or b"{}")
    finally:
        conn.close()


def _result(success: bool, **fields) -> str:
    return json.dumps({"success": success, **{k: v for k, v in fields.items() if v not in (None, "")}},
                      ensure_ascii=False)


def _data_dir() -> Path:
    try:
        from plugins.plugin_storage import plugin_data_dir
        return Path(plugin_data_dir(PLUGIN))
    except Exception:
        return Path.home() / ".hermes" / "plugin-data" / PLUGIN


def _save_image(data_url: str) -> Path:
    header, _, b64 = data_url.partition(",")
    ext = ".png" if "png" in header else ".jpg"
    out = _data_dir() / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"shot-{time.strftime('%Y%m%d-%H%M%S')}{ext}"
    path.write_bytes(base64.b64decode(b64))
    for old in sorted(out.glob("shot-*"))[:-20]:     # keep the 20 newest
        old.unlink(missing_ok=True)
    return path


def _attach_image(result: dict, path: Path) -> dict | None:
    """Image tool result for a model that can view it, or None to keep the text result."""
    try:
        from tools.vision_tools import (
            _EMBED_MAX_DIMENSION,
            _resize_image_for_vision,
            _should_use_native_vision_fast_path,
        )
        from tools.vision_tools_history_budget import resolve_embed_target_bytes
        if not _should_use_native_vision_fast_path():
            return None
        data_url = _resize_image_for_vision(
            path, mime_type="image/jpeg", max_base64_bytes=resolve_embed_target_bytes(),
            max_dimension=_EMBED_MAX_DIMENSION, force_jpeg=True,
        )
        if not isinstance(data_url, str) or not data_url.startswith("data:"):
            return None
        text = json.dumps(result, ensure_ascii=False)
        return {
            "_multimodal": True,
            "text_summary": text,
            "meta": {"screenshot_path": str(path), "native_vision": True},
            "content": [
                {"type": "text", "text": text + "\n\nThe screenshot is attached — inspect it with your native vision."},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    except Exception as exc:
        log.debug("screenshot attach failed, returning text: %s", exc)
        return None


def remote_browser(args: dict, **kwargs) -> str | dict:
    args = dict(args or {})
    action = str(args.pop("action", "") or "")
    if action not in ACTIONS:
        return _result(False, error=f"Unknown action {action!r}. Use one of: {', '.join(ACTIONS)}.")
    try:
        if action == "status":
            st = _relay("GET", "/status")
            return _result(True, connected=st.get("connected"), device=st.get("device"),
                           note=None if st.get("connected") else
                           "Not connected: ask the user to open the Hermes Remote Browser extension in Chrome and switch it on.")
        if action == "pairing_requests":
            st = _relay("GET", "/status")
            return _result(True, pending=st.get("pending_pairings", []), paired_browsers=st.get("devices", []))
        if action == "approve_pairing":
            res = _relay("POST", "/approve", {"code": str(args.get("code") or "")})
            if not res.get("ok"):
                return _result(False, error=res.get("error") or "Approval failed.")
            return _result(True, approved=res.get("name"),
                           note="Paired. The extension switches itself on; check with action status.")
        res = _relay("POST", "/cmd", {"action": action, "params": args})
    except (FileNotFoundError, ConnectionRefusedError):
        return _result(False, error="The remote browser relay is not running on this server (remote-browser-relay.service).")
    except (OSError, ValueError) as exc:
        return _result(False, error=f"Could not reach the remote browser relay: {exc}")
    if not res.get("ok"):
        return _result(False, error=res.get("error") or "The browser reported an error.")
    data = res.get("data") or {}
    if action == "screenshot" and isinstance(data.get("image"), str):
        path = _save_image(data.pop("image"))
        payload = {"success": True, **data, "screenshot_path": str(path)}
        return _attach_image(payload, path) or json.dumps(payload, ensure_ascii=False)
    return _result(True, **data) if isinstance(data, dict) else _result(True, data=data)


def _available() -> bool:
    return SOCK.exists()


def _on_pre_tool_call(tool_name: str = "", args: dict | None = None, task_id: str = "", **kwargs):
    if tool_name != "remote_browser":
        return None
    a = args or {}
    action = str(a.get("action") or "")
    if action != "approve_pairing":
        # Ordinary browsing needs no prompt: the user's on/off switch, auto-off and the
        # "Hermes" tab group in the extension are the gate.
        return None
    # Never covered by a session/always answer: each code is its own rule, so a page or message
    # that tricks the agent into approving a stranger's browser still needs the user's click.
    code = str(a.get("code") or "").strip().upper()
    return {"action": "approve", "rule_key": f"remote_browser_pair:{code}",
            "message": f"Pair a new browser with Hermes Remote Browser (code {code})? Approve only if this "
                       "is the code showing in YOUR Chrome's extension popup right now."}


def register(ctx) -> None:
    ctx.register_tool(name="remote_browser", toolset=PLUGIN, schema=SCHEMA, handler=remote_browser,
                      check_fn=_available, emoji="🖥️")
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
