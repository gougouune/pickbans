"""Offline check of the home screen data: fake client → profile → opponent backfill → home payload.
python tools/try_home.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pickbans import paths  # noqa: E402

paths.HISTORY_FILE = os.path.join(os.environ.get("TEMP", "."), "pickbans_try_history.json")
if os.path.exists(paths.HISTORY_FILE):
    os.remove(paths.HISTORY_FILE)

from pickbans.engine import Engine  # noqa: E402
from pickbans.home import build_home  # noqa: E402
from pickbans.pack import load_pack  # noqa: E402
from pickbans.profile import Profile  # noqa: E402

eng = Engine(load_pack())
key = {cid: c["key"] for cid, c in eng.champs.items()}

GAMES = [  # (my champ, win, my team, enemy team, mode)
    ("Pyke", True, ["Garen", "Vi", "Ahri", "Jinx", "Pyke"], ["Jax", "Aatrox", "Akali", "Quinn", "Zilean"], "CLASSIC"),
    ("Pyke", False, ["Darius", "LeeSin", "Yone", "Caitlyn", "Pyke"], ["Malphite", "Sejuani", "Galio", "Jhin", "Rell"], "CLASSIC"),
    ("Veigar", True, ["Sett", "Amumu", "Veigar", "Ezreal", "Lulu"], ["Teemo", "Warwick", "Zed", "Ashe", "Leona"], "CLASSIC"),
    ("Pantheon", True, ["Pantheon", "Lux", "Jhin", "Sona", "Zed"], ["Ahri", "Ashe", "Nami", "Garen", "Yasuo"], "ARAM"),
]


class FakeLCU:
    def summoner(self):
        return {"gameName": "tester"}

    def mastery(self):
        return [{"championId": key["Pyke"], "championPoints": 90000}, {"championId": key["Veigar"], "championPoints": 40000}]

    def owned_ids(self):
        return []

    def match_history(self, count=60):
        return [{"gameId": 100 + i, "gameMode": mode, "mapId": 11 if mode == "CLASSIC" else 12, "gameCreation": (1760000000 - i * 4000) * 1000,
                 "participants": [{"championId": key[me], "stats": {"win": win, "kills": 3, "deaths": 4, "assists": 11},
                                   "timeline": {"lane": "NONE", "role": "NONE"}}]}
                for i, (me, win, _, _, mode) in enumerate(GAMES)]

    def get(self, path, timeout=5):
        i = int(path.rsplit("/", 1)[1]) - 100
        me, win, mine, theirs, _ = GAMES[i]
        return {"participants": [{"teamId": 100, "championId": key[c], "stats": {"win": win}} for c in mine] +
                                [{"teamId": 200, "championId": key[c], "stats": {"win": not win}} for c in theirs]}


p = Profile.from_lcu(FakeLCU(), eng.key_to_id)
print("recent (ARAM must be gone):", [(r["champ"], r["win"]) for r in p.recent])
print("backfilled:", p.backfill(FakeLCU(), eng))
print("history:", [(h["me"], h["role"], "vs", h["vs"], h["win"]) for h in p.history])
home = build_home(eng, p)
print("pool:", [(x["id"], x["role"], x["tier"], x["wr"]) for x in home["pool"]])
print("notebook Pyke:", json.dumps(home["notebook"].get("Pyke"), indent=1)[:900])
print("facts:")
for f in home["facts"][:12]:
    print("  ", f.get("text") or f"QUIZ {f['ids']} -> {f['winner']} {f['wr']}%")
