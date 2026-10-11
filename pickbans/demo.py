"""Scripted champ select that produces real LCU-shaped sessions, so the app can be tried without League."""
from .profile import Profile

# You are Support (cell 3). Order roughly follows ranked draft.
ALLY_ROLES = ["TOP", "JUNGLE", "MIDDLE", "UTILITY", "BOTTOM"]
ME = 3
BANS = ["Yasuo", "Zed", "Blitzcrank", "Leona", "MasterYi", "Thresh", "Darius", "Morgana", "Lux", "Samira"]
# (side, cell, champ, hover_first)
PICKS = [
    ("ally", 4, "Jinx", True),
    ("enemy", 5, "Sejuani", False),
    ("enemy", 6, "Malphite", False),
    ("ally", 1, "Vi", True),
    ("ally", 2, "Ahri", True),
    ("enemy", 7, "Nautilus", False),
    ("enemy", 8, "Caitlyn", False),
    ("ally", 0, "Garen", True),
    ("ally", ME, "Nami", True),
    ("enemy", 9, "Galio", False),
]


def fake_live(elapsed, names):
    """Live Client Data shaped like the real API. Game clock runs 15x fast so the demo shows level 6, drake, etc.
    names: {champ id: display name}"""
    t = 60 + elapsed * 15
    ally_champs = {"TOP": "Garen", "JUNGLE": "Vi", "MIDDLE": "Ahri", "BOTTOM": "Jinx", "UTILITY": "Nami"}
    enemy_champs = {"TOP": "Malphite", "JUNGLE": "Sejuani", "MIDDLE": "Galio", "BOTTOM": "Caitlyn", "UTILITY": "Nautilus"}
    players = []
    for team, champs, lead in (("ORDER", ally_champs, 0), ("CHAOS", enemy_champs, 25)):
        for pos, cid in champs.items():
            lvl = min(18, 1 + int((t + lead) / (95 if pos != "UTILITY" else 110)))
            me = team == "ORDER" and pos == "UTILITY"
            players.append({"championName": names[cid], "rawChampionName": f"game_character_displayname_{cid}",
                            "team": team, "position": pos, "level": lvl, "isDead": False,
                            "riotId": "DemoPlayer#DEMO" if me else f"{cid}#BOT",
                            "scores": {"kills": int(t / (260 if team == "ORDER" else 300))}})
    events = [{"EventName": "GameStart", "EventTime": 0}]
    if t > 330:
        events.append({"EventName": "DragonKill", "EventTime": 330})
    return {"gameData": {"gameTime": t}, "activePlayer": {"riotId": "DemoPlayer#DEMO", "level": 1},
            "allPlayers": players, "events": {"Events": events}}


def demo_profile(key_of):
    p = Profile()
    p.name = "DemoPlayer"
    p.history = []
    for cid, pts, games, wins in [("Blitzcrank", 120000, 14, 8), ("Nautilus", 60000, 9, 5), ("Lux", 45000, 6, 3),
                                  ("Nami", 30000, 5, 3), ("Morgana", 20000, 4, 2), ("Soraka", 8000, 2, 1)]:
        p.mastery[cid] = pts
        p.games[cid] = {"games": games, "wins": wins, "roles": {"UTILITY": games}}
    p.role_counts = {"UTILITY": 40, "BOTTOM": 5}
    import time as _t
    now = int(_t.time())
    games = [("Blitzcrank", "Lulu", True), ("Nautilus", "Thresh", False), ("Blitzcrank", "Morgana", False),
             ("Nami", "Leona", False), ("Lux", "Pyke", True), ("Blitzcrank", "Soraka", True),
             ("Nautilus", "Janna", False), ("Blitzcrank", "Lulu", True), ("Nami", "Nautilus", False), ("Blitzcrank", "Morgana", False)]
    for i, (me, vs, win) in enumerate(games):
        gid = 500 + i
        p.recent.append({"game_id": gid, "champ": me, "win": win, "role": "UTILITY", "k": 2 + i % 4, "d": 3 + i % 3,
                         "a": 9 + i, "t": now - i * 5400})
        p.history.append({"game_id": gid, "me": me, "role": "UTILITY", "vs": vs, "win": win, "t": now - i * 5400})
    return p


def timeline(key_of):
    """List of (seconds, gameflow phase, session or None)."""
    steps = []
    bans_done, locked, hovers = [], {}, {}

    def snap(phase="BAN_PICK", in_progress=None):
        actions = []
        for i, b in enumerate(bans_done):
            actions.append([{"actorCellId": i, "championId": key_of(b), "type": "ban", "completed": True, "isInProgress": False}])
        for cell, champ in locked.items():
            actions.append([{"actorCellId": cell, "championId": key_of(champ), "type": "pick", "completed": True, "isInProgress": False}])
        if in_progress:
            actions.append([{"actorCellId": in_progress[0], "championId": 0, "type": in_progress[1], "completed": False, "isInProgress": True}])
        return {
            "gameId": 999000111,
            "localPlayerCellId": ME,
            "timer": {"phase": phase},
            "actions": actions,
            "bans": {"myTeamBans": [], "theirTeamBans": []},
            "myTeam": [{"cellId": c, "assignedPosition": ALLY_ROLES[c].lower(),
                        "championId": key_of(locked[c]) if c in locked else 0,
                        "championPickIntent": key_of(hovers[c]) if c in hovers and c not in locked else 0} for c in range(5)],
            "theirTeam": [{"cellId": c, "assignedPosition": "", "championId": key_of(locked[c]) if c in locked else 0} for c in range(5, 10)],
        }

    t = 12  # the home screen shows first
    steps.append((t, "ChampSelect", snap("PLANNING")))
    hovers.update({4: "Jinx", 1: "Vi", 2: "Ahri", 0: "Garen"})
    t += 3
    steps.append((t, "ChampSelect", snap("BAN_PICK", (ME, "ban"))))
    for b in BANS:
        t += 1.2
        bans_done.append(b)
        steps.append((t, "ChampSelect", snap("BAN_PICK", (ME, "ban") if len(bans_done) < 4 else None)))
    for side, cell, champ, hover_first in PICKS:
        if cell == ME:
            t += 3
            steps.append((t, "ChampSelect", snap("BAN_PICK", (ME, "pick"))))
            hovers[ME] = champ
            t += 3
            steps.append((t, "ChampSelect", snap("BAN_PICK", (ME, "pick"))))
        t += 2.5
        locked[cell] = champ
        steps.append((t, "ChampSelect", snap()))
    t += 3
    steps.append((t, "ChampSelect", snap("FINALIZATION")))
    t += 6
    steps.append((t, "InProgress", None))
    return steps
