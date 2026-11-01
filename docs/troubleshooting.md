# Troubleshooting

Start with the remote browser `setup` and `status` actions. Note which step fails before
changing anything. A working HTTPS banner alone does not prove the browser is connected.

| Symptom | What to check |
|---|---|
| Tool missing after install | Restart the Hermes process that serves this conversation. If you use a separate desktop/dashboard process, restart that too. Check that the plugin is enabled. |
| Relay reports "address already in use" | Another process may own the port. Identify it before stopping anything. If you choose a different `REMOTE_BROWSER_PORT`, update the tunnel route too. |
| Local relay banner works, public URL returns 502 | The tunnel's local service must be HTTP, not HTTPS, and must use the relay's actual port. A connector in a container cannot reach the host relay through its own loopback address. |
| Public URL shows a login page | An interactive access gateway is intercepting the extension. It cannot complete that login. Use a dedicated, pairing-protected relay hostname only if your security policy permits it. |
| Banner works, pairing never gets a code | Check websocket support on the reverse proxy, use `wss://your-hostname`, and inspect the extension popup error. |
| Code has expired or cannot be approved | Click **Pair this browser** again and give the new code to the agent. Confirm only the code you can see in your own extension. |
| Popup says "unpaired on the server" | The saved browser token is no longer recognized, for example after revocation or loss of relay state. Pair again. |
| Paired, but `status` says disconnected | Click **Switch on**. The extension starts switched off and switches off automatically after the selected interval. |
| A second browser disconnects the first | Only one browser can be connected at a time. A newer connection replaces the previous one. |
| An existing tab is missing | Move it into the purple **Hermes** tab group. Tabs outside that group are intentionally unavailable. |
| A click or typing does nothing | Some sites reject synthetic input; rich editors may need manual input. Ask the user to complete that step. Don't use this to bypass a site's checks. |
| Element reference no longer works | Take a fresh snapshot after the page changes, then use its new reference numbers. |
| Chrome settings or Web Store page cannot be controlled | Chrome protects these pages from scripting. Complete extension installation and settings yourself. |
| Screenshot changes the active tab | This is expected: screenshots bring the agent's tab to the front of its window. |

## What to include in a report

Use the [first-run report form](https://github.com/driftverse/hermes-remote-browser/issues/new?template=first-run.yml).
Include your server OS, Hermes version, browser version, proxy/tunnel type, the failed step and
a redacted error message. Report success too; it helps establish actual compatibility.

Do **not** attach device tokens, pairing codes, cookies, `.env` files, private page text,
`devices.json`, or unreviewed screenshots/logs. Read and redact diagnostic output before posting.
There is no need to share your public hostname; use `browser.example.com` as a substitute.
