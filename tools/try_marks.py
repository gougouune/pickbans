"""Marks (love / like / hate / ban) + "no leftovers from the previous game".  python tools/try_marks.py"""
import copy
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pickbans import marks, paths  # noqa: E402

tmp = tempfile.mkdtemp(prefix="pickbans_marks_")
marks.MARKS_FILE = os.path.join(tmp, "marks.json")      # never touch the real marks
paths.HISTORY_FILE = os.path.join(tmp, "history.json")

from pickbans import app as appmod, demo, pool as poolmod  # noqa: E402

appmod.HOME_CACHE = os.path.join(tmp, "home.json")
appmod.SETTINGS_FILE = os.path.join(tmp, "settings.json")
poolmod.POOL_FILE = os.path.join(tmp, "pool.json")

a = appmod.App()
a.demo_steps = None
key_of = lambda c: a.id_to_key[c]
a.profile = demo.demo_profile(key_of)
steps = [s for _, ph, s in demo.timeline(key_of) if s]
mid = steps[-6]                   # a pick-phase session
final = steps[-1]                 # FINALIZATION

# ---------- marks ----------
def recs():
    a.on_session(mid)
    return a.state["recs"]

base = recs()
print("base picks:", [r["id"] for r in base["picks"]], "| bans:", [b["id"] for b in base["bans"]])
a.mark("Soraka", "love")
pool_ids = [e["id"] for e in a.state["pool"]["roles"]["UTILITY"]]
print("1) love Soraka -> in pool:", "Soraka" in pool_ids, "| marks:", a.state["marks"])
a.mark("Rakan", "ban")
r = recs()
print("2) ban Rakan -> first ban:", r["bans"][0]["id"], r["bans"][0]["reasons"])
assert r["bans"][0]["id"] == "Rakan"
a.mark("Nami", "ban")   # a champion in my pool: never recommended, gone from the pool
r = recs()
print("   ban Nami (in my pool) -> picks:", [x["id"] for x in r["picks"]], "| try:", [x["id"] for x in r["try"]])
assert "Nami" not in [x["id"] for x in r["picks"]] and "Nami" not in [x["id"] for x in r["try"]]
assert "Nami" not in [e["id"] for e in a.state["pool"]["roles"]["UTILITY"]]
a.mark("Rell", "hate")
r = recs()
print("3) hate Rell -> bans:", [(b["id"], b["reasons"][0]) for b in r["bans"]])
assert any(b["id"] == "Rell" for b in r["bans"])
a.mark("Nami", "")
print("4) cleared Nami -> back in pool:", "Nami" in [e["id"] for e in a.state["pool"]["roles"]["UTILITY"]], "| marks:", a.state["marks"])

# ---------- hated champion warned in the assessment ----------
a.on_session(final)
trap_ids = [(t["id"], t.get("hate", False)) for t in a.state["assessment"]["traps"]]
print("5) assessment traps:", trap_ids)

# ---------- the bug: previous game's panels in the NEXT champ select ----------
a.set(status="assessment", live={"clock": "21:10"})          # we were in game
print("6) before next game: assessment =", bool(a.state.get("assessment")), "| live =", bool(a.state.get("live")))
nxt = copy.deepcopy(steps[0])                                # a fresh champ select (PLANNING)
nxt["gameId"] = 555
a.on_session(nxt)
print("   new champ select -> status:", a.state["status"], "| assessment:", a.state["assessment"], "| live:", a.state["live"], "| rune_import:", a.state.get("rune_import"))
assert a.state["assessment"] is None and a.state["live"] is None and a.state.get("rune_import") is None
print("All good.")
