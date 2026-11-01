# First-run test

We're looking for the first five community testers with Hermes on a home server or VPS and
Chrome on a different computer. A failed setup is worth reporting too.

Use harmless public pages for this test. You do not need to share a personal account, install
anything beyond the documented plugin and extension, or send private data to the maintainer.
Page content returned to Hermes can reach your configured model provider.

## Setup

- [ ] Install the plugin and restart the relevant Hermes process.
- [ ] Set up a public HTTPS relay hostname with websocket support.
- [ ] Install the unpacked extension from the release ZIP.
- [ ] Pair the browser using the code shown in its popup and confirm in Hermes.
- [ ] Click **Switch on** and confirm remote browser `status` reports `connected: true`.

See the [quick start](../README.md#quick-start), [Cloudflare guide](cloudflare-setup.md) and
[troubleshooting](troubleshooting.md). Record rough setup time and the first confusing step.

## Harmless browsing check

1. Open `https://example.com` yourself in a tab **outside** the Hermes group.
2. Ask the agent to list remote-browser tabs. That tab should not appear.
3. Move the tab into the purple **Hermes** group and list tabs again. It should now appear.
4. Ask: "Use my remote browser to read the shared Example Domain page and tell me its heading.
   Don't submit any forms or change any accounts."
5. Ask the agent to open `https://www.iana.org/help/example-domains` through the remote browser.
   Confirm the new tab is in the Hermes group and ask for a snapshot.
6. Click **Switch off**. Ask for another snapshot; browsing should be refused while access is off.

If any check fails, record what actually happened. Do not widen extension permissions or bypass
pairing to make a test pass.

## Optional checks

- Restart Chrome and confirm the extension stays off until you enable it.
- Choose the shortest auto-off interval, wait for it to expire, and confirm access stops.
- If you want to test an existing login, use a disposable demo account and a read-only task.
  Type any password or one-time code yourself; never send it to the agent or include it in a report.

## Send the result

[Open a first-run report](https://github.com/driftverse/hermes-remote-browser/issues/new?template=first-run.yml).
Include successful and failed checks, versions, approximate setup time and what needs clearer docs.
No private browsing data is needed. A submitted report is evidence from that tester, not a claim
that every OS, browser or site is supported.
