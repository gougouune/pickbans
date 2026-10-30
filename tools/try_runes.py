"""Test the rune import against a fake League client (nothing touches a real account).  python tools/try_runes.py"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pickbans import net  # noqa: E402
from pickbans.lcu import LCU  # noqa: E402

STATE = {"pages": [], "owned": 2, "next": 100, "calls": [], "refuse": False}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj=None, code=200):
        body = json.dumps(obj).encode() if obj is not None else b""
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/pages"):
            return self._send(STATE["pages"])
        if self.path.endswith("/inventory"):
            return self._send({"ownedPageCount": STATE["owned"]})
        self._send(None, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        STATE["calls"].append(("POST", body["name"]))
        if STATE["refuse"]:
            return self._send({"message": "nope"}, 400)
        STATE["next"] += 1
        STATE["pages"].append(dict(body, id=STATE["next"], isEditable=True))
        self._send(STATE["pages"][-1])

    def do_DELETE(self):
        pid = int(self.path.rsplit("/", 1)[1])
        STATE["calls"].append(("DELETE", pid))
        STATE["pages"] = [p for p in STATE["pages"] if p["id"] != pid]
        self._send(None, 204)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
lcu = LCU(srv.server_address[1], "x")
lcu.base = f"http://127.0.0.1:{srv.server_address[1]}"  # the fake speaks plain HTTP
lcu.get = lambda path, timeout=5: net.get_json(lcu.base + path, timeout=timeout)
RUNES = {"primary": 8200, "sub": 8000, "perks": [8992, 8226, 8210, 8237, 8017, 9105, 5008, 5008, 5001]}
names = lambda: [p["name"] for p in STATE["pages"]]

STATE["pages"] = [{"id": 1, "name": "My page", "isEditable": True}]
print("1) free slot:", lcu.import_runes(RUNES), names())
assert names() == ["My page", "PICKBANS"]

print("2) again (reuses its page):", lcu.import_runes(dict(RUNES, primary=8100)), names())
assert names() == ["My page", "PICKBANS"] and STATE["pages"][-1]["primaryStyleId"] == 8100

STATE["pages"] = [{"id": 1, "name": "Mine A", "isEditable": True}, {"id": 2, "name": "Mine B", "isEditable": True}]
print("3) all pages are yours:", lcu.import_runes(RUNES), names())
assert names() == ["Mine A", "Mine B"]  # your pages are untouched

STATE["pages"] = [{"id": 1, "name": "Mine A", "isEditable": True}]
STATE["refuse"] = True
print("4) client refuses:", lcu.import_runes(RUNES), names())
assert names() == ["Mine A"]
print("All good: your own pages were never deleted or changed.")
srv.shutdown()
