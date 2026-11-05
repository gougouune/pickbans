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


def fake_live(elapsed, names, my_item_ids=()):
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
            items = []
            if me:   # you buy your build as the game goes
                items = [int(i) for i in list(my_item_ids)[:max(0, int((t - 240) // 240) + 1)]]
            elif cid == "Caitlyn" and t >= 480:      # a lifesteal item at ~8:00
                items = [3072]
            elif cid in ("Malphite", "Sejuani") and t >= 600:  # armor stacking at ~10:00
                items = [3075, 3068]
            players.append({"championName": names[cid], "rawChampionName": f"game_character_displayname_{cid}",
                            "team": team, "position": pos, "level": lvl, "isDead": False,
                            "riotId": "DemoPlayer#DEMO" if me else f"{cid}#BOT",
                            "items": [{"itemID": i, "slot": n, "count": 1} for n, i in enumerate(items)],
                            "scores": {"kills": int(t / (260 if team == "ORDER" else 300)), "deaths": int(t / 700)}})
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


def fake_game(key_of):
    """A finished game shaped like the client's match-history answers: (detail, timeline, my champion key).
    You played Nami support, died early and often, put down few wards."""
    me_key = key_of("Nami")
    champs = [266, 64, 103, 22, me_key, 54, 106, 61, 51, 53]           # participant ids 1..10
    stats = [dict(kills=5, deaths=3, assists=6, totalMinionsKilled=190, neutralMinionsKilled=0, visionScore=20, wardsPlaced=9,
                  wardsKilled=1, visionWardsBoughtInGame=2, totalDamageDealtToChampions=17000, win=False) for _ in range(10)]
    stats[4] = dict(kills=1, deaths=8, assists=9, totalMinionsKilled=24, neutralMinionsKilled=0, visionScore=22, wardsPlaced=11,
                    wardsKilled=2, visionWardsBoughtInGame=0, totalDamageDealtToChampions=6500, win=False)
    parts = []
    for i in range(10):
        parts.append({"participantId": i + 1, "teamId": 100 if i < 5 else 200, "championId": champs[i], "stats": stats[i],
                      "timeline": {"lane": "BOTTOM", "role": "DUO_SUPPORT", "creepsPerMinDeltas": {"0-10": 1.0, "10-20": 0.7, "20-30": 0.4},
                                   "csDiffPerMinDeltas": {"0-10": -0.2}} if i == 4 else {}})
    detail = {"gameId": 123, "gameDuration": 1740, "participants": parts}
    # your 8 deaths (blue side: x + y above ~14900 = enemy half of the map)
    deaths = [(300, 9500, 6800), (420, 10200, 6900), (560, 9000, 7000), (840, 3000, 4000), (1000, 11000, 5600),
              (1300, 2500, 5200), (1500, 10500, 7600), (1650, 4000, 3000)]
    frames = [{"timestamp": 0, "events": []}]
    for t, x, y in deaths:
        frames.append({"timestamp": t * 1000, "events": [{"type": "CHAMPION_KILL", "timestamp": t * 1000, "victimId": 5, "killerId": 8,
                                                          "position": {"x": x, "y": y}}]})
    for t in (120, 400, 900, 1500):
        frames.append({"timestamp": t * 1000, "events": [{"type": "WARD_PLACED", "timestamp": t * 1000, "creatorId": 5, "wardType": "YELLOW_TRINKET"}]})
    return detail, {"frames": frames}, me_key


def fake_history_metrics():
    """Ten past support games (newest first): vision and deaths improved over time."""
    def g(d, vis, kp, win):
        return {"game_id": 1, "role": "UTILITY", "m": {"role": "UTILITY", "dur": 1700, "win": win, "k": 1, "d": d, "a": 10, "cs_pm": 0.7,
                                                       "vis_pm": vis, "wards_pm": 0.4, "cw": 1, "deaths_pm": round(d / 28, 3), "kp": kp, "dmg_share": 0.08}}
    return [g(5, 1.5, 0.62, True), g(6, 1.4, 0.6, False), g(4, 1.7, 0.66, True), g(7, 1.2, 0.55, False), g(5, 1.6, 0.6, True),
            g(9, 0.8, 0.5, False), g(8, 0.9, 0.52, False), g(7, 1.0, 0.5, False), g(10, 0.7, 0.45, False), g(8, 1.1, 0.55, True)]

