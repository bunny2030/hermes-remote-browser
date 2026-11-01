# Launch kit

Draft copy for the maintainer. These posts have not been published. Do not claim community
testing, Chrome Web Store availability or broad OS compatibility before verifying it.

## Hermes community post

**Title: Hermes on a server, Chrome on your laptop: looking for first testers**

My Hermes agent runs on a home server. My logged-in Chrome is on my laptop. I built
Hermes Remote Browser to connect the two.

The laptop only needs a Chrome extension. It connects out to a small relay on the server,
so there's no companion app, VPN client or inbound port on the laptop. You share tabs by
moving them into a purple Hermes group and switching access on. It automatically switches off.

A few caveats before you install: the server needs a public HTTPS hostname with websocket
support, the extension currently installs unpacked, and some sites ignore scripted input.
Page text and screenshots go into the Hermes conversation and can reach your model provider.

It's MIT licensed. I'm looking for five people with Hermes on a server and Chrome on another
computer to try setup and report what works or breaks. Failed setups count too.

Repo: https://github.com/driftverse/hermes-remote-browser
Test checklist: https://github.com/driftverse/hermes-remote-browser/blob/main/docs/first-run-test.md

## Short post for X

My Hermes agent runs on a server. My logged-in Chrome is on my laptop.

I built a bridge: Chrome extension, shared tabs, an on/off switch.

MIT. Looking for first testers:
https://github.com/driftverse/hermes-remote-browser

## Self-hosting community post

**Title: I built a browser bridge for a server-hosted Hermes agent**

Sharing a small project I made for my home-server setup. Hermes runs on the server, but the
browser sessions I want it to use are on my laptop.

Hermes Remote Browser connects those through a Chrome extension and a Python relay. The
extension opens an outbound websocket to an HTTPS hostname you host. Agent commands reach
the relay over an owner-only Unix socket. The computer running Chrome doesn't need a local
companion program or an open inbound port.

The extension limits browsing to a purple Hermes tab group while its switch is on. Access
expires automatically. It doesn't use Chrome's debugger permission, though it does request
broad host permissions so you can share different sites. The README covers the security model
and prompt-injection risks; this is not a claim of an independent security audit.

Current limits: one connected browser at a time, unpacked extension installation, and synthetic
clicks/typing that some sites reject. Shared content can reach the agent's model provider.

I'd like feedback on the setup and permissions model, especially from people running Hermes
on a VPS or a separate home server. The repo includes a Cloudflare Tunnel guide and a first-run
checklist. Please follow your community's self-promotion rules before sharing this post.

https://github.com/driftverse/hermes-remote-browser

## Real demo recording: about 30 seconds

This is a recording plan, not a finished demo. Use a clean browser profile and harmless pages.
Do not recreate agent results as an animation or show private tabs. A public-page demo proves
remote browser control, but does not prove an existing-login workflow; use a disposable demo
account if you want to show that separately.

| Time | Actual screen action | On-screen text |
|---|---|---|
| 0–5s | Show Hermes on the server beside Chrome on the other computer. | My agent lives on a server. My browser doesn't. |
| 5–10s | Show Example Domain outside the group, then move it into Hermes. | I choose which tabs it gets. |
| 10–21s | Ask Hermes to read that tab. Show the real tool call and returned heading. | Same Chrome. Controlled from another machine. |
| 21–27s | Switch off; show a fresh browsing action being refused. | Off means off. |
| 27–32s | Show the repo URL. | Looking for first testers. MIT licensed. |

If you cut a long wait, label it. Hide notifications, profile emails, hostnames, pairing codes
and tokens. Verify tab isolation and switch-off behavior before recording any claim about them.

## Distribution order

1. Merge the docs and test the issue form so links in posts work.
2. Record the real demo and add it near the top of the README.
3. Share once in the relevant Hermes showcase/plugin channel, after checking its rules.
4. Submit the repo through Hermes Atlas's suggestion process if it is not already listed.
5. Share the technical post in one suitable self-hosting community, if its rules permit it.
6. Help testers, fix their first points of friction and publish a follow-up with actual results.

Track successful independent setups and recurring failures. Stars and release downloads are
secondary signals; neither tells you whether someone got the bridge working.
