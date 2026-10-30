"""Home screen (when you're not in champ select / in game): recent games, your matchup notebook, did-you-know cards."""
import random
import time

from .engine import role_label

MIN_GAMES = 500  # a matchup needs this many games in the stats before we state it as a fact


def build_home(engine, profile, mypool=None):
    ch = engine.champs
    pool = pool_of(engine, profile, mypool)
    return {
        "recent": [dict(r, vs=profile.vs_of(r["game_id"])) for r in profile.recent[:12]],
        "pool": [{"id": cid, "role": role, **_champ_line(engine, profile, cid, role)} for cid, role in pool],
        "notebook": {cid: _notebook(engine, profile, cid, role) for cid, role in pool},
        "facts": _facts(engine, profile, pool),
        "has_stats": bool(engine.pack.get("matchups")),
        "stats_patch": engine.pack.get("stats_version"),
        "stats_rank": engine.pack.get("stats_rank"),
    } if pool or profile.recent else None


def pool_of(engine, profile, mypool=None):
    """Up to 8 (champ, role) from YOUR pool (what you added first, then most played)."""
    if mypool is None:
        from . import pool as poolmod
        mypool = poolmod.build(engine, profile, poolmod.load_overrides())
    entries = [(e, role) for role, lst in mypool["roles"].items() for e in lst]
    entries.sort(key=lambda x: (x[0]["source"] != "added", -x[0]["games"], -x[0]["mastery"]))
    out, seen = [], set()
    for e, role in entries:
        if e["id"] not in seen:
            seen.add(e["id"])
            out.append((e["id"], role))
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
        if real and opp in engine.champs:
            rated.append((opp, real[0], real[1]))
    # enough games = relative to how much this champion is played (rare picks never reach a fixed number)
    enough = max(60, min(MIN_GAMES, 0.25 * max((x[2] for x in rated), default=0)))
    rated = [x for x in rated if x[2] >= enough]
    rated.sort(key=lambda x: x[1])
    fmt = lambda x: {"vs": x[0], "wr": round(x[1], 3), "games": x[2]}
    worst = [fmt(x) for x in rated if x[1] <= 0.495][:4]
    best = [fmt(x) for x in rated[::-1] if x[1] >= 0.505][:4]
    return {"role": role, "mine": rows, "worst": worst, "best": best}


def _facts(engine, profile, pool):
    ch = engine.champs
    name = lambda c: ch[c]["name"]
    facts = []
    asked = set()
    for cid, role in pool:
        lane = role_label(role)
        st = engine.stat(cid, role)
        nb = _notebook(engine, profile, cid, role)
        if st:
            where = {"gold": "in Gold"}.get(engine.pack.get("stats_rank"), "in ranked")
            facts.append({"kind": "fact", "ids": [cid], "text": f"{name(cid)} {lane} wins {round(st['wr'] * 100)}% of games {where} "
                          f"({engine.tier(cid, role)} tier, #{st['rank']} in lane)."})
            move = (st.get("prev") or st["rank"]) - st["rank"]
            if not engine.pack.get("stats_thin"):  # early in a patch these numbers are last patch's
                if move >= 3:
                    facts.append({"kind": "fact", "ids": [cid], "text": f"{name(cid)} climbed {move} spots among {lane.lower()}s this patch."})
                elif move <= -3:
                    facts.append({"kind": "fact", "ids": [cid], "text": f"{name(cid)} dropped {-move} spots among {lane.lower()}s this patch."})
            if st["br"] >= 0.15:
                facts.append({"kind": "fact", "ids": [cid], "text": f"{name(cid)} is banned in {round(st['br'] * 100)}% of games — have a backup pick."})
        # head-to-heads are always a question, never a sentence that gives the answer away
        for m in nb["best"][:4] + nb["worst"][:4]:
            pair = frozenset((cid, m["vs"]))
            if abs(m["wr"] - 0.5) >= 0.025 and pair not in asked:
                asked.add(pair)
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
        by_ban = sorted(lane_stats, key=lambda c: -lane_stats[c]["br"])
        top = lane_stats[by_ban[0]]["br"]
        if len(by_ban) > 1 and top - lane_stats[by_ban[1]]["br"] >= 0.03:  # numbers are rounded: only a clear #1 counts
            facts.append({"kind": "fact", "ids": [by_ban[0]], "text": f"Most banned {role_label(main).lower()}: {name(by_ban[0])} ({round(top * 100)}% of games)."})
    rng = random.Random(time.strftime("%Y-%m-%d"))  # new order every day, stable within a day
    quizzes = [f for f in facts if f["kind"] == "quiz"]
    others = [f for f in facts if f["kind"] != "quiz"]
    rng.shuffle(quizzes)
    rng.shuffle(others)
    out = []
    while quizzes or others:  # mostly questions: two quizzes, then a fact
        out += quizzes[:2] + others[:1]
        quizzes, others = quizzes[2:], others[1:]
    return out[:40]
