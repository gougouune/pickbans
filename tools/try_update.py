"""Local end-to-end check of the auto-update chain, no GitHub needed.  python tools/try_update.py
publish -> serve the folder over HTTP -> an app with an OLD pack must download it; an up-to-date app must not."""
import copy
import functools
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(prefix="pickbans_update_")
pub = os.path.join(tmp, "public")

run = lambda *a: subprocess.run([sys.executable, os.path.join(ROOT, "tools", "publish_pack.py"), *a], capture_output=True, text=True).stdout.strip()
print("publish 1:", run("--out", pub, "--no-fetch"))
print("publish 2:", run("--out", os.path.join(tmp, "public2"), "--previous", pub, "--no-fetch"), "(must say unchanged)")
m1 = json.load(open(os.path.join(pub, "manifest.json")))
m2 = json.load(open(os.path.join(tmp, "public2", "manifest.json")))
print("built_at kept:", m1["built_at"] == m2["built_at"], "| manifest:", {k: m1[k] for k in ("version", "pairs", "app_version")})

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=pub)
handler.log_message = lambda *a: None
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()

from pickbans import pack as P, paths  # noqa: E402

P.REMOTE_BASE = f"http://127.0.0.1:{srv.server_address[1]}/"
paths.USER_PACK = os.path.join(tmp, "user_pack.json")

current = json.load(open(os.path.join(pub, "pack.json"), encoding="utf-8"))
old = copy.deepcopy(current)
old["built_at"] -= 86400
old["matchups"] = {}
got, manifest = P.fetch_remote(old)
print("old app  -> downloaded:", got is not old, "| pairs now:", sum(len(t) for r in got["matchups"].values() for t in r.values()),
      "| saved:", os.path.exists(paths.USER_PACK))
got2, _ = P.fetch_remote(current)
print("fresh app -> downloaded:", got2 is not current, "(must be False)")
P.REMOTE_BASE = "http://127.0.0.1:9/"  # nothing listens here
pk, msg, man = P.auto_update(current)
print("host down -> app still fine:", msg, "| manifest:", man)
srv.shutdown()
