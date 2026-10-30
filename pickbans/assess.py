"""Quick match assessment — compact: matchups board, short traps, one-line plan.

No AI at runtime: pre-written champion notes from the data pack + template sentences.
"""
from .pack import ROLES

SCALE = {"E": 0, "M": 1, "L": 2}


def assess(engine, draft, profile):
    ch = engine.champs
    role = draft.get("my_role") or profile.main_role() or "MIDDLE"
    me = next((a for a in draft["allies"] if a["is_me"]), {})
    mine = me.get("champ") or me.get("hover")
    allies = [a["champ"] for a in draft["allies"] if a["champ"]]
    enemies = [e["champ"] for e in draft["enemies"] if e["champ"]]
    at, et = engine.totals(allies), engine.totals(enemies)
    ally_at = _by_role(draft["allies"], mine and {role: mine})
    enemy_at = _by_role(draft["enemies"])

    # ---- headline + plan (one line each) ----
    a_scale = sum(SCALE[ch[c]["scaling"]] for c in allies) / max(1, len(allies))
    e_scale = sum(SCALE[ch[c]["scaling"]] for c in enemies) / max(1, len(enemies))
    if a_scale - e_scale >= 0.4:
        headline, plan = "You scale better", "Play safe early, farm, fight after 2-3 items."
    elif e_scale - a_scale >= 0.4:
        headline, plan = "You're the early team", "Be aggressive: take drakes and towers, end before 30 min."
    else:
        headline, plan = "Even game", "Play around objectives — the team that shows up first wins."

    gaps = [m["label"] for m in engine.missing(allies) if m.get("missing")] if len(allies) >= 4 else []
    if "Frontline" in gaps:
        plan = "No frontline: let them engage first, then punish."
    elif "Engage" in gaps:
        plan = "Little engage: pick people off, don't force 5v5s."
    elif at.get("EN", 0) >= 6:
        plan = "Lots of engage: group and win the 5v5 near objectives."
    elif at.get("PO", 0) >= 6:
        plan = "Poke team: chip them before objectives, no long all-ins."

    # ---- tags (chips) ----
    tags = []
    for label in gaps[:2]:
        tags.append({"text": f"You: no {label.lower()}", "kind": "bad"})
    if at.get("EN", 0) >= 6:
        tags.append({"text": "You: engage", "kind": "good"})
    if et.get("EN", 0) >= 6:
        tags.append({"text": "They: engage", "kind": "bad"})
    if et.get("DI", 0) + et.get("BU", 0) * 0.5 >= 8:
        tags.append({"text": "They: dive / burst", "kind": "bad"})
    if et.get("PO", 0) >= 6:
        tags.append({"text": "They: poke", "kind": "bad"})
    dmg = engine.damage_mix(enemies)
    if len(enemies) >= 4 and dmg["AP"] <= 0.5:
        tags.append({"text": "They: all AD", "kind": "info"})
    elif len(enemies) >= 4 and dmg["AD"] <= 0.5:
        tags.append({"text": "They: all AP", "kind": "info"})

    # ---- matchups board (ally perspective, -1..1) ----
    matchups = []
    for r in ROLES:
        a, e = ally_at.get(r), enemy_at.get(r)
        score = wr = None
        if a and e:
            score = round((engine.lane(a, e, profile, r)[0] - 0.5) * 2, 2)
            real = engine.pair(r, a, e)
            wr = round(real[0] * 100) if real else None
        matchups.append({"role": r, "ally": a, "enemy": e, "score": score, "wr": wr, "mine": r == role})
    bot = _duo(engine, profile, ally_at, enemy_at)
    if bot is not None:
        for m in matchups:
            if m["role"] in ("BOTTOM", "UTILITY"):
                m["duo"] = bot

    # ---- my lane ----
    lane = None
    if mine:
        opps = [enemy_at.get(r) for r in (("BOTTOM", "UTILITY") if role in ("BOTTOM", "UTILITY") else (role,))]
        opps = [o for o in opps if o]
        main_opp = enemy_at.get(role)
        if role in ("BOTTOM", "UTILITY") and bot is not None:
            s = bot
        elif main_opp:
            s = (engine.lane(mine, main_opp, profile, role)[0] - 0.5) * 2
        else:
            s = None
        verdict = None if s is None else "good" if s >= 0.2 else "hard" if s <= -0.2 else "even"
        tip = {"good": "You're favored: trade early and push your lead.",
               "hard": "Tough lane: farm safe until 6 or until your jungler comes. Dying is worse than losing CS.",
               "even": "Even lane: play for your level 2/6 spikes and your jungler."}.get(verdict, "")
        lane = {"me": mine, "opps": opps, "verdict": verdict, "tip": tip,
                "vs": ch.get(main_opp, {}).get("vs", "") if main_opp else "",
                "play": ch[mine].get("play", ""), "styles": ch[mine]["styles"]}

    # ---- traps: short headline + detail ----
    def threat(c):
        t = ch[c]["traits"]
        return t.get("GL", 0) * 2 + t.get("PI", 0) + t.get("BU", 0) * 0.5 + t.get("EN", 0) * 0.5
    traps = []
    for c in sorted(enemies, key=threat, reverse=True):
        if ch[c].get("watch"):
            head, tail = split_note(ch[c]["watch"], ch[c]["name"])
            traps.append({"id": c, "head": head, "tail": tail})

    gameplan = None
    if mine:
        build = engine.build(mine, role)
        gameplan = {"champ": mine, "styles": ch[mine]["styles"], "play": ch[mine].get("play", ""), "build": build,
                    "situational": engine.situational(mine, enemies, build)}

    return {"headline": headline, "plan": plan, "tags": tags[:4], "matchups": matchups, "gameplan": gameplan,
            "lane": lane, "traps": traps[:4], "allies": allies, "enemies": enemies}


def split_note(text, name):
    """'Zilean ult REVIVES his ally — expect it.' -> ('Ult REVIVES his ally', 'expect it')"""
    text = text.strip().rstrip(".")
    for sep in (" — ", ". ", ": "):
        if sep in text:
            head, tail = text.split(sep, 1)
            break
    else:
        head, tail = text, ""
    for prefix in ("Careful, ", name + " "):
        if head.startswith(prefix):
            head = head[len(prefix):]
    return head[:1].upper() + head[1:], tail.rstrip(".")


def _by_role(team, override=None):
    out = {}
    for p in team:
        c = p.get("champ") or (p.get("hover") if p.get("is_me") else None)
        if c and p.get("role"):
            out.setdefault(p["role"], c)
    out.update(override or {})
    return out


def _duo(engine, profile, ally_at, enemy_at):
    """Bot lane is a 2v2: ADC vs ADC and support vs support matter most, cross pairs a bit."""
    a_adc, a_sup = ally_at.get("BOTTOM"), ally_at.get("UTILITY")
    e_adc, e_sup = enemy_at.get("BOTTOM"), enemy_at.get("UTILITY")
    pairs = [(a_adc, e_adc, 0.35, "BOTTOM"), (a_sup, e_sup, 0.35, "UTILITY"),
             (a_sup, e_adc, 0.15, "BOTTOM"), (a_adc, e_sup, 0.15, "BOTTOM")]
    tot = w = 0.0
    for a, e, weight, r in pairs:
        if a and e:
            tot += (engine.lane(a, e, profile, r)[0] - 0.5) * 2 * weight
            w += weight
    return round(tot / w, 2) if w else None
