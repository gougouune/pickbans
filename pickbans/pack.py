"""Data pack: everything PICKBANS knows about League.

The pack is built from tools/kb/*.txt by tools/build_pack.py and shipped inside the app.
At startup the app checks Riot's Data Dragon: on a new patch it refreshes the roster and
adds any new champion with traits guessed from Riot's own tags, so it never breaks.
"""
import json
import logging
import os
import re
import time

from . import net, paths

DDRAGON = "https://ddragon.leagueoflegends.com"
# Where the published data pack lives (built by .github/workflows/update-pack.yml, pushed to the `data` branch).
# Every app checks manifest.json at launch and downloads pack.json only when it is newer.
REMOTE_BASE = "https://raw.githubusercontent.com/gougouune/pickbans/data/"

ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
TRAITS = ["EN", "PE", "CC", "PO", "DI", "FR", "SU", "BU", "DP", "TS", "WC", "MO", "SP", "GL", "PI"]

log = logging.getLogger("pickbans.pack")


def norm(name):
    return re.sub(r"[^a-z]", "", name.lower())


# ---------- building from the knowledge base text files ----------

def parse_kb(kb_dir):
    champs, notes, meta, cheese = {}, {}, {}, []
    for line in _lines(os.path.join(kb_dir, "champs.txt")):
        cid, pos, dmg, rng, styles, traits, scaling, diff = [p.strip() for p in line.split("|")]
        champs[cid] = {
            "positions": pos.split(","),
            "dmg": dmg,
            "range": rng,
            "styles": [s.strip() for s in styles.split(",")],
            "traits": {t[:2]: int(t[2:]) for t in traits.split()},
            "scaling": scaling,
            "difficulty": int(diff),
        }
    for fname in sorted(f for f in os.listdir(kb_dir) if f.startswith("notes_")):
        for line in _lines(os.path.join(kb_dir, fname)):
            parts = [p.strip() for p in line.split("|")]
            entry = {"weak_vs": [w.strip() for w in parts[1].split(",") if w.strip()]}
            for p in parts[2:]:
                key, _, text = p.partition(":")
                entry[key.strip()] = text.strip()
            notes[parts[0]] = entry
    for line in _lines(os.path.join(kb_dir, "meta.txt")):
        head, _, names = line.partition(":")
        role, tier = head.split()
        for n in names.split(","):
            meta.setdefault(role, {})[n.strip()] = tier
    for line in _lines(os.path.join(kb_dir, "cheese.txt")):
        cid, role, trigger, why = [p.strip() for p in line.split("|")]
        cheese.append({"id": cid, "role": role, "trigger": trigger, "why": why})
    return champs, notes, meta, cheese


