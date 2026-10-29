# Hermes Remote Browser

Let a [Hermes Agent](https://github.com/NousResearch/hermes-agent) running on a **home server or
VPS** use the Chrome on **your own computer**, with your logged-in sites, across networks, with
nothing installed on that computer except a browser extension.

```
 Your computer                                 Your server
┌──────────────────────────┐                 ┌────────────────────────────────────────┐
│ Chrome                   │   wss (out)     │ reverse proxy / tunnel (HTTPS)         │
│  └ Hermes Remote Browser ├────────────────▶│  └ relay.py  127.0.0.1:9178  /ext      │
│     extension            │                 │       ▲ control.sock (owner-only)      │
│  └ purple "Hermes" tab   │                 │       │                                │
│    group = what the      │                 │  Hermes Agent ── remote_browser tool   │
│    agent can see         │                 │                  (plugin)              │
└──────────────────────────┘                 └────────────────────────────────────────┘
```

- **The extension dials out.** Your computer opens no ports and needs no VPN client or companion
  program. Any HTTPS hostname that forwards websockets to the relay works; Cloudflare Tunnel is an
  easy free option.
- **The agent only sees the tabs you share.** It can use tabs in a purple **Hermes** tab group,
  and the tabs it opens itself land there. Drag a tab into the group to share it. Everything else
  in your browser stays invisible.
- **Off by default.** You switch it on from the toolbar icon. It switches itself off again after
  15 min / 1 h / 4 h (your choice) and at every browser start.
- **Pairing without secrets.** The extension shows a short code. You approve it on the server,
  either by telling your agent "approve the browser code ABC-123" (Hermes asks you to confirm)
  or with `remote-browser approve ABC-123`. The browser then holds a random device token; the
  server stores only its hash.
- **Password fields are off-limits.** The extension refuses to read or type into them.
- **No `debugger` permission.** Pages are driven with `chrome.scripting` and `chrome.tabs`.

## What the agent can do

One tool, `remote_browser`, with these actions:

| Action | What it does |
|---|---|
| `status` | Is a browser connected? |
| `tabs` | List the tabs in the Hermes group |
| `open` | Open a URL in a new Hermes-group tab (or reuse one: `new_tab: false` / `tab_id`) |
| `snapshot` | Page title, URL, visible text and a numbered list of clickable/typeable elements |
| `click` / `type` / `select` | Act on an element by its number from the latest snapshot |
| `scroll` | `up` / `down` / `top` / `bottom` |
| `key` | Press a key (Enter, Escape, Tab…) on the focused element |
| `back` | Go back |
| `screenshot` | Capture the tab (brings it to the front of its window) |
| `close` | Close a Hermes-group tab |
| `pairing_requests` / `approve_pairing` | See and approve pairing codes (approval always asks you) |

## Requirements

- Hermes Agent with plugin support (tested on v0.22.5) on a Linux server with systemd
- Python 3.11+ for the relay
- A public HTTPS hostname that can forward websockets to `127.0.0.1:9178` on the server
- Chrome (or another Chromium browser) **116 or newer** on your computer

## Install

### 1. Relay (on the server)

```bash
mkdir -p ~/.local/share/hermes-remote-browser
cp relay/relay.py ~/.local/share/hermes-remote-browser/
python3 -m venv ~/.local/share/hermes-remote-browser/venv
~/.local/share/hermes-remote-browser/venv/bin/pip install -r relay/requirements.txt

install -m 755 relay/remote-browser ~/.local/bin/remote-browser
cp relay/remote-browser-relay.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now remote-browser-relay
loginctl enable-linger "$USER"   # keep user services running when you're logged out
remote-browser status
```

### 2. Public hostname

Point a hostname at `http://localhost:9178`. With Cloudflare Tunnel: Zero Trust → Networks →
Tunnels → your tunnel → Public hostnames → add `browser.example.com`, service type **HTTP**
(not HTTPS), URL `localhost:9178`.

Check it: `curl https://browser.example.com/` should print `Hermes Remote Browser relay`.
Only `/ext` (the websocket) is exposed; the control API lives on the unix socket.

Don't put an interactive login page (like Cloudflare Access) in front of this hostname. The
extension can't complete it. Pairing is the access control.

### 3. Hermes plugin (on the server)

```bash
cp -r plugin/remote-browser ~/.hermes/plugins/
```

Add it under `plugins.enabled` in `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - remote-browser
```

Restart Hermes. If you use the web dashboard / Hermes Desktop, restart that too, since its chats
run in a separate process:

```bash
systemctl --user restart hermes-gateway
hermes plugins list | grep remote-browser
```

Optional: add a line to your `SOUL.md` so the agent reaches for the tool, e.g. *"To use the
browser on my computer, use the `remote_browser` tool (find it with tool_search if needed)."*

### 4. Extension (on your computer)

1. Copy the `extension/` folder to your computer.
2. Open `chrome://extensions`, switch on **Developer mode**, click **Load unpacked**, and pick the folder.
3. Click the purple **H** icon, enter `wss://browser.example.com`, and click **Pair this browser**.
4. Approve the code it shows (ask your agent, or run `remote-browser approve CODE` on the server).
5. Click **Switch on**. The badge turns green.

## Day to day

- Ask your agent to do something in your browser. It opens tabs in the purple **Hermes** group.
- Switch the extension off when you're done (or let auto-off do it).
- `remote-browser status`: connection, pending codes, paired browsers
- `remote-browser revoke ID`: unpair a browser (the extension notices and switches off)
- `remote-browser logs`: relay log

## Security model

Read this before using it with accounts that matter.

- **What the agent sees, its model provider sees.** Page text and screenshots go into the
  conversation, and from there to whatever LLM provider your Hermes uses. Pick providers you trust.
- **The gate is on your side.** The switch, auto-off and the tab group are enforced in the extension,
  so the server can't widen them. Browsing actions don't ask for approval each time; sharing a tab
  *is* the approval.
- **Pages can try to trick the agent.** A malicious page can contain instructions aimed at the
  agent (prompt injection). Keep the Hermes group to sites you trust, and keep Hermes's own
  approvals on for anything risky.
- **Pairing** codes are 6 characters, expire after 5 minutes, at most 3 can be pending, and at
  most 10 can be requested per 10 minutes. Each approval through the agent asks you to confirm
  that exact code. An agent with shell access to the server could still call the relay's control
  socket directly; the relay can't stop software running as the same user.
- **Tokens** are 256-bit random values. The server stores only their SHA-256 hash
  (`devices.json`, mode 600).
- **Events are synthetic.** Clicks and typing come from page scripts, so pages see them as
  scripted, not as real input. That's also why a few sites ignore them.

## Limitations

- One connected browser at a time (a new connection replaces the old one).
- Some sites ignore scripted clicks/typing, and rich editors may not accept `type`.
- `screenshot` brings the agent's tab to the front of its window.
- Pages Chrome protects (`chrome://`, the Web Store) can't be scripted.

## Configuration

| Variable | Default | Used by |
|---|---|---|
| `REMOTE_BROWSER_HOME` | `~/.local/share/hermes-remote-browser` | relay, plugin, CLI (state + `control.sock`) |
| `REMOTE_BROWSER_HOST` | `127.0.0.1` | relay websocket listener |
| `REMOTE_BROWSER_PORT` | `9178` | relay websocket listener |

## Related projects

Other ways to connect Hermes to a browser, which may suit you better if Hermes runs on the same
computer as your browser:

- [Hermes Connector](https://hermesatlas.com/projects/CorsenAI/hermes-connector): extension + local companion
- [hermes-chrome](https://github.com/leaf76/hermes-chrome): local bridge + extension
- [Hermes Browser Extension](https://hermesatlas.com/projects/abundantbeing/hermes-browser-extension): side panel

Hermes's built-in browser tools can also attach to Chrome over the DevTools port
(`--remote-debugging-port`).

## License

MIT, see [LICENSE](LICENSE). Not affiliated with Nous Research or Google.
