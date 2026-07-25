"""mitmproxy addon — streams each intercepted flow (with bodies) to ReconForge.

Works for ANY client pointed at the proxy: the Android emulator OR Firefox/any
browser (Burp-style). Captures text request/response bodies so the AI can read
the full exchange. Run:  mitmdump -q -p 8080 -s mitm_addon.py
"""
import json
import os
import threading
import urllib.request

BACKEND = os.environ.get("RECONFORGE_BACKEND", "http://127.0.0.1:8777")
_PUSH = BACKEND.rstrip("/") + "/api/intercept/push"
_TEXTY = ("json", "text", "xml", "javascript", "x-www-form-urlencoded", "html", "graphql", "csv")
_LIMIT = 8192


def _post(data: dict):
    try:
        req = urllib.request.Request(
            _PUSH, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass


def _body(msg, limit: int = _LIMIT):
    try:
        ct = msg.headers.get("content-type", "")
        if not any(t in ct.lower() for t in _TEXTY):
            return None
        txt = msg.get_text(strict=False)
        return txt[:limit] if txt else None
    except Exception:
        return None


def response(flow):
    try:
        r = flow.request
        data = {
            "method": r.method,
            "url": r.pretty_url,
            "host": r.host,
            "path": r.path.split("?", 1)[0],
            "query": r.query.fields and dict(r.query) or {},
            "status": flow.response.status_code,
            "req_headers": dict(r.headers),
            "res_headers": {k: v for k, v in flow.response.headers.items()
                            if k.lower() in ("content-type", "set-cookie", "location", "server", "www-authenticate")},
            "req_body": _body(r),
            "res_body": _body(flow.response),
            "res_ctype": flow.response.headers.get("content-type", ""),
            "req_len": len(r.raw_content or b""),
            "res_len": len(flow.response.raw_content or b""),
        }
    except Exception:
        return
    threading.Thread(target=_post, args=(data,), daemon=True).start()
