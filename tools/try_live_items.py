"""Dynamic item recommendations from what enemies really own / their kills.  python tools/try_live_items.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pickbans.engine import Engine  # noqa: E402
from pickbans.pack import load_pack  # noqa: E402

e = Engine(load_pack())
E = lambda champ, items=(), k=0, d=0: {"champ": champ, "items": [str(i) for i in items], "kills": k, "deaths": d}
BLOODTHIRSTER, THORNMAIL, SUNFIRE, WARMOGS, RANDUINS = 3072, 3075, 3068, 3083, 3143
FROZEN, JAKSHO, KRAKEN, IE, LIANDRY, RABADON = 3110, 6665, 6672, 3031, 6653, 3089
TEAM = ["Garen", "Vi", "Swain", "Jinx", "Lulu"]


def show(title, me, team, live, owned=()):
    items = e.situational(me, team, e.build(me, e.champs[me]["positions"][0]), live=live, owned=owned)
    print(f"\n{title}  [{me}: {e.item_class(me)}]")
    for x in items:
        print(f"   - {x['name']}{' (EARLIER: already in your build)' if x.get('early') else ''}: {x['why']}" + (f"   <- {x['live']}" if x.get("live") else ""))
    return items


# 1) the classic: nothing special at the start, then Swain buys a lifesteal item
start = [E(c) for c in TEAM]
a = show("1a) start of the game", "Naafiri", TEAM, start)
later = [E("Swain", [BLOODTHIRSTER])] + [E(c) for c in TEAM if c != "Swain"]
b = show("1b) Swain buys Bloodthirster", "Naafiri", TEAM, later)
assert any(x["id"] == "6609" for x in b) and not any(x["id"] == "6609" for x in a) or any(x["trigger"] == "heal" for x in b)
t = show("1c) same, but I'm a tank (Maokai)", "Maokai", TEAM, later)
print("   (Thornmail is in Maokai's normal build: it should say 'earlier', not vanish)")

# 2) heavy armor -> penetration for an ADC / assassin
armor = [E("Malphite", [THORNMAIL, SUNFIRE]), E("Sejuani", [THORNMAIL, SUNFIRE]), E("Galio"), E("Caitlyn"), E("Nautilus")]
c = show("2) enemies stack armor (Jinx)", "Jinx", [x["champ"] for x in armor], armor)
assert any(x["trigger"] == "armor_stack" for x in c)

# 3) magic resist stacking -> mage
mr = [E("Maokai", [JAKSHO, 3156]), E("Galio", [3102, 3156, 6665]), E("Zed"), E("Caitlyn"), E("Leona")]
d = show("3) enemies stack magic resist (Veigar)", "Veigar", [x["champ"] for x in mr], mr)

# 4) a fed enemy AD champion
fed = [E("Zed", [3142, 3814], 8, 1)] + [E(c) for c in ["Darius", "Vi", "Jinx", "Thresh"]]
f = show("4) Zed is 8/1 (Veigar)", "Veigar", [x["champ"] for x in fed], fed)
assert any("fed" in (x.get("live") or "") for x in f)

# 5) real items beat the champion-based guess: Zed/Darius look AD, but they build AP
ap = [E("Zed", [RABADON, LIANDRY]), E("Darius", [RABADON, 3116, 6655]), E("Vi", [LIANDRY, 3157]), E("Jinx"), E("Thresh")]
static_only = show("5a) AD champions, no item info yet", "Veigar", [x["champ"] for x in ap], [E(x["champ"]) for x in ap])
live_mix = show("5b) same champions, but their ITEMS are AP", "Veigar", [x["champ"] for x in ap], ap)
print("   ad_heavy dropped once items say AP:", not any(x["trigger"] == "ad_heavy" for x in live_mix))

# 6) what I already own is never recommended again
o = show("6) Naafiri already owns Chempunk Chainsword", "Naafiri", TEAM, later, owned=["6609"])
assert not any(x["id"] == "6609" for x in o)

print("\nAll good.")
