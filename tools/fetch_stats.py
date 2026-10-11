"""Pull real stats from OP.GG into tools/kb/stats.json (tiers per lane + every champion's matchup table).

Run once per patch, from the project root:  python tools/fetch_stats.py   (then python tools/build_pack.py)
~270 calls, 3 at a time, a few minutes. Resumable: re-running only fetches what's missing (use --fresh to redo all).
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pickbans import opgg  # noqa: E402
from pickbans.pack import fetch_roster, latest_version, norm  # noqa: E402

OUT = os.path.join(ROOT, "tools", "kb", "stats.json")

version = latest_version()
roster = fetch_roster(version)
by_name = {norm(c["name"]): cid for cid, c in roster.items()}
by_name.update({norm(cid): cid for cid in roster})
key_to_id = {c["key"]: cid for cid, c in roster.items()}

old = {}
if os.path.exists(OUT) and "--fresh" not in sys.argv:
    with open(OUT, encoding="utf-8") as f:
        old = json.load(f)
    if old.get("version") != version:
        old = {}

# --max-age-days N: within the same patch, only refetch everything when the stats are older than N days
if "--max-age-days" in sys.argv and old:
    days = float(sys.argv[sys.argv.index("--max-age-days") + 1])
    age = (time.time() - old.get("fetched_at", 0)) / 86400
    complete = sum(len(v) for v in old.get("matchups", {}).values()) >= 250
    if age < days and complete:
        print(f"Stats are {age:.1f} days old (< {days}) for patch {version}: nothing to do")
        sys.exit(0)
    if age >= days:
        old = {}

print(f"Patch {version}: lane tiers…")
meta = opgg.lane_meta(lambda n: by_name.get(norm(n)))
matchups = old.get("matchups", {})
jobs = [(role, cid) for role, champs in meta.items() for cid in champs if cid not in matchups.get(role, {})]
print(f"{sum(len(v) for v in meta.values())} champion/lane combos, {len(jobs)} matchup tables to fetch")


def fetch(job):
    role, cid = job
    other = next(c for c in meta[role] if c != cid)
    try:
        return role, cid, opgg.matchup_table(roster[cid], role, roster[other], key_to_id)
    except Exception as e:
        return role, cid, e


done = failed = 0
with ThreadPoolExecutor(3) as pool:
    for role, cid, table in pool.map(fetch, jobs):
        if isinstance(table, Exception):
            failed += 1
            print("  FAILED", table)
        else:
            matchups.setdefault(role, {})[cid] = table
        done += 1
        if done % 25 == 0 or done == len(jobs):
            print(f"  {done}/{len(jobs)}")
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump({"version": version, "fetched_at": int(time.time()), "source": "op.gg",
                           "meta": meta, "matchups": matchups}, f)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"version": version, "fetched_at": int(time.time()), "source": "op.gg", "meta": meta, "matchups": matchups}, f)
pairs = sum(len(t) for r in matchups.values() for t in r.values())
print(f"Saved {OUT}: {pairs} matchup pairs, {failed} failed")