def _lines(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                yield line


def build_pack(kb_dir):
    """Merge the knowledge base with Riot's live roster into one pack dict."""
    version = latest_version()
    roster = fetch_roster(version)
    kb_champs, notes, meta, cheese = parse_kb(kb_dir)
    by_norm = {norm(cid): cid for cid in roster}
    by_norm.update({norm(c["name"]): cid for cid, c in roster.items()})

    def resolve(name):
        return by_norm.get(norm(name))

    champions = {}
    for cid, riot in roster.items():
        kb = kb_champs.get(cid) or guess_from_riot(riot)
        n = notes.get(cid, {})
        champions[cid] = {
            **riot,
            **kb,
            "weak_vs": [r for r in (resolve(w) for w in n.get("weak_vs", [])) if r],
            "play": n.get("play", ""),
            "vs": n.get("vs", ""),
            "watch": n.get("watch", ""),
            "guessed": cid not in kb_champs,
        }
    fixed_meta = {role: {resolve(k): v for k, v in tiers.items() if resolve(k)} for role, tiers in meta.items()}
    fixed_cheese = [dict(c, id=resolve(c["id"])) for c in cheese if resolve(c["id"])]
    unknown = [n for n in list(kb_champs) + list(notes) if n not in roster]
    if unknown:
        log.warning("KB entries not in Riot roster: %s", unknown)
    pack = {
        "version": version,
        "built_at": int(time.time()),
        "meta_source": "baseline",
        "champions": champions,
        "meta": fixed_meta,
        "cheese": fixed_cheese,
        "stats": {},
        "matchups": {},
    }
    stats_file = os.path.join(kb_dir, "stats.json")
    if os.path.exists(stats_file):  # real stats from tools/fetch_stats.py
        with open(stats_file, encoding="utf-8") as f:
            s = json.load(f)
        pack.update(stats=s["meta"], matchups=s["matchups"], meta_source=s.get("source", "op.gg"),
                    stats_version=s["version"], stats_at=s["fetched_at"],
                    matchups_version=s["version"], matchups_at=s["fetched_at"],
                    matchups_rank=s.get("matchups_rank", {}), stats_rank=s.get("rank"))
    return pack


# ---------- Riot Data Dragon ----------

def latest_version():
    return net.get_json(f"{DDRAGON}/api/versions.json")[0]


def fetch_roster(version):
    data = net.get_json(f"{DDRAGON}/cdn/{version}/data/en_US/champion.json")["data"]
    return {
        cid: {
            "id": cid,
            "key": int(c["key"]),
            "name": c["name"],
            "title": c["title"],
            "tags": c["tags"],
            "info": c["info"],
            "melee": c["stats"]["attackrange"] < 300,
        }
        for cid, c in data.items()
    }


_TAG_TRAITS = {
    "Tank": {"FR": 3, "EN": 2, "CC": 2},
    "Fighter": {"FR": 2, "DP": 2, "DI": 1},
    "Assassin": {"BU": 3, "MO": 2},
    "Mage": {"BU": 2, "PO": 1, "WC": 2, "CC": 1},
    "Marksman": {"DP": 3, "WC": 1},
    "Support": {"SU": 2, "PE": 2, "CC": 1},
}
_TAG_POS = {
    "Marksman": ["BOTTOM"], "Support": ["UTILITY"], "Mage": ["MIDDLE"],
    "Assassin": ["MIDDLE", "JUNGLE"], "Fighter": ["TOP", "JUNGLE"], "Tank": ["TOP", "UTILITY"],
}
_TAG_STYLE = {
    "Tank": "Tank", "Fighter": "Bruiser", "Assassin": "Assassin",
    "Mage": "Mage", "Marksman": "Marksman", "Support": "Support",
}


def guess_from_riot(riot):
    """Best-effort traits for a champion the knowledge base doesn't cover yet (brand-new release)."""
    traits = {}
    for tag in riot["tags"]:
        for k, v in _TAG_TRAITS.get(tag, {}).items():
            traits[k] = max(traits.get(k, 0), v)
    positions = []
    for tag in riot["tags"]:
        positions += [p for p in _TAG_POS.get(tag, []) if p not in positions]
    info = riot["info"]
    return {
        "positions": positions or ["MIDDLE"],
        "dmg": "AP" if info["magic"] > info["attack"] else "AD",
        "range": "M" if riot["melee"] else "R",
        "styles": [_TAG_STYLE[t] for t in riot["tags"] if t in _TAG_STYLE],
        "traits": traits,
        "scaling": "M",
        "difficulty": 3 if info["difficulty"] >= 7 else 2 if info["difficulty"] >= 4 else 1,
    }


# ---------- loading + auto-update at runtime ----------

def load_pack():
    """Newest of: user copy (auto-updated) vs bundled copy."""
    candidates = []
    for p in (paths.USER_PACK, paths.BUNDLED_PACK):
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                candidates.append(json.load(f))
    if not candidates:
        raise RuntimeError("No data pack found. Run tools/build_pack.py")
    return max(candidates, key=lambda pk: (_vkey(pk["version"]), pk["built_at"]))


def fetch_remote(pack):
    """Download the published pack if it's newer than ours. Returns (pack, manifest or None)."""
    manifest = net.get_json(REMOTE_BASE + "manifest.json", timeout=6)
    newer = (_vkey(manifest["version"]), manifest["built_at"]) > (_vkey(pack["version"]), pack["built_at"])
    if newer:
        remote = net.get_json(REMOTE_BASE + "pack.json", timeout=30)
        if len(remote.get("champions", {})) >= 150 and remote.get("stats"):
            _save(remote)
            return remote, manifest
    return pack, manifest


def auto_update(pack):
    """Runs at every launch. Returns (pack, message, manifest). Never raises: offline just keeps the current pack.

    1. published pack (stats + matchups + texts) if newer  2. Riot roster if a patch dropped before the pack did."""
    manifest = None
    got_remote = False
    try:
        new, manifest = fetch_remote(pack)
        got_remote = new is not pack
        pack = new
    except Exception as e:  # no internet, GitHub down, pack not published yet
        log.info("no published pack: %s", e)
    try:
        version = latest_version()
        if _vkey(version) <= _vkey(pack["version"]):
            return pack, ("Downloaded new data" if got_remote else "Data up to date") + f" (patch {pack['version']})", manifest
        roster = fetch_roster(version)
        added = []
        for cid, riot in roster.items():
            if cid in pack["champions"]:
                pack["champions"][cid].update(riot)
            else:
                pack["champions"][cid] = {**riot, **guess_from_riot(riot), "weak_vs": [],
                                          "play": "", "vs": "", "watch": "", "guessed": True}
                added.append(riot["name"])
        pack["version"] = version  # built_at stays: the published pack for this patch must still win later
        _save(pack)
        msg = f"Updated to patch {version}"
        if added:
            msg += f" — new: {', '.join(added)}"
        return pack, msg, manifest
    except Exception as e:  # offline, Riot down, etc.
        log.warning("auto-update failed: %s", e)
        return pack, f"Offline — using patch {pack['version']} data", manifest


def refresh_pool(pack, pool, max_per_run=8):
    """Plan B when the published pack is late or unreachable: refresh the matchup tables of the champions
    YOU play straight from OP.GG (one call each, at most once every 3 days per champion).
    pool: [(champ id, role)]. Returns how many tables were refreshed."""
    now = time.time()
    stale = pack.get("matchups_version") != pack["version"] or now - pack.get("matchups_at", 0) > 10 * 86400
    if not stale:
        return 0
    from . import opgg
    key_to_id = {c["key"]: cid for cid, c in pack["champions"].items()}
    done_at = pack.setdefault("pool_at", {})
    n = 0
    for cid, role in pool:
        tag = f"{role}:{cid}"
        lane = pack.get("stats", {}).get(role, {})
        if n >= max_per_run or now - done_at.get(tag, 0) < 3 * 86400 or cid not in lane:
            continue
        try:
            table = opgg.matchup_table(pack["champions"][cid], role, opgg.safe_opponent(lane, pack["champions"], cid), key_to_id)
            pack.setdefault("matchups", {}).setdefault(role, {})[cid] = table
            done_at[tag] = int(now)
            n += 1
        except Exception as e:
            log.info("pool refresh %s: %s", tag, e)
    if n:
        _save(pack)
    return n


def refresh_tiers(pack, max_age_days=10):
    """Keep lane tiers / win rates fresh between app releases: one OP.GG call, at most every few days.
    (Full matchup tables are ~270 calls, so those only come with a new data pack.)"""
    if time.time() - pack.get("stats_at", 0) < max_age_days * 86400:
        return pack, None
    try:
        from . import opgg
        by_name = {norm(c["name"]): cid for cid, c in pack["champions"].items()}
        by_name.update({norm(cid): cid for cid in pack["champions"]})
        meta = opgg.lane_meta(lambda n: by_name.get(norm(n)))
        if sum(len(v) for v in meta.values()) < 100:
            return pack, "tier refresh skipped (incomplete answer)"
        pack.update(stats=meta, meta_source="op.gg", stats_at=int(time.time()), stats_version=pack["version"],
                    stats_rank="emerald_plus")
        pack.setdefault("matchups", {})
        _save(pack)
        return pack, "Lane tiers refreshed from OP.GG"
    except Exception as e:
        log.warning("tier refresh failed: %s", e)
        return pack, None


def _save(pack):
    with open(paths.USER_PACK, "w", encoding="utf-8") as f:
        json.dump(pack, f)


def _vkey(v):
    return tuple(int(x) for x in re.findall(r"\d+", v))
