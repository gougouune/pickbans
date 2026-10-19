"""PICKBANS main loop: watch the client, run the engine, serve the UI."""
import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, demo, live, net, paths
from .assess import assess
from .draft import infer_roles, parse_session
from .engine import Engine
from .home import build_home, pool_of
from .lcu import LCU, find_credentials
from .pack import DDRAGON, auto_update, load_pack, refresh_pool, refresh_tiers
from .profile import Profile

log = logging.getLogger("pickbans")

IN_GAME = {"GameStart", "InProgress", "Reconnect"}


def _newer(a, b):
    num = lambda v: tuple(int(x) for x in str(v or "0").split(".") if x.isdigit())
    return num(a) > num(b)
POST_GAME = {"PreEndOfGame", "EndOfGame", "WaitingForStats"}


class App:
    def __init__(self):
        self.lock = threading.Lock()
        self.pack = load_pack()
        self.engine = Engine(self.pack)
        self.id_to_key = {cid: c["key"] for cid, c in self.pack["champions"].items()}
        self.lcu = None
        self.profile = Profile()
        self.profile_stale = True
        self.last_draft = None
        self.demo_steps = None
        self.last_poll = 0.0
        self.profile_loading = False
        self.tracker = None
        self.state = {"status": "starting", "seq": 0, "message": "Starting…", "version": __version__,
                      "patch": self.pack["version"], "meta_source": self.pack.get("meta_source", "baseline"),
                      "stats_rank": self.pack.get("stats_rank")}

    # ---------- state ----------
    def set(self, **kw):
        with self.lock:
            if all(k in self.state and self.state[k] == v for k, v in kw.items()):
                return  # nothing changed: don't make the window redraw
            self.state.update(kw)
            self.state["seq"] += 1

    def snapshot(self):
        self.last_poll = time.time()
        with self.lock:
            return dict(self.state)

    # ---------- startup ----------
    def update_pack(self):
        pack, msg, manifest = auto_update(self.pack)
        log.info(msg)
        if manifest and _newer(manifest.get("app_version"), __version__):
            self.set(update={"version": manifest["app_version"], "url": manifest.get("app_url")})
        pack, stats_msg = refresh_tiers(pack)
        if stats_msg:
            log.info(stats_msg)
        self.pack = pack
        self.engine = Engine(pack)
        self.id_to_key = {cid: c["key"] for cid, c in pack["champions"].items()}
        self.set(patch=pack["version"], pack_msg=msg, meta_source=pack.get("meta_source", "baseline"),
                 stats_rank=pack.get("stats_rank"))
        if not self.demo_steps and (self.profile.mastery or self.profile.recent):
            self.set(home=build_home(self.engine, self.profile))

    def champs_json(self):
        v = self.pack["version"]
        return {cid: {"name": c["name"], "img": f"{DDRAGON}/cdn/{v}/img/champion/{cid}.png", "styles": c["styles"],
                      "dmg": c["dmg"]}
                for cid, c in self.pack["champions"].items()}

    # ---------- main loop ----------
    def loop(self):
        threading.Thread(target=self.update_pack, daemon=True).start()
        while True:
            try:
                if self.demo_steps is not None:
                    self.tick_demo()
                    time.sleep(0.25)
                    continue
                self.tick_client()
            except Exception:
                log.exception("loop error")
                self.lcu = None
                time.sleep(2)

    def tick_client(self):
        if not self.lcu:
            creds = find_credentials()
            if not creds:
                self.set(status="no_client", message="Open League of Legends — PICKBANS will connect by itself.")
                time.sleep(3)
                return
            self.lcu = LCU(*creds)
            self.profile_stale = True
            log.info("connected to client on port %s", creds[0])
        try:
            phase = self.lcu.phase()
        except Exception:
            log.info("client gone")
            self.lcu = None
            return
        if self.profile_stale and not self.profile_loading and phase not in IN_GAME and phase not in POST_GAME:
            self.profile_stale = False
            self.profile_loading = True
            threading.Thread(target=self.load_profile, args=(self.lcu,), daemon=True).start()
        if phase == "ChampSelect":
            s = self.lcu.session()
            if s:
                if not self.state.get("in_select"):
                    pick = self.lcu.pickable_ids()
                    if pick:
                        self.profile.owned = {self.engine.key_to_id[k] for k in pick if k in self.engine.key_to_id}
                self.on_session(s)
            time.sleep(0.5)
        elif phase in IN_GAME:
            self.tick_live(live.fetch())
            time.sleep(2)
        else:
            self.tracker = None
            if phase in POST_GAME:
                self.profile_stale = True
            if self.state.get("status") != "assessment" or phase in ("Lobby", "Matchmaking", "ReadyCheck"):
                msg = {"Lobby": "In lobby — queue up!", "Matchmaking": "In queue…", "ReadyCheck": "Match found!"}.get(phase, "Waiting for champ select…")
                self.set(status="idle", message=msg, in_select=False, profile=self.profile.to_json())
            time.sleep(1)

    def load_profile(self, lcu):
        """Runs in the background — match history can take 10+ s on a slow client."""
        try:
            p = Profile.from_lcu(lcu, self.engine.key_to_id)
            if self.profile.owned and p.owned is None:
                p.owned = self.profile.owned
            if not self.demo_steps:
                self.profile = p
                self.set(profile=p.to_json(), home=build_home(self.engine, p))
            log.info("profile: %s, %d mastery champs, %d recent games", p.name, len(p.mastery),
                     sum(g["games"] for g in p.games.values()))
            added = p.backfill(lcu, self.engine)  # who you laned against, for the matchup notebook
            if added and not self.demo_steps:
                log.info("matchup notebook: %d games added", added)
                self.set(home=build_home(self.engine, p))
            n = refresh_pool(self.pack, pool_of(self.engine, p))  # plan B if the published pack is late
            if n and not self.demo_steps:
                log.info("refreshed %d matchup tables for your champions from OP.GG", n)
                self.set(home=build_home(self.engine, p))
        except Exception:
            log.exception("profile load failed")
        finally:
            self.profile_loading = False

    def on_session(self, s):
        d = parse_session(s, self.engine.key_to_id)
        infer_roles(d["enemies"], self.engine.role_rate)
        self.last_draft = d
        recs = self.engine.recommend(d, self.profile)
        extra = {}
        if d["phase"] == "FINALIZATION":
            extra["assessment"] = assess(self.engine, d, self.profile)
            me = next((a for a in d["allies"] if a["is_me"]), {})
            if me.get("champ") and not self.demo_steps:
                self.profile.log_game(d["game_id"], me["champ"], recs["role"], recs["opponent"])
        self.set(status="champ_select", in_select=True, draft=d, recs=recs, message="", live=None, **extra)

    def show_assessment(self):
        self.set(status="assessment", in_select=False, assessment=assess(self.engine, self.last_draft, self.profile))

    def tick_live(self, data):
        """In game: keep the assessment up and refresh the live panel (clock, level 6 alerts, objectives)."""
        if self.tracker is None:
            self.tracker = live.LiveTracker(self.engine)
        if data and not self.last_draft:
            self.last_draft = self.tracker.draft_from_live(data)  # PICKBANS opened mid-game
        if self.last_draft and self.state.get("status") != "assessment":
            self.show_assessment()
        if data and self.last_draft:
            self.set(live=self.tracker.update(data, self.last_draft))

    # ---------- demo ----------
    def start_demo(self):
        key_of = lambda cid: self.id_to_key[cid]
        self.saved_profile = self.profile
        self.profile = demo.demo_profile(key_of)
        self.demo_steps = demo.timeline(key_of)
        self.demo_t0 = time.time()
        self.demo_game_t0 = None
        self.tracker = None
        self.last_draft = None
        self.demo_i = 0
        self.set(demo=True, status="idle", message="Demo: champ select starts in a few seconds…",
                 profile=self.profile.to_json(), home=build_home(self.engine, self.profile))

    def stop_demo(self):
        self.demo_steps = None
        self.demo_game_t0 = None
        self.tracker = None
        self.profile = getattr(self, "saved_profile", self.profile)
        self.last_draft = None
        self.set(demo=False, status="starting", message="", assessment=None, draft=None, recs=None, live=None,
                 profile=self.profile.to_json(), home=build_home(self.engine, self.profile))

    def tick_demo(self):
        el = time.time() - self.demo_t0
        while self.demo_i < len(self.demo_steps) and self.demo_steps[self.demo_i][0] <= el:
            _, phase, s = self.demo_steps[self.demo_i]
            self.demo_i += 1
            if phase == "ChampSelect":
                self.on_session(s)
            else:
                self.demo_game_t0 = time.time()
        if getattr(self, "demo_game_t0", None) and self.demo_i >= len(self.demo_steps):
            names = {cid: c["name"] for cid, c in self.engine.champs.items()}
            self.tick_live(demo.fake_live(time.time() - self.demo_game_t0, names))


