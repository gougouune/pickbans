"""Tiny HTTP helpers on the standard library only (keeps the .exe dependency-free)."""
import base64
import json
import ssl
import urllib.request

_INSECURE = ssl.create_default_context()
_INSECURE.check_hostname = False
_INSECURE.verify_mode = ssl.CERT_NONE


def get_json(url, timeout=10, auth=None, insecure=False):
    req = urllib.request.Request(url, headers={"User-Agent": "PICKBANS"})
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    ctx = _INSECURE if insecure else None
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return json.loads(r.read().decode("utf-8"))


def send(method, url, body=None, timeout=10, auth=None, insecure=False):
    """POST / PUT / DELETE with an optional JSON body. Returns the JSON answer or None if empty."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": "PICKBANS", "Content-Type": "application/json"})
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=timeout, context=_INSECURE if insecure else None) as r:
        raw = r.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else None
