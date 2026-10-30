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
# The tool is aimed at Gold and below, so lane stats come from this rank.
# (OP.GG only gives full matchup tables for its default bracket, Emerald+; per-rank head-to-heads override those.)
RANK = sys.argv[sys.argv.index("--rank") + 1] if "--rank" in sys.argv else "gold"

version = latest_version()
roster = fetch_roster(version)
by_name = {norm(c["name"]): cid for cid, c in roster.items()}
by_name.update({norm(cid): cid for cid in roster})
key_to_id = {c["key"]: cid for cid, c in roster.items()}

old = {}
PREV = None
FILL_ONLY = False
MIN_PAIR_GAMES = 200   # below this, a new-patch matchup is noise: use last patch's number instead
if os.path.exists(OUT) and "--fresh" not in sys.argv:
    with open(OUT, encoding="utf-8") as f:
        old = json.load(f)
    if old.get("version") != version:
        PREV = old  # previous patch: fills the gaps while the new patch has few games
        old = {}

# --max-age-days N: within the same patch, only refetch everything when the stats are older than N days
if "--max-age-days" in sys.argv and old:
    days = float(sys.argv[sys.argv.index("--max-age-days") + 1])
    if old.get("thin"):
        days = min(days, 1)  # early in a patch: refresh daily until the new numbers are solid
    age = (time.time() - old.get("fetched_at", 0)) / 86400
    if old.get("rank") != RANK:
        old = dict(old, fetched_at=0)  # rank changed: redo everything
    age = (time.time() - old.get("fetched_at", 0)) / 86400
    missing = [(r, c) for r, lane in old.get("meta", {}).items() for c in lane
               if c not in old.get("matchups", {}).get(r, {}) or c not in old.get("rank_done", {}).get(r, [])
               or c not in old.get("builds", {}).get(r, {})]
    if age < days and not missing:
        print(f"Stats are {age:.1f} days old (< {days}) for patch {version}: nothing to do")
        sys.exit(0)
    if age >= days:
        PREV = old  # refetch everything, but keep these numbers wherever the fresh ones are thin
        old = {}
    else:
        FILL_ONLY = True  # same patch, recent: keep tiers as they are, just fetch the missing tables

print(f"Patch {version}: lane tiers…")
meta = old["meta"] if FILL_ONLY else opgg.lane_meta(lambda n: by_name.get(norm(n)))
fetched_at = old["fetched_at"] if FILL_ONLY else int(time.time())
matchups = old.get("matchups", {})
jobs = [(role, cid) for role, champs in meta.items() for cid in champs if cid not in matchups.get(role, {})]
print(f"{sum(len(v) for v in meta.values())} champion/lane combos, {len(jobs)} matchup tables to fetch")


def fetch(job):
    role, cid = job
    try:
        return role, cid, opgg.matchup_table(roster[cid], role, opgg.safe_opponent(meta[role], roster, cid), key_to_id)
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
                json.dump({"version": version, "fetched_at": fetched_at, "source": "op.gg",
                           "meta": meta, "matchups": matchups}, f)

# ---- pass 2: the same lanes at the target rank (stats + a few head-to-heads each) ----
base_meta = old.get("base_meta") if FILL_ONLY else None
base_meta = base_meta or json.loads(json.dumps(meta))   # Emerald+ lane list, kept as fallback
matchups_rank = old.get("matchups_rank", {}) if FILL_ONLY else {}
rank_done = old.get("rank_done", {}) if FILL_ONLY else {}
builds = old.get("builds", {}) if FILL_ONLY else {}
rank_meta = json.loads(json.dumps(old["meta"])) if FILL_ONLY else json.loads(json.dumps(base_meta))
jobs2 = [(role, cid) for role, champs in base_meta.items() for cid in champs
         if cid not in rank_done.get(role, []) or cid not in builds.get(role, {})]
print(f"Rank '{RANK}': {len(jobs2)} champion/lane stats to fetch")


def fetch_rank(job):
    role, cid = job
    try:
        return role, cid, opgg.rank_stats(roster[cid], role, RANK, key_to_id)
    except Exception as e:
        return role, cid, e


def save():
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"version": version, "fetched_at": fetched_at, "source": "op.gg", "rank": RANK,
                   "meta": rank_meta, "base_meta": base_meta, "matchups": matchups,
                   "matchups_rank": matchups_rank, "rank_done": rank_done, "builds": builds}, f)


done2 = failed2 = 0
with ThreadPoolExecutor(3) as pool:
    for role, cid, res in pool.map(fetch_rank, jobs2):
        if isinstance(res, Exception):
            failed2 += 1
            print("  FAILED", res)
        else:
            stat, pairs, build = res
            builds.setdefault(role, {})[cid] = build
            if stat and stat["play"] >= 500:      # enough games at this rank to trust the lane numbers
                rank_meta[role][cid] = stat
            if pairs:
                matchups_rank.setdefault(role, {})[cid] = pairs
            if cid not in rank_done.setdefault(role, []):
                rank_done[role].append(cid)
        done2 += 1
        if done2 % 25 == 0:
            print(f"  {done2}/{len(jobs2)}")
            save()
# ---- early in a patch OP.GG has few games: keep last patch's numbers where the new ones are too thin ----
THIN = old.get("thin", False) if FILL_ONLY else False
if PREV:
    def merge_tables(new, prev_tables):
        kept = total = 0
        for role, champs in prev_tables.items():
            for cid, table in champs.items():
                cur = new.setdefault(role, {}).setdefault(cid, {})
                for opp, (games, wins) in table.items():
                    total += 1
                    if cur.get(opp, [0, 0])[0] < MIN_PAIR_GAMES:
                        cur[opp] = [games, wins]
                        kept += 1
        return kept, total

    def merge_meta(new, prev_meta):
        kept = 0
        for role, champs in prev_meta.items():
            for cid, st in champs.items():
                cur = new.setdefault(role, {}).get(cid)
                if not cur or cur.get("play", 0) < 0.3 * st.get("play", 0):
                    new[role][cid] = st
                    kept += 1
        return kept

    k1, t1 = merge_tables(matchups, PREV.get("matchups", {}))
    k2, _ = merge_tables(matchups_rank, PREV.get("matchups_rank", {}))
    k3 = merge_meta(rank_meta, PREV.get("meta", {}))
    for role, champs in PREV.get("builds", {}).items():  # too few games on the new patch: keep the last build
        for cid, b in champs.items():
            cur = builds.setdefault(role, {}).get(cid)
            if b and (not cur or cur.get("play", 0) < 50):
                builds[role][cid] = b
    THIN = t1 > 0 and k1 / t1 > 0.3
    print(f"New patch: kept {k1}/{t1} matchups, {k2} rank head-to-heads and {k3} lane stats from patch {PREV.get('version')}"
          f"{' (still thin: will refresh daily)' if THIN else ''}")


def save():  # noqa: F811  (final save also records whether the data is still thin)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"version": version, "fetched_at": fetched_at, "source": "op.gg", "rank": RANK, "thin": THIN,
                   "meta": rank_meta, "base_meta": base_meta, "matchups": matchups,
                   "matchups_rank": matchups_rank, "rank_done": rank_done, "builds": builds}, f)


save()
pairs = sum(len(t) for r in matchups.values() for t in r.values())
rpairs = sum(len(t) for r in matchups_rank.values() for t in r.values())
print(f"Saved {OUT}: {pairs} matchup pairs (Emerald+), {rpairs} head-to-heads at {RANK}, {failed + failed2} failed")
