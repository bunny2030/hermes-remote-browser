# Give the relay an HTTPS address with Cloudflare Tunnel

This guide assumes you already have a domain on Cloudflare and a tunnel connector running
on the same server as Hermes. If you don't, start with the
[Cloudflare Tunnel documentation](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/).
Cloudflare's dashboard labels can change; look for the tunnel's public hostname or published application routes.

You will publish the relay's browser endpoint. Pairing controls which browser can connect;
the relay's separate control socket stays on the server. Use a dedicated hostname such as
`browser.example.com`, not a route to your whole home network.

## 1. Check the relay before changing the tunnel

Install the plugin using the [README](../README.md#quick-start), restart your Hermes process,
and ask the agent to run the remote browser `setup` action. Resolve any relay startup error first.

On the server, this read-only check should return `Hermes Remote Browser relay`:

```bash
curl --fail --show-error http://127.0.0.1:9178/
```

If you configured a different `REMOTE_BROWSER_PORT`, use that port throughout this guide.
Keep the relay bound to loopback. You don't need to open a router port.

## 2. Add a route to the existing tunnel

In Cloudflare's dashboard, open your tunnel and add a public hostname / published application:

| Setting | Example |
|---|---|
| Hostname | `browser.example.com` |
| Service type | `HTTP` |
| Service URL | `127.0.0.1:9178` |

Keep existing tunnel routes unchanged. The public side uses HTTPS; the local service uses HTTP.
Setting the local service to HTTPS will fail because the relay itself does not serve TLS.

This loopback address works only when the connector and relay share the host's network namespace.
If your connector runs in a container, `127.0.0.1` means that container. Stop here and resolve that
networking difference rather than exposing the relay on every interface.

**Do not add an interactive Cloudflare Access login to this hostname.** The extension cannot
complete that login. This endpoint uses the plugin's device pairing instead. If your policy
requires Access, this setup is not compatible as written; don't disable unrelated protections.

## 3. Check the public address

From a different network, if possible:

```bash
curl --fail --show-error https://browser.example.com/
```

Expect the same relay banner. That checks DNS, HTTPS and origin routing, but does **not** prove
websocket connectivity or browser pairing. The next step checks those.

## 4. Pair Chrome

1. Install the extension using the [README](../README.md#quick-start).
2. Open its popup and enter `wss://browser.example.com` (no `/ext` suffix).
3. Click **Pair this browser**.
4. Give the displayed code to your agent and confirm the pairing when Hermes asks.
5. Click **Switch on**.
6. Ask the agent for remote browser `status`. It should report `connected: true`.

Never post the code, device token or relay state files in an issue. Continue with the
[first-run test](first-run-test.md), or use [troubleshooting](troubleshooting.md) if it fails.