# ---------- web server ----------

def make_handler(app):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=paths.WEB_DIR, **kw)

        def log_message(self, *a):
            pass

        def _json(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/api/state"):
                return self._json(app.snapshot())
            if self.path.startswith("/api/champs"):
                return self._json(app.champs_json())
            if self.path.startswith("/api/items"):
                v = app.pack["version"]
                return self._json([dict(it, img=f"{DDRAGON}/cdn/{v}/img/item/{it['id']}.png") for it in app.pack.get("items", [])])
            if self.path.startswith("/api/log"):
                try:
                    with open(paths.LOG_FILE, encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()[-150:]
                except OSError:
                    lines = []
                return self._json({"pid": os.getpid(), "log_file": paths.LOG_FILE, "lines": lines})
            return super().do_GET()

        def do_POST(self):
            if self.path == "/api/demo/start":
                app.start_demo()
            elif self.path == "/api/demo/stop":
                app.stop_demo()
            elif self.path == "/api/quit":
                self._json({"ok": True})
                threading.Timer(0.3, lambda: os._exit(0)).start()
                return
            return self._json({"ok": True})

    return Handler


PORTS = (47800, 47801, 47802)


class Server(ThreadingHTTPServer):
    allow_reuse_address = False  # on Windows, reuse would let two PICKBANS share a port


def running_instance():
    """URL of a PICKBANS that's already running, if any."""
    for port in PORTS:
        try:
            s = net.get_json(f"http://127.0.0.1:{port}/api/state", timeout=1)
            if "seq" in s and "patch" in s:
                return f"http://127.0.0.1:{port}/"
        except Exception:
            continue
    return None


def start_server(port=None):
    for p in ([port] if port else list(PORTS) + [0]):
        try:
            return Server(("127.0.0.1", p), None)
        except OSError:
            continue


def open_window(url):
    """A clean app-style window via Edge (always on Windows 10/11); fallback to the default browser."""
    candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        shutil.which("msedge") or "",
    ]
    edge = next((c for c in candidates if c and os.path.exists(c)), None)
    if edge:
        profile_dir = os.path.join(paths.USER_DIR, "window")
        # keep polling at full speed even when minimized / behind League
        subprocess.Popen([edge, f"--app={url}", "--window-size=520,980", f"--user-data-dir={profile_dir}",
                          "--no-first-run", "--no-default-browser-check", "--disable-features=Translate",
                          "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                          "--disable-backgrounding-occluded-windows"])
        return True
    webbrowser.open(url)
    return True


def main():
    ap = argparse.ArgumentParser(prog="pickbans")
    ap.add_argument("--demo", action="store_true", help="start with a scripted fake champ select")
    ap.add_argument("--no-window", action="store_true", help="don't open a window (dev)")
    ap.add_argument("--port", type=int, help="force a port and skip the already-running check (dev)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(process)d %(name)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(paths.LOG_FILE, encoding="utf-8")] +
                                 ([logging.StreamHandler()] if sys.stdout else []), force=True)
    if not args.port:
        existing = running_instance()
        if existing:
            log.info("already running on %s — just opening its window", existing)
            if not args.no_window:
                open_window(existing)
            return
    app = App()
    server = start_server(args.port)
    server.RequestHandlerClass = make_handler(app)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    log.info("PICKBANS %s on %s (exe: %s)", __version__, url, sys.executable)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if args.demo:
        app.start_demo()
    threading.Thread(target=app.loop, daemon=True).start()

    # Quit when the window stops polling. (Can't watch the Edge process: it relaunches itself on first run.)
    has_window = not args.no_window and open_window(url)
    started = time.time()
    try:
        while True:
            time.sleep(1)
            if not has_window:
                continue
            polled = app.last_poll > started
            idle = time.time() - app.last_poll
            if (polled and idle > 20) or (not polled and time.time() - started > 120):
                log.info("window closed — quitting")
                break
    except KeyboardInterrupt:
        pass
    server.shutdown()


if __name__ == "__main__":
    main()
