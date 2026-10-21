"""In-game panel: reads Riot's Live Client Data API (port 2999, only while a game runs).

Only uses info the game itself shows (clock, levels, kills, objective kills). No enemy cooldown tracking.
"""
import re

from . import net
from .assess import split_note
from .pack import norm

LIVE_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"
DRAKE_FIRST, DRAKE_RESPAWN = 5 * 60, 5 * 60
BARON_FIRST, BARON_RESPAWN = 20 * 60, 6 * 60
ALERT_SECONDS = 120
POSITIONS = {"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"}


def fetch():
    try:
        return net.get_json(LIVE_URL, timeout=2, insecure=True)
    except Exception:
        return None


class LiveTracker:
    """Keeps a little memory between polls (when someone hit 6) so alerts show for a while then fade."""

    def __init__(self, engine):
        self.engine = engine
        self.by_name = {norm(c["name"]): cid for cid, c in engine.champs.items()}
        self.by_name.update({norm(cid): cid for cid in engine.champs})
        self.hit6 = {}
        self.roles_checked = False

    def champ_of(self, p):
        raw = p.get("rawChampionName", "")
        m = re.search(r"displayname_(\w+)$", raw)
        if m and m.group(1) in self.engine.champs:
            return m.group(1)
        return self.by_name.get(norm(p.get("championName", "")))

    def players(self, data):
        active = data.get("activePlayer") or {}
        me_ids = {active.get("riotId"), active.get("summonerName")} - {None, ""}
        players = data.get("allPlayers") or []
        my_team = next((p["team"] for p in players if {p.get("riotId"), p.get("summonerName")} & me_ids), "ORDER")
        out = []
        for p in players:
            out.append({
                "champ": self.champ_of(p),
                "ally": p["team"] == my_team,
                "is_me": bool({p.get("riotId"), p.get("summonerName")} & me_ids),
                "role": p.get("position") if p.get("position") in POSITIONS else None,
                "level": p.get("level", 1),
                "kills": (p.get("scores") or {}).get("kills", 0),
                "dead": p.get("isDead", False),
                "smite": any("smite" in ((p.get("summonerSpells") or {}).get(k) or {}).get("displayName", "").lower()
                             for k in ("summonerSpellOne", "summonerSpellTwo")),
            })
        return out

    def fix_roles(self, draft, data):
        """Champ select only lets us GUESS enemy lanes. In game, Riot gives each player's real position
        (and Smite = jungler). Correct the draft with that. Returns True if anything changed."""
        from .draft import infer_roles
        live_enemies = {p["champ"]: p for p in self.players(data) if not p["ally"] and p["champ"]}
        enemies = [e for e in draft["enemies"] if e.get("champ")]
        if not live_enemies or not enemies:
            return False
        before = {e["champ"]: e.get("role") for e in enemies}
        known = {c: p["role"] for c, p in live_enemies.items() if p["role"]}
        if len(set(known.values())) == len(known) and len(known) >= 4:  # real positions (ranked / draft)
            self.roles_checked = True
            for e in enemies:
                if e["champ"] in known:
                    e["role"], e["role_guessed"] = known[e["champ"]], False
        else:  # positions missing (some modes): at least pin the Smite holder, re-guess the rest
            junglers = [c for c, p in live_enemies.items() if p["smite"]]
            if len(junglers) != 1:
                return False  # no info yet: try again on the next poll
            self.roles_checked = True
            for e in enemies:
                if e["champ"] == junglers[0]:
                    e["role"], e["role_guessed"] = "JUNGLE", False
                elif e.get("role_guessed", True):
                    e["role"] = None
            infer_roles(enemies, self.engine.role_rate)
        return any(before[e["champ"]] != e.get("role") for e in enemies)

    def draft_from_live(self, data):
        """If PICKBANS was opened mid-game, rebuild a draft from the live player list."""
        ps = self.players(data)
        allies = [{"cell": i, "role": p["role"], "champ": p["champ"], "hover": None, "is_me": p["is_me"]}
                  for i, p in enumerate(ps) if p["ally"]]
        enemies = [{"cell": i, "role": p["role"], "champ": p["champ"]} for i, p in enumerate(ps) if not p["ally"]]
        me = next((a for a in allies if a["is_me"]), {})
        return {"phase": "INGAME", "my_action": None, "my_role": me.get("role"),
                "allies": allies, "enemies": enemies, "bans": [], "game_id": None}

    def update(self, data, draft):
        ch = self.engine.champs
        t = (data.get("gameData") or {}).get("gameTime", 0)
        ps = self.players(data)
        me = next((p for p in ps if p["is_me"]), None)
        alerts = []

        # level 6 spikes (yours + enemies with a scary ult)
        for p in ps:
            key = (p["champ"], p["ally"])
            if p["level"] >= 6 and key not in self.hit6:
                self.hit6[key] = t
        for (cid, ally), when in self.hit6.items():
            if not cid or t - when > ALERT_SECONDS:
                continue
            if me and cid == me["champ"] and ally:
                alerts.append({"kind": "good", "id": cid, "text": "You're 6 — your ult is up. " + _ult_hint(ch[cid])})
            elif not ally:
                tr = ch[cid]["traits"]
                if tr.get("GL", 0) + tr.get("EN", 0) + tr.get("BU", 0) + tr.get("PI", 0) >= 4 and ch[cid].get("watch"):
                    head, _ = split_note(ch[cid]["watch"], ch[cid]["name"])
                    alerts.append({"kind": "bad", "id": cid, "text": f"{ch[cid]['name']} is 6 — {head[0].lower() + head[1:]}."})

        # objectives (the game shows these timers too)
        events = (data.get("events") or {}).get("Events") or []
        last = lambda name: max((e["EventTime"] for e in events if e.get("EventName") == name), default=None)
        objectives = []
        for label, first, respawn, ev in (("Drake", DRAKE_FIRST, DRAKE_RESPAWN, "DragonKill"),
                                          ("Baron", BARON_FIRST, BARON_RESPAWN, "BaronKill")):
            killed = last(ev)
            spawn = killed + respawn if killed is not None else first
            left = spawn - t
            if left <= 0:
                objectives.append({"label": label, "text": f"{label} is up", "soon": True})
            elif left <= 90:
                objectives.append({"label": label, "text": f"{label} in {int(left // 60)}:{int(left % 60):02d} — ward and group", "soon": True})
            elif label == "Drake" or t > BARON_FIRST - 180:
                objectives.append({"label": label, "text": f"{label} in {int(left // 60)}:{int(left % 60):02d}", "soon": False})

        # game phase advice
        a_kills = sum(p["kills"] for p in ps if p["ally"])
        e_kills = sum(p["kills"] for p in ps if not p["ally"])
        if t < 14 * 60:
            phase, advice = "Laning", "Farm, watch your lane opponent's cooldowns, back when low."
        elif t < 25 * 60:
            phase, advice = "Mid game", "Group for drakes and towers. Don't farm a side lane alone without vision."
        else:
            phase, advice = "Late game", "One death = Baron or game. Stay with your team, never face-check."
        if a_kills - e_kills >= 5:
            advice = "You're ahead: take objectives together, don't chase into fog. " + advice
        elif e_kills - a_kills >= 5:
            advice = "You're behind: farm safe, defend towers, wait for their mistake. " + advice

        return {
            "time": int(t), "clock": f"{int(t // 60)}:{int(t % 60):02d}", "phase": phase, "advice": advice,
            "alerts": alerts, "objectives": objectives, "score": [a_kills, e_kills],
            "levels": {("a:" if p["ally"] else "e:") + (p["champ"] or "?"): p["level"] for p in ps},
            "my_level": me["level"] if me else None,
        }


def _ult_hint(c):
    for part in (c.get("play") or "").split(". "):
        if "ult" in part.lower() or "(r)" in part.lower():
            return part.strip().rstrip(".") + "."
    return "Look for a fight."
