"""Home screen (when you're not in champ select / in game): recent games, your matchup notebook, did-you-know cards."""
import random
import time

from .engine import role_label

MIN_GAMES = 500  # a matchup needs this many games in the stats before we state it as a fact


def build_home(engine, profile):
    ch = engine.champs
    pool = pool_of(engine, profile)
    return {
        "recent": [dict(r, vs=profile.vs_of(r["game_id"])) for r in profile.recent[:12]],
        "pool": [{"id": cid, "role": role, **_champ_line(engine, profile, cid, role)} for cid, role in pool],
        "notebook": {cid: _notebook(engine, profile, cid, role) for cid, role in pool},
        "facts": _facts(engine, profile, pool),
        "has_stats": bool(engine.pack.get("matchups")),
        "stats_patch": engine.pack.get("stats_version"),
        "stats_rank": engine.pack.get("stats_rank"),
    } if pool or profile.recent else None


def pool_of(engine, profile):
    """Up to 8 (champ, role) you actually play: recent games first, then mastery."""
    ranked = sorted(profile.games, key=lambda c: -profile.games[c]["games"])
    ranked += [c for c, _ in sorted(profile.mastery.items(), key=lambda x: -x[1]) if c not in ranked]
    out = []
    for cid in ranked:
        if cid not in engine.champs:
            continue
        roles = profile.games.get(cid, {}).get("roles") or {}
        role = max(roles, key=roles.get) if roles else None
        if not role:
            lanes = [r for r in ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY") if engine.stat(cid, r)]
            role = max(lanes, key=lambda r: engine.stat(cid, r)["rr"]) if lanes else engine.champs[cid]["positions"][0]
        out.append((cid, role))
        if len(out) == 8:
            break
    return out


def _champ_line(engine, profile, cid, role):
    st = engine.stat(cid, role) or {}
    rec = profile.games.get(cid, {"games": 0, "wins": 0})
    return {"tier": engine.tier(cid, role), "wr": st.get("wr"), "rank": st.get("rank"), "prev": st.get("prev"),
            "games": rec["games"], "wins": rec["wins"]}


def _notebook(engine, profile, cid, role):
    """Your own results vs each opponent + what the stats say are the best / worst lanes for this champ."""
    mine = {}
    for h in profile.history:
        if h.get("me") == cid and h.get("vs") and h.get("win") is not None:
            w = mine.setdefault(h["vs"], [0, 0])
            w[0] += bool(h["win"])
            w[1] += 1
    rows = []
    for vs, (w, g) in sorted(mine.items(), key=lambda x: -x[1][1]):
        real = engine.pair(role, cid, vs)
        rows.append({"vs": vs, "w": w, "g": g, "wr": round(real[0], 3) if real else None})
    table = engine.pack.get("matchups", {}).get(role, {}).get(cid, {})
    opps = set(table) | set(engine.pack.get("matchups_rank", {}).get(role, {}).get(cid, {}))
    rated = []
    for opp in opps:
        real = engine.pair(role, cid, opp)
        if real and real[1] >= MIN_GAMES and opp in engine.champs:
            rated.append((opp, real[0], real[1]))
    rated.sort(key=lambda x: x[1])
    fmt = lambda x: {"vs": x[0], "wr": round(x[1], 3), "games": x[2]}
    return {"role": role, "mine": rows, "worst": [fmt(x) for x in rated[:4]], "best": [fmt(x) for x in rated[::-1][:4]]}


def _facts(engine, profile, pool):
    ch = engine.champs
    name = lambda c: ch[c]["name"]
    facts = []
    for cid, role in pool:
        lane = role_label(role)
        st = engine.stat(cid, role)
        nb = _notebook(engine, profile, cid, role)
        if st:
            facts.append({"kind": "fact", "ids": [cid], "text": f"{name(cid)} {lane} wins {round(st['wr'] * 100)}% of games this patch "
                          f"({engine.tier(cid, role)} tier, #{st['rank']} in lane)."})
            move = (st.get("prev") or st["rank"]) - st["rank"]
            if move >= 3:
                facts.append({"kind": "fact", "ids": [cid], "text": f"{name(cid)} climbed {move} spots among {lane.lower()}s this patch."})
            elif move <= -3:
                facts.append({"kind": "fact", "ids": [cid], "text": f"{name(cid)} dropped {-move} spots among {lane.lower()}s this patch."})
            if st["br"] >= 0.15:
                facts.append({"kind": "fact", "ids": [cid], "text": f"{name(cid)} is banned in {round(st['br'] * 100)}% of games — have a backup pick."})
        for m in nb["best"][:2]:
            facts.append({"kind": "fact", "ids": [cid, m["vs"]], "text": f"{name(cid)} wins {round(m['wr'] * 100)}% vs {name(m['vs'])} — a lane to pick into."})
        for m in nb["worst"][:2]:
            facts.append({"kind": "fact", "ids": [cid, m["vs"]], "text": f"{name(cid)} only wins {round(m['wr'] * 100)}% vs {name(m['vs'])} — ban it or pick something else."})
        for m in nb["best"][:3] + nb["worst"][:3]:
            if abs(m["wr"] - 0.5) >= 0.025:
                facts.append({"kind": "quiz", "ids": [cid, m["vs"]], "role": lane,
                              "winner": cid if m["wr"] > 0.5 else m["vs"], "wr": round(max(m["wr"], 1 - m["wr"]) * 100)})
        rec = profile.games.get(cid)
        if rec and rec["games"] >= 4:
            facts.append({"kind": "fact", "ids": [cid], "text": f"You're {rec['wins']}-{rec['games'] - rec['wins']} on {name(cid)} in your recent games."})
        for row in nb["mine"]:
            if row["g"] >= 2:
                facts.append({"kind": "fact", "ids": [cid, row["vs"]], "text": f"Your {name(cid)} is {row['w']}-{row['g'] - row['w']} vs {name(row['vs'])}."})
    main = profile.main_role()
    lane_stats = engine.pack.get("stats", {}).get(main, {})
    if lane_stats:
        banned = max(lane_stats, key=lambda c: lane_stats[c]["br"])
        best = max((c for c in lane_stats if lane_stats[c]["pr"] >= 0.02), key=lambda c: lane_stats[c]["wr"], default=None)
        facts.append({"kind": "fact", "ids": [banned], "text": f"Most banned {role_label(main).lower()}: {name(banned)} ({round(lane_stats[banned]['br'] * 100)}% of games)."})
        if best:
            facts.append({"kind": "fact", "ids": [best], "text": f"Best win rate among popular {role_label(main).lower()}s: {name(best)} ({round(lane_stats[best]['wr'] * 100)}%)."})
    random.Random(time.strftime("%Y-%m-%d")).shuffle(facts)  # new order every day, stable within a day
    return facts[:40]
