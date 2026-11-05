"""Post-match breakdown on made-up games (shapes of the client's match-history API).  python tools/try_breakdown.py"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pickbans import breakdown, demo  # noqa: E402

detail, timeline, key = demo.fake_game(lambda c: {"Nami": 267}[c])
history = demo.fake_history_metrics()


def show(title, b):
    print(f"\n=== {title}")
    if not b:
        print("   (nothing: game couldn't be read)")
        return
    print(f"   {'WIN' if b['win'] else 'LOSS'} {b['k']}/{b['d']}/{b['a']}, {b['dur'] // 60} min, role {b['role']}, timeline: {b['has_timeline']}")
    for t in b["tiles"]:
        print(f"   tile  {t['label']:20} {t['value']}{'%' if t.get('pct') else ''}  (typical {t['bench']}{'%' if t.get('pct') else ''}, your avg {t['avg']}) -> {t['state']}")
    for f in b["findings"]:
        print(f"   {f['kind'].upper():4}  {f['title']}: {f['text']}")
    for p in b["phases"]:
        print(f"   phase {p['label']:6} cs/min {p['cs']}  deaths {p['deaths']}  wards {p['wards']}")
    for t in b["trend"]:
        print(f"   trend {t['label']:20} {t['before']} -> {t['now']}  {t['state']}")


full = breakdown.build(detail, timeline, key, "Nami", "UTILITY", history, 123)
show("full data (stats + timeline + 10 past games)", full)
assert full and any(f["title"] == "Not enough wards" for f in full["findings"])
assert any(f["title"] == "Too aggressive early" for f in full["findings"])

show("no timeline (client didn't give it)", breakdown.build(detail, None, key, "Nami", "UTILITY", history, 123))
show("no past games", breakdown.build(detail, timeline, key, "Nami", "UTILITY", [], 123))
show("garbage from the client", breakdown.build({"participants": [{"championId": 267}]}, {"frames": "nope"}, key, "Nami", "UTILITY", history, 1))
show("nothing at all", breakdown.build({}, None, key, "Nami", "UTILITY", history, 1))

# a good game: no complaints, some praise
good = copy.deepcopy(detail)
me = next(p for p in good["participants"] if p["participantId"] == 5)
me["stats"].update(kills=3, deaths=2, assists=18, visionScore=70, wardsPlaced=30, visionWardsBoughtInGame=7, win=True)
show("a clean support game", breakdown.build(good, None, key, "Nami", "UTILITY", history, 2))
print("\nAll good.")
