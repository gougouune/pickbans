"""Recs in a mode with no assigned lanes (Swiftplay, blind pick): from the WHOLE pool.  python tools/try_swiftplay.py
Uses your real profile if League is open, otherwise a made-up multi-role one."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pickbans import marks, paths  # noqa: E402

tmp = tempfile.mkdtemp(prefix="pickbans_swift_")
marks.MARKS_FILE = os.path.join(tmp, "marks.json")
paths.HISTORY_FILE = os.path.join(tmp, "history.json")

from pickbans import pool as poolmod  # noqa: E402
from pickbans.draft import parse_session  # noqa: E402
from pickbans.engine import Engine  # noqa: E402
from pickbans.lcu import LCU, find_credentials  # noqa: E402
from pickbans.pack import load_pack  # noqa: E402
from pickbans.profile import Profile  # noqa: E402

poolmod.POOL_FILE = os.path.join(tmp, "pool.json")
e = Engine(load_pack())
key = lambda c: e.champs[c]["key"]
creds = find_credentials()
if creds:
    prof = Profile.from_lcu(LCU(*creds), e.key_to_id)
    print("real profile:", prof.name, "| swiftplay games count toward what you play")
else:
    prof = Profile()
    prof.games = {"Pantheon": {"games": 4, "wins": 2, "roles": {}}, "Ekko": {"games": 3, "wins": 2, "roles": {"JUNGLE": 3}},
                  "Naafiri": {"games": 6, "wins": 3, "roles": {"MIDDLE": 6}}, "Pyke": {"games": 5, "wins": 2, "roles": {"UTILITY": 5}}}
    prof.mastery = {"Pantheon": 50000, "Pyke": 200000}
pool = poolmod.build(e, prof, poolmod.load_overrides())
print("pool:", {r: [x["id"] for x in l] for r, l in pool["roles"].items() if l})


def session(my_champ=0, actions=True):
    team = lambda base, mine: [{"cellId": base + i, "assignedPosition": "", "championId": 0, "championPickIntent": 0} for i in range(5)]
    s = {"gameId": 777, "localPlayerCellId": 2, "timer": {"phase": "BAN_PICK"}, "myTeam": team(0, True), "theirTeam": team(5, False),
         "actions": [[{"actorCellId": 2, "type": "pick", "championId": 0, "completed": False, "isInProgress": True}]] if actions else [],
         "bans": {"myTeamBans": [], "theirTeamBans": []}}
    if my_champ:
        s["myTeam"][2]["championId"] = key(my_champ)
        if actions:
            s["actions"] = [[{"actorCellId": 2, "type": "pick", "championId": key(my_champ), "completed": True, "isInProgress": False}]]
    return s


for title, sess in [("1) Swiftplay-like, nothing picked yet (no actions)", session(0, False)),
                    ("2) you picked Pantheon (no actions: champion only on myTeam)", session("Pantheon", False)),
                    ("3) blind pick with actions but no lanes, hovering", session(0, True))]:
    d = parse_session(sess, e.key_to_id)
    me = next(a for a in d["allies"] if a["is_me"])
    r = e.recommend(d, prof, pool)
    print(f"\n{title}\n   my champ: {me['champ']} | any_role: {r['any_role']} | my lane: {r['my_lane']} | pool {r['pool_available']}/{r['pool_size']}")
    print("   picks:", [(x["id"], x["grade"], x["reasons"][:1]) for x in r["picks"]])
    print("   counter/try/cheese/bans:", len(r["counter"]), len(r["try"]), len(r["cheese"]), len(r["bans"]), "(must all be 0 without lanes)")
    assert r["any_role"] and not (r["counter"] or r["try"] or r["cheese"] or r["bans"])
    if me["champ"]:
        b = r["my_pick"]["build"]
        print("   runes/build for", me["champ"], "->", bool(b), "lane used:", b and b["role"])
        assert b and me["champ"] == "Pantheon"
assert e.recommend(parse_session(session(0, False), e.key_to_id), prof, pool)["picks"], "no picks at all"
print("\nAll good.")
