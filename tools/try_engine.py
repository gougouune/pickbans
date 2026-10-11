"""Print what the engine recommends at each step of the demo draft. python tools/try_engine.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pickbans import demo  # noqa: E402
from pickbans.assess import assess  # noqa: E402
from pickbans.draft import infer_roles, parse_session  # noqa: E402
from pickbans.engine import Engine  # noqa: E402
from pickbans.pack import load_pack  # noqa: E402

pack = load_pack()
eng = Engine(pack)
id_to_key = {cid: c["key"] for cid, c in pack["champions"].items()}
key_of = lambda cid: id_to_key[cid]
prof = demo.demo_profile(key_of)
name = lambda c: pack["champions"][c]["name"]
fmt = lambda rs: ", ".join(f"{name(r['id'])} {r['grade']}({r['score']})" for r in rs) or "-"

last = None
for t, phase, s in demo.timeline(key_of):
    if s is None:
        break
    d = parse_session(s, eng.key_to_id)
    infer_roles(d["enemies"], eng.role_rate)
    last = d
    r = eng.recommend(d, prof)
    en = [e["champ"] for e in d["enemies"] if e["champ"]]
    print(f"\n[{t:5.1f}s] {d['phase']} action={d['my_action']} bans={len(d['bans'])} enemies={en}")
    print("  comfy :", fmt(r["comfy"]))
    print("  ideal :", fmt(r["ideal"]))
    print("  counter:", fmt(r["counter"]), "| opp:", r["opponent"])
    print("  cheese:", fmt(r["cheese"]), [c["reasons"][0] for c in r["cheese"]])
    print("  bans  :", ", ".join(f"{name(b['id'])} ({b['reasons'][0]})" for b in r["bans"]))
    print("  missing:", [m["label"] for m in r["missing"] if m["missing"]], "| enemy:", r["enemy_tags"])
    if r["ideal"]:
        print("  why ideal #1:", r["ideal"][0]["reasons"], r["ideal"][0]["parts"])

print("\n=== ASSESSMENT")
import json  # noqa: E402
print(json.dumps(assess(eng, last, prof), indent=1))
