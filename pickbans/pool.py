"""YOUR champion pool per role: detected from your games, corrected by hand.

The whole app recommends from this pool first. A champion outside it never shows up in the main recs.
"""
import json
import os

from . import paths
from .pack import ROLES

POOL_FILE = os.path.join(paths.USER_DIR, "pool.json")
MIN_GAMES = 2            # games in a role (last ~60 Rift games) to count as "you play it there"
MIN_MASTERY = 30000      # or this much mastery, in the champion's usual lane(s)


def load_overrides():
    try:
        with open(POOL_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    return {"add": {r: list(data.get("add", {}).get(r, [])) for r in ROLES},
            "remove": {r: list(data.get("remove", {}).get(r, [])) for r in ROLES}}


def save_overrides(ov):
    with open(POOL_FILE, "w", encoding="utf-8") as f:
        json.dump(ov, f, indent=1)


def edit(ov, action, role, cid):
    """action: add (always in your pool) | remove (never) | reset (back to what was detected)."""
    if role not in ROLES:
        raise ValueError(role)
    for k in ("add", "remove"):
        if cid in ov[k][role]:
            ov[k][role].remove(cid)
    if action in ("add", "remove"):
        ov[action][role].append(cid)
    save_overrides(ov)
    return ov


def _usual_lanes(engine, cid):
    lanes = [r for r in ROLES if (engine.stat(cid, r) or {}).get("rr", 0) >= 0.25]
    return lanes or engine.champs[cid]["positions"][:1]


def detected(engine, profile):
    """{role: {champ: why}} from recent games per role + big mastery in the champion's usual lanes."""
    out = {r: {} for r in ROLES}
    for cid, rec in profile.games.items():
        if cid not in engine.champs:
            continue
        roles = rec.get("roles") or {}
        if roles:
            for role, n in roles.items():
                if n >= MIN_GAMES and role in out:
                    out[role][cid] = f"{n} recent games"
        elif rec["games"] >= MIN_GAMES:  # the client didn't say which lane: use the champion's usual one
            for role in _usual_lanes(engine, cid):
                out[role][cid] = f"{rec['games']} recent games"
    for cid, pts in profile.mastery.items():
        if pts >= MIN_MASTERY and cid in engine.champs:
            for role in _usual_lanes(engine, cid):
                out[role].setdefault(cid, f"{pts // 1000}k mastery")
    return out


def build(engine, profile, ov):
    """Final pool: {role: [{id, source, why, games, wins, mastery}]} sorted by how much you play it, plus what you removed."""
    det = detected(engine, profile)
    pool, removed = {}, {}
    for role in ROLES:
        entries = []
        ids = list(det[role]) + [c for c in ov["add"][role] if c not in det[role]]
        for cid in ids:
            if cid in ov["remove"][role] or cid not in engine.champs:
                continue
            rec = profile.games.get(cid, {})
            entries.append({"id": cid, "source": "added" if cid in ov["add"][role] else "detected",
                            "why": det[role].get(cid, "added by you"),
                            "games": (rec.get("roles") or {}).get(role, 0), "wins": rec.get("wins", 0),
                            "mastery": profile.mastery.get(cid, 0)})
        entries.sort(key=lambda e: (e["source"] != "added", -e["games"], -e["mastery"]))
        pool[role] = entries
        removed[role] = [c for c in ov["remove"][role] if c in engine.champs]
    return {"roles": pool, "removed": removed}


def ids(pool, role):
    return [e["id"] for e in pool["roles"].get(role, [])]


def similarity(engine, cid, other):
    """0..1 — how alike two champions play (traits + playstyle labels)."""
    a, b = engine.champs[cid]["traits"], engine.champs[other]["traits"]
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    cos = dot / (na * nb) if na and nb else 0
    styles = set(engine.champs[cid]["styles"]) & set(engine.champs[other]["styles"])
    return min(1.0, cos * 0.8 + (0.2 if styles else 0))
