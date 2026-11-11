"""A whole evening of games against a fake League client: lobby -> champ select -> game -> end -> next champ select.
Catches the state bugs (leftovers from the previous game, screens stuck on 'analyzing'...).  python tools/try_lifecycle.py"""
import copy
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pickbans import marks, paths  # noqa: E402

tmp = tempfile.mkdtemp(prefix="pickbans_life_")
marks.MARKS_FILE = os.path.join(tmp, "marks.json")
paths.HISTORY_FILE = os.path.join(tmp, "history.json")

from pickbans import app as appmod, demo, live, pool as poolmod  # noqa: E402

appmod.HOME_CACHE = os.path.join(tmp, "home.json")
appmod.SETTINGS_FILE = os.path.join(tmp, "settings.json")
appmod.LAST_GAME_FILE = os.path.join(tmp, "last_game.json")
poolmod.POOL_FILE = os.path.join(tmp, "pool.json")
REAL_SLEEP = time.sleep
appmod.time.sleep = lambda s: None            # the loop's pauses don't matter here

a = appmod.App()
key = lambda c: a.id_to_key[c]
a.profile = demo.demo_profile(key)
a.profile_stale = False
sessions = [s for _, ph, s in demo.timeline(key) if s]
locked_session, planning = sessions[-1], sessions[0]


class FakeLCU:
    def __init__(self):
        self.phase_v, self.sess, self.history, self.details = "None", None, [], {}
        self.queue = {"id": 420, "gameMode": "CLASSIC", "mapId": 11}
        self.imported = []

    def phase(self): return self.phase_v
    def session(self): return self.sess
    def pickable_ids(self): return []
    def match_history(self, count=60): return self.history
    def import_runes(self, runes): self.imported.append(runes); return True, "ok"

    def get(self, path, timeout=5):
        if path.endswith("gameflow/v1/session"):
            return {"gameData": {"queue": self.queue}}
        if "/lol-match-history/v1/games/" in path:
            return self.details.get(int(path.rsplit("/", 1)[1]))
        return None


lcu = FakeLCU()
a.lcu = lcu
names = {c: v["name"] for c, v in a.engine.champs.items()}
mine = [i["id"] for k in ("core", "boots") for i in (a.engine.build("Nami", "UTILITY") or {}).get(k, [])]
game_clock = [600]
live.fetch = lambda: demo.fake_live((game_clock[0] - 60) / 15, names, mine) if game_clock[0] else None


def go(phase, sess=None):
    lcu.phase_v, lcu.sess = phase, sess
    a.tick_client()
    return a.state


def session_of(base, gid):
    s = copy.deepcopy(base)
    s["gameId"] = gid
    return s


def wait_analysis():
    for _ in range(100):
        if not a.state.get("analyzing"):
            return
        REAL_SLEEP(0.05)


def check(label, ok, extra=""):
    print(f"   {'ok ' if ok else 'BUG'} {label} {extra}")
    return ok


bugs = 0
# ---------------------------------------------------------------- game 1: a normal ranked game
print("GAME 1 (ranked, lanes assigned)")
go("Lobby")
s = go("ChampSelect", session_of(planning, 111))
bugs += not check("champ select shows recs", s["status"] == "champ_select" and bool(s["recs"]))
s = go("ChampSelect", session_of(locked_session, 111))
bugs += not check("draft locked -> assessment ready", bool(s["assessment"]))
go("GameStart")
game_clock[0] = 0
go("GameStart")
game_clock[0] = 600
s = go("InProgress")
bugs += not check("in game: live panel", s["status"] == "assessment" and bool(s["live"]))
detail, tl, ck = demo.fake_game(key)
detail["gameId"] = 111
lcu.details[111] = detail
lcu.history = [{"gameId": 111, "gameCreation": int(time.time() * 1000) - 1800000, "gameDuration": 1740, "mapId": 11,
                "participants": [{"championId": ck}]}]
s = go("WaitingForStats")
bugs += not check("game over -> post-match screen", s["status"] == "postgame" and a.state.get("analyzing") is not None)
wait_analysis()
bugs += not check("breakdown arrived", bool(a.state.get("last_game")) and not a.state.get("analyzing"))
s = go("Lobby")
bugs += not check("back in lobby -> home, game panels cleared", s["status"] == "idle" and not s["live"] and not s["assessment"])

# ---------------------------------------------------------------- game 2: the client reports gameId 0 (some modes do)
print("GAME 2 (client says gameId = 0)")
s = go("ChampSelect", session_of(planning, 0))
bugs += not check("new champ select starts clean", s["status"] == "champ_select" and not s["assessment"] and not s["live"])
s = go("ChampSelect", session_of(locked_session, 0))
bugs += not check("locked draft -> assessment", bool(s["assessment"]))
go("InProgress")
go("WaitingForStats")
wait_analysis()
go("Lobby")
# game 3 right after, again gameId 0: the OLD panels must not come back
s = go("ChampSelect", session_of(planning, 0))
bugs += not check("3rd champ select (gameId 0 again): no leftovers", not s["assessment"] and not s["live"] and s["rune_import"] is None,
                  f"assessment={bool(s['assessment'])} live={bool(s['live'])} rune_import={s['rune_import']}")

# ---------------------------------------------------------------- practice tool: no match history, no breakdown
print("PRACTICE TOOL")
go("Lobby")
lcu.queue = {"id": 3140, "gameMode": "PRACTICETOOL", "mapId": 11}
lcu.history = []
go("ChampSelect", session_of(locked_session, 0))
go("InProgress")
print("   (mode the app saw at game start:", a.game_mode, "| in_game:", a.in_game, ")")
s = go("EndOfGame")
t0 = time.time()
wait_analysis()
bugs += not check("no 'Game over / Analyzing…' screen for a game that has no history", s["status"] != "postgame" or not a.state.get("analyzing"),
                  f"(status={s['status']}, analyzing={a.state.get('analyzing')})")
s = go("Lobby")
bugs += not check("then back to the home screen", s["status"] == "idle")

# ---------------------------------------------------------------- swiftplay: no lanes at all
print("SWIFTPLAY (no assigned lanes)")
lcu.queue = {"id": 480, "gameMode": "SWIFTPLAY", "mapId": 11}
sw = copy.deepcopy(locked_session)
for side in ("myTeam", "theirTeam"):
    for p in sw[side]:
        p["assignedPosition"] = ""
sw["gameId"] = 0
s = go("ChampSelect", session_of(sw, 0))
bugs += not check("recs from the whole pool", s["recs"]["any_role"] and bool(s["recs"]["picks"]))
ass = s["assessment"]
rows = [m for m in (ass or {}).get("matchups", []) if m.get("ally") and m.get("enemy")]
bugs += not check("no made-up lane matchups when nobody has a lane", not rows, f"({len(rows)} fake rows)")

print(f"\n{'ALL GOOD' if not bugs else str(bugs) + ' BUG(S) FOUND'}")
sys.exit(1 if bugs else 0)
