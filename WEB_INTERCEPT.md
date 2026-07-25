# ReconForge — Web / Firefox interception (Burp-style)

The same mitmproxy sidecar that intercepts the emulator also intercepts **any
browser**. Point Firefox at it and every request/response (with bodies) streams
into the **🌐 Network** tab — clickable, and "Send to agent" for AI analysis.

## One-time Firefox setup
1. In ReconForge → Network tab, set **Target: Firefox / Web**, click **▶ Start intercept**
   (runs `mitmdump` on `127.0.0.1:8080`, does NOT touch the emulator proxy).
2. Point Firefox at the proxy:
   `Settings → Network Settings → Manual proxy` →
   HTTP Proxy `127.0.0.1` Port `8080`, tick **"Also use this proxy for HTTPS"**.
3. Trust the mitmproxy CA **inside Firefox** (Firefox has its own cert store):
   - With the proxy on, browse to **http://mitm.it** → download the certificate → *or*
   - `Settings → Privacy & Security → Certificates → View Certificates → Authorities →
     Import` → `~/.mitmproxy/mitmproxy-ca-cert.pem` → tick **"Trust… to identify websites"**.

Now browse normally — HTTPS is decrypted and each flow appears live in ReconForge.

## Using it
- Click any flow → full request/response headers + bodies.
- **Send to agent** → the assistant reads the full exchange and looks for
  auth tokens, IDOR/BOLA, injection, secrets, misconfig.
- **🔎 Analyze all** → hand the whole captured session to the agent at once.
- Tip: keep a dedicated Firefox profile for testing so only target traffic is proxied.

## Notes
- Isolate scope: only browse in-scope targets while intercept is on.
- To stop: **⏸ Stop intercept** (also clears any device proxy) and turn Firefox proxy back to "No proxy".
