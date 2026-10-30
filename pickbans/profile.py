"""What PICKBANS knows about YOU: mastery, recent games, and a local log of your matchups."""
import json
import logging
import math
import os
import time

from . import paths

log = logging.getLogger("pickbans.profile")

_LANE_TO_ROLE = {"TOP": "TOP", "JUNGLE": "JUNGLE", "MIDDLE": "MIDDLE", "MID": "MIDDLE", "BOTTOM": "BOTTOM", "BOT": "BOTTOM"}


class Profile:
    def __init__(self):
        self.name = None
        self.mastery = {}    # champ id -> points
        self.games = {}      # champ id -> {"games", "wins", "roles": {role: n}}
        self.role_counts = {}
        self.owned = None    # set of champ ids, None = unknown (assume all)
        self.recent = []     # last Summoner's Rift games, newest first
        self.history = _load_history()

    # ---------- loading ----------
    @classmethod
    def from_lcu(cls, lcu, key_to_id):
        p = cls()
        try:
            s = lcu.summoner() or {}
            p.name = s.get("gameName") or s.get("displayName")
            for m in lcu.mastery():
                cid = key_to_id.get(m.get("championId"))
                if cid:
                    p.mastery[cid] = m.get("championPoints", 0)
            games = lcu.match_history(60)
            for g in games:
                part = (g.get("participants") or [{}])[0]
                cid = key_to_id.get(part.get("championId"))
                if not cid or not _is_rift(g):
                    continue  # ARAM & co say nothing about your lanes
                stats = part.get("stats") or {}
                won = bool(stats.get("win"))
                role = _role_of(part.get("timeline") or {})
                p.recent.append({"game_id": g.get("gameId"), "champ": cid, "win": won, "role": role,
                                 "k": stats.get("kills", 0), "d": stats.get("deaths", 0), "a": stats.get("assists", 0),
                                 "t": int((g.get("gameCreation") or 0) / 1000)})
                rec = p.games.setdefault(cid, {"games": 0, "wins": 0, "roles": {}})
                rec["games"] += 1
                rec["wins"] += won
                if role:
                    rec["roles"][role] = rec["roles"].get(role, 0) + 1
                    p.role_counts[role] = p.role_counts.get(role, 0) + 1
            p.recent.sort(key=lambda r: -r["t"])
            p._resolve_results(games)
            owned = lcu.owned_ids()
            if owned:
                p.owned = {key_to_id[k] for k in owned if k in key_to_id}
        except Exception as e:
            log.warning("profile load partial: %s", e)
        return p

    # ---------- scores ----------
    def comfort(self, cid):
        """0..1 — how much you play this champ and how well."""
        pts = self.mastery.get(cid, 0)
        m = math.log10(pts / 1000 + 1) / math.log10(301)
        rec = self.games.get(cid, {"games": 0, "wins": 0})
        r = min(1.0, rec["games"] / 10)
        wr = (rec["wins"] + 5) / (rec["games"] + 10)
        return max(0.0, min(1.0, 0.5 * min(m, 1) + 0.5 * r + 0.3 * (wr - 0.5)))

    def played_in(self, cid, role):
        return self.games.get(cid, {}).get("roles", {}).get(role, 0)

    def main_role(self):
        return max(self.role_counts, key=self.role_counts.get) if self.role_counts else None

    def winrate(self, cid):
        rec = self.games.get(cid)
        if not rec or rec["games"] < 3:
            return None
        return rec["wins"] / rec["games"]

    def matchup(self, mine, theirs):
        """(wins, games) from your own logged games."""
        w = g = 0
        for h in self.history:
            if h.get("me") == mine and h.get("vs") == theirs and h.get("win") is not None:
                g += 1
                w += h["win"]
        return w, g

    def worst_matchups(self, min_games=2):
        stats = {}
        for h in self.history:
            if h.get("vs") and h.get("win") is not None:
                s = stats.setdefault(h["vs"], [0, 0])
                s[0] += h["win"]
                s[1] += 1
        return sorted(((v, w / g) for v, (w, g) in stats.items() if g >= min_games and w / g < 0.5), key=lambda x: x[1])

    def owns(self, cid):
        return self.owned is None or cid in self.owned

    # ---------- matchup log ----------
    def log_game(self, game_id, me, role, vs):
        if not game_id or any(h.get("game_id") == game_id for h in self.history):
            return
        self.history.append({"game_id": game_id, "me": me, "role": role, "vs": vs, "win": None, "t": int(time.time())})
        _save_history(self.history)

    def _resolve_results(self, games):
        by_id = {g.get("gameId"): g for g in games}
        changed = False
        for h in self.history:
            if h.get("win") is None and h.get("game_id") in by_id:
                part = (by_id[h["game_id"]].get("participants") or [{}])[0]
                h["win"] = bool((part.get("stats") or {}).get("win"))
                changed = True
        if changed:
            _save_history(self.history)

    def backfill(self, lcu, engine, limit=25):
        """Find who you laned against in your recent games (one client call per game, done once then cached)."""
        from .draft import infer_roles
        known = {h.get("game_id") for h in self.history if h.get("vs")}
        added = 0
        for r in self.recent[:limit]:
            if r["game_id"] in known or not r["game_id"]:
                continue
            try:
                g = lcu.get(f"/lol-match-history/v1/games/{r['game_id']}", timeout=15) or {}
                parts = g.get("participants") or []
                mine = next((x for x in parts if engine.key_to_id.get(x.get("championId")) == r["champ"]), None)
                if not mine:
                    continue
                team = lambda tid: [{"role": None, "champ": engine.key_to_id.get(x.get("championId"))}
                                    for x in parts if x.get("teamId") == tid]
                allies = team(mine["teamId"])
                enemies = team(next(x["teamId"] for x in parts if x["teamId"] != mine["teamId"]))
                role = r["role"]
                if not role:
                    infer_roles(allies, engine.role_rate)
                    role = next((a["role"] for a in allies if a["champ"] == r["champ"]), None)
                infer_roles(enemies, engine.role_rate)
                vs = next((e["champ"] for e in enemies if e["role"] == role), None)
                r["role"] = role
                if vs:
                    self.history = [h for h in self.history if h.get("game_id") != r["game_id"]]
                    self.history.append({"game_id": r["game_id"], "me": r["champ"], "role": role, "vs": vs,
                                         "win": r["win"], "t": r["t"]})
                    added += 1
            except Exception as e:
                log.warning("backfill %s: %s", r["game_id"], e)
                break
        if added:
            _save_history(self.history)
        return added

    def vs_of(self, game_id):
        return next((h.get("vs") for h in self.history if h.get("game_id") == game_id), None)

    def to_cache(self):
        return {"name": self.name, "mastery": self.mastery, "games": self.games, "role_counts": self.role_counts,
                "recent": self.recent}

    @classmethod
    def from_cache(cls, d):
        p = cls()
        p.name = d.get("name")
        p.mastery = d.get("mastery") or {}
        p.games = d.get("games") or {}
        p.role_counts = d.get("role_counts") or {}
        p.recent = d.get("recent") or []
        return p

    def to_json(self):
        top = sorted(self.mastery.items(), key=lambda x: -x[1])[:10]
        return {"name": self.name, "main_role": self.main_role(), "pool": [c for c, _ in top], "logged_games": len(self.history)}


def _is_rift(g):
    mode, mid = g.get("gameMode"), g.get("mapId")
    return (mode in (None, "CLASSIC")) and (mid in (None, 11))


def _role_of(tl):
    lane, role = (tl.get("lane") or "").upper(), (tl.get("role") or "").upper()
    if lane == "BOTTOM" and "SUPPORT" in role:
        return "UTILITY"
    return _LANE_TO_ROLE.get(lane)


def _load_history():
    if os.path.exists(paths.HISTORY_FILE):
        try:
            with open(paths.HISTORY_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return []


def _save_history(h):
    with open(paths.HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(h, f, indent=1)
