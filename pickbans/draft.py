"""Turns a raw LCU champ-select session into a simple draft dict the engine understands."""
import math
from itertools import permutations

from .pack import ROLES


def parse_session(s, key_to_id):
    """key_to_id: {int championKey: 'ChampionId'}"""
    me_cell = s.get("localPlayerCellId", -1)
    locked, in_progress, bans = {}, {}, []
    for group in s.get("actions", []):
        for a in group:
            cid = key_to_id.get(a.get("championId") or 0)
            if a.get("type") == "pick":
                if a.get("completed") and cid:
                    locked[a["actorCellId"]] = cid
                elif a.get("isInProgress"):
                    in_progress[a["actorCellId"]] = "pick"
            elif a.get("type") == "ban":
                if a.get("completed") and cid:
                    bans.append(cid)
                elif a.get("isInProgress"):
                    in_progress[a["actorCellId"]] = "ban"
    for k in (s.get("bans") or {}).get("myTeamBans", []) + (s.get("bans") or {}).get("theirTeamBans", []):
        cid = key_to_id.get(k)
        if cid and cid not in bans:
            bans.append(cid)

    allies = []
    for p in s.get("myTeam", []):
        cell = p.get("cellId")
        champ = locked.get(cell)
        hover = key_to_id.get(p.get("championPickIntent") or 0) or key_to_id.get(p.get("championId") or 0)
        allies.append({
            "cell": cell,
            "role": (p.get("assignedPosition") or "").upper() or None,
            "champ": champ,
            "hover": None if champ else hover,
            "is_me": cell == me_cell,
        })
    enemies = []
    for p in s.get("theirTeam", []):
        champ = locked.get(p.get("cellId")) or key_to_id.get(p.get("championId") or 0)
        enemies.append({"cell": p.get("cellId"), "role": (p.get("assignedPosition") or "").upper() or None, "champ": champ})

    me = next((a for a in allies if a["is_me"]), None)
    return {
        "phase": (s.get("timer") or {}).get("phase", "BAN_PICK"),
        "my_action": in_progress.get(me_cell),
        "my_role": (me or {}).get("role"),
        "allies": allies,
        "enemies": enemies,
        "bans": bans,
        "game_id": s.get("gameId"),
    }


def infer_roles(team, rate):
    """Fill missing roles with the most likely assignment. rate(champ, role) -> 0..1 (engine.role_rate)."""
    known = {p["role"] for p in team if p["role"]}
    todo = [p for p in team if not p["role"] and p["champ"]]
    free = [r for r in ROLES if r not in known]
    if not todo or not free:
        return team
    if len(todo) > len(free):
        todo = todo[: len(free)]

    def fit(champ, role):
        return math.log(rate(champ, role) + 0.01)

    best = max(permutations(free, len(todo)), key=lambda perm: sum(fit(p["champ"], r) for p, r in zip(todo, perm)))
    for p, r in zip(todo, best):
        p["role"] = r
        p["role_guessed"] = True
    return team
