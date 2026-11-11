"""Post-match breakdown: what the numbers say about YOUR game, no opinions.

Reads the finished game from the client (stats per player, plus the minute-by-minute timeline when available),
compares it with a rough Gold benchmark and with your own recent games, and turns the gaps into a few short tips.
Every input is optional: whatever the client doesn't give us is skipped instead of guessed.
"""
import time

# Rough "typical Gold" numbers per role, written by hand (not from stats).
BENCH = {
    "TOP":     {"cs_pm": 5.8, "vis_pm": 0.70, "kp": 0.50},
    "JUNGLE":  {"cs_pm": 5.0, "vis_pm": 1.00, "kp": 0.62},
    "MIDDLE":  {"cs_pm": 6.2, "vis_pm": 0.70, "kp": 0.55},
    "BOTTOM":  {"cs_pm": 6.3, "vis_pm": 0.65, "kp": 0.60},
    "UTILITY": {"cs_pm": 0.8, "vis_pm": 1.80, "kp": 0.62},
}
DEATHS_PM_OK, DEATHS_PM_BAD = 0.25, 0.33      # per minute: ~7 deaths in 28 min is normal, 9+ is a lot
MAP_MIDPOINT = 14900                          # x + y of the map's diagonal: blue side below it, red side above
WINDOWS = ["0-10", "10-20", "20-30", "30-end"]
ROLE_NAME = {"TOP": "top", "JUNGLE": "jungle", "MIDDLE": "mid", "BOTTOM": "ADC", "UTILITY": "support"}


def _num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _fmt_t(sec):
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


# ---------------------------------------------------------------- metrics (one game, one player)

def metrics_of(detail, champ_key):
    """Numbers for your participant. None if the game can't be read."""
    parts = (detail or {}).get("participants") or []
    mine = next((p for p in parts if p.get("championId") == champ_key), None)
    if not mine:
        return None
    st = mine.get("stats") or {}
    dur = _num(detail.get("gameDuration"))
    if dur > 10000:   # some client versions give milliseconds
        dur /= 1000
    if dur < 300:      # a remake or an unreadable game: nothing meaningful to say
        return None
    mins = max(dur / 60, 1.0)
    team = [p for p in parts if p.get("teamId") == mine.get("teamId")]
    team_k = sum(_num((p.get("stats") or {}).get("kills")) for p in team)
    team_dmg = sum(_num((p.get("stats") or {}).get("totalDamageDealtToChampions")) for p in team)
    k, d, a = (int(_num(st.get(x))) for x in ("kills", "deaths", "assists"))
    cs = int(_num(st.get("totalMinionsKilled")) + _num(st.get("neutralMinionsKilled")))
    tl = mine.get("timeline") or {}
    dmg = _num(st.get("totalDamageDealtToChampions"))
    return {
        "dur": int(dur), "win": bool(st.get("win")), "pid": mine.get("participantId"), "team": mine.get("teamId"),
        "k": k, "d": d, "a": a, "cs": cs, "cs_pm": round(cs / mins, 2),
        "vis": int(_num(st.get("visionScore"))), "vis_pm": round(_num(st.get("visionScore")) / mins, 2),
        "wards": int(_num(st.get("wardsPlaced"))), "wards_pm": round(_num(st.get("wardsPlaced")) / mins, 2),
        "wk": int(_num(st.get("wardsKilled"))), "cw": int(_num(st.get("visionWardsBoughtInGame"))),
        "deaths_pm": round(d / mins, 3),
        "kp": round((k + a) / team_k, 2) if team_k else None,
        "dmg_share": round(dmg / team_dmg, 2) if team_dmg else None,
        "role": _role_of_timeline(tl),
        "cs_delta": tl.get("creepsPerMinDeltas") or {}, "csd_delta": tl.get("csDiffPerMinDeltas") or {},
        "xpd_delta": tl.get("xpDiffPerMinDeltas") or {},
    }


def _role_of_timeline(tl):
    lane, role = (tl.get("lane") or "").upper(), (tl.get("role") or "").upper()
    if lane == "BOTTOM" and "SUPPORT" in role:
        return "UTILITY"
    return {"TOP": "TOP", "JUNGLE": "JUNGLE", "MIDDLE": "MIDDLE", "MID": "MIDDLE", "BOTTOM": "BOTTOM", "BOT": "BOTTOM"}.get(lane)


COMPACT = ("dur", "win", "k", "d", "a", "cs_pm", "vis_pm", "wards_pm", "cw", "deaths_pm", "kp", "dmg_share", "role")


def compact(m):
    """What we keep per game in history.json (small, no per-minute arrays)."""
    return {k: m.get(k) for k in COMPACT}


# ---------------------------------------------------------------- timeline events (optional)

def events_of(timeline, pid):
    """Deaths / kills / wards of ONE player from the minute-by-minute timeline. Empty lists if it isn't readable."""
    deaths, kills, wards = [], [], []
    try:
        for f in (timeline or {}).get("frames") or []:
            for e in f.get("events") or []:
                t, typ = _num(e.get("timestamp")) / 1000, e.get("type")
                pos = e.get("position") or {}
                if typ == "CHAMPION_KILL":
                    if e.get("victimId") == pid:
                        deaths.append({"t": t, "x": pos.get("x"), "y": pos.get("y")})
                    elif e.get("killerId") == pid or pid in (e.get("assistingParticipantIds") or []):
                        kills.append({"t": t})
                elif typ == "WARD_PLACED" and e.get("creatorId") == pid and e.get("wardType") not in ("UNDEFINED", "BLUE_TRINKET_TEST"):
                    wards.append({"t": t})
    except (TypeError, AttributeError):
        return [], [], []
    return deaths, kills, wards


def _enemy_half(team_id, x, y):
    if x is None or y is None:
        return None
    return (x + y > MAP_MIDPOINT) if team_id == 100 else (x + y < MAP_MIDPOINT)


def _window(t):
    return 0 if t < 600 else 1 if t < 1200 else 2 if t < 1800 else 3


# ---------------------------------------------------------------- the analysis

def _avg(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def trend(history, current):
    """Last 5 games vs the 5 before, per stat, for the same role. 'better' / 'worse' / 'same'."""
    rows = [h["m"] for h in history if isinstance(h.get("m"), dict) and h["m"].get("role") == current.get("role")]
    rows = [compact(current)] + rows
    last, prev = rows[:5], rows[5:10]
    if len(last) < 3 or len(prev) < 3:
        return []
    out = []
    for key, label, low_is_good, digits in (("deaths_pm", "Deaths / min", True, 2), ("vis_pm", "Vision / min", False, 2),
                                            ("cs_pm", "CS / min", False, 1), ("kp", "Kill participation", False, 2)):
        if key == "cs_pm" and current.get("role") == "UTILITY":
            continue
        a, b = _avg([r.get(key) for r in last]), _avg([r.get(key) for r in prev])
        if a is None or b is None or b == 0:
            continue
        change = (a - b) / b
        better = (change < -0.05) if low_is_good else (change > 0.05)
        worse = (change > 0.05) if low_is_good else (change < -0.05)
        out.append({"label": label, "now": round(a * (100 if key == "kp" else 1), digits if key != "kp" else 0),
                    "before": round(b * (100 if key == "kp" else 1), digits if key != "kp" else 0),
                    "pct": key == "kp", "state": "better" if better else "worse" if worse else "same"})
    return out


def analyze(m, role, history=(), deaths=(), wards=()):
    """m = metrics_of(...). Returns {tiles, findings, phases, trend, has_timeline}."""
    role = role if role in BENCH else (m.get("role") if m.get("role") in BENCH else "MIDDLE")
    bench, mins = BENCH[role], max(m["dur"] / 60, 1)
    same_role = [h["m"] for h in history if isinstance(h.get("m"), dict) and h["m"].get("role") == role]
    mine = lambda key: _avg([r.get(key) for r in same_role[:10]])

    # ---------- tiles ----------
    def rel_state(value, ref, higher_is_better=True):
        if value is None:
            return "ok"
        r = value / ref if ref else 1
        return ("good" if r >= 1.0 else "ok" if r >= 0.85 else "bad") if higher_is_better else ("good" if r <= 1.0 else "ok" if r <= 1.3 else "bad")

    tiles = []
    if role != "UTILITY":
        tiles.append({"key": "cs", "label": "CS / min", "value": m["cs_pm"], "bench": bench["cs_pm"], "avg": _r(mine("cs_pm")),
                      "state": rel_state(m["cs_pm"], bench["cs_pm"])})
    tiles.append({"key": "vis", "label": "Vision / min", "value": m["vis_pm"], "bench": bench["vis_pm"], "avg": _r(mine("vis_pm")),
                  "state": rel_state(m["vis_pm"], bench["vis_pm"])})
    tiles.append({"key": "deaths", "label": "Deaths", "value": m["d"], "bench": round(DEATHS_PM_OK * mins), "avg": _r(mine("d"), 1),
                  "state": rel_state(m["deaths_pm"], DEATHS_PM_OK, higher_is_better=False), "sub": f"{m['deaths_pm']:.2f} / min"})
    if m.get("kp") is not None:
        tiles.append({"key": "kp", "label": "Kill participation", "value": round(m["kp"] * 100), "bench": round(bench["kp"] * 100),
                      "avg": _r(mine("kp") * 100 if mine("kp") is not None else None), "pct": True,
                      "state": rel_state(m["kp"], bench["kp"])})
    if role in ("MIDDLE", "BOTTOM", "TOP") and m.get("dmg_share") is not None and len(tiles) < 5:
        tiles.append({"key": "dmg", "label": "Damage share", "value": round(m["dmg_share"] * 100), "bench": 20, "pct": True,
                      "avg": _r(mine("dmg_share") * 100 if mine("dmg_share") is not None else None),
                      "state": rel_state(m["dmg_share"], 0.20)})

    # ---------- findings (severity = how far off, so the worst come first) ----------
    bad, good = [], []

    def add(kind, sev, title, text):
        (bad if kind == "bad" else good).append({"kind": kind, "sev": sev, "title": title, "text": text})

    d_list = list(deaths)
    early = [x for x in d_list if x["t"] < 600]
    half = [x for x in d_list if _enemy_half(m.get("team"), x.get("x"), x.get("y")) is True]
    own = [x for x in d_list if _enemy_half(m.get("team"), x.get("x"), x.get("y")) is False]
    positions = [x for x in d_list if x.get("x") is not None]

    if len(early) >= 2 and role != "JUNGLE":
        add("bad", 3 + len(early), "Too aggressive early",
            f"{len(early)} deaths before 10:00 ({', '.join(_fmt_t(x['t']) for x in early[:3])}). Trade less in the first levels and "
            f"keep your summoners for when it matters.")
    if len(positions) >= 3 and len(half) / len(positions) >= 0.5:
        add("bad", 3 + len(half), "Overextending",
            f"{len(half)} of your {len(d_list)} deaths happened on the enemy side of the map. Stop chasing past your vision, "
            f"and back off when you lose track of their jungler.")
    if len(positions) >= 3 and len(own) >= 3 and len(own) / len(positions) >= 0.4:
        add("bad", 2 + len(own), "Check your map",
            f"{len(own)} deaths came on your own side of the map: usually a gank you didn't see. Glance at the minimap every "
            f"few seconds and ward the paths into your lane.")
    if m["deaths_pm"] >= DEATHS_PM_BAD and not (early or half):
        add("bad", 2 + m["deaths_pm"] * 10, "Too many deaths",
            f"{m['d']} deaths in {mins:.0f} min ({m['deaths_pm']:.2f}/min, normal is about {DEATHS_PM_OK}). Every death is gold and tempo "
            f"for them: play one step safer when you're ahead or when your jungler is missing.")
    if not positions and m["d"] >= 6 and m["vis_pm"] < bench["vis_pm"] * 0.7:
        add("bad", 3, "Check your map", f"{m['d']} deaths with low vision: you're probably getting caught. Look at the minimap more and ward before you step up.")

    low_vision = m["vis_pm"] < bench["vis_pm"] * 0.75
    if low_vision:
        add("bad", 2 + (1 - m["vis_pm"] / bench["vis_pm"]) * 4, "Not enough wards",
            f"{m['vis_pm']:.1f} vision/min ({m['vis']} total), typical for {ROLE_NAME[role]} in Gold is about {bench['vis_pm']}. "
            f"Place your trinket every time it's up and buy a Control Ward on each back.")
    if m["cw"] == 0 and role in ("UTILITY", "JUNGLE") and mins >= 15:
        add("bad", 2.5, "No Control Wards", "You bought 0 Control Wards. One per back is the cheapest way to avoid getting ganked.")
    elif m["cw"] >= 5 and not low_vision:
        add("good", 1, "Good vision", f"{m['vis']} vision score and {m['cw']} Control Wards bought.")

    if role != "UTILITY":
        if m["cs_pm"] < bench["cs_pm"] * 0.85:
            add("bad", 2 + (1 - m["cs_pm"] / bench["cs_pm"]) * 5, "Low farm",
                f"{m['cs_pm']:.1f} CS/min vs about {bench['cs_pm']} typical. Last-hit more and use dead time between fights to take waves/camps.")
        elif m["cs_pm"] >= bench["cs_pm"] * 1.08:
            add("good", 1.5, "Great farm", f"{m['cs_pm']:.1f} CS/min is above the Gold average ({bench['cs_pm']}).")
        cs_d = m.get("cs_delta") or {}
        w1, w2, w3 = (_num(cs_d.get(k), None) for k in ("10-20", "20-30", "0-10"))
        if w1 is not None and w2 is not None and w2 < w1 - 1.2 and m["dur"] >= 1500:
            add("bad", 2, "Farm drops after laning", f"{w1:.1f} CS/min from 10 to 20, then {w2:.1f} from 20 to 30. Keep farming side waves between fights.")
        diff = _num((m.get("csd_delta") or {}).get("0-10"), None)
        if diff is not None and diff <= -0.7:
            add("bad", 2.5, "Behind in lane early", f"About {abs(diff) * 10:.0f} fewer CS than your lane opponent at 10 minutes. Back earlier, take safer trades.")
        elif diff is not None and diff >= 0.7:
            add("good", 1.5, "Won your lane", f"About {diff * 10:.0f} more CS than your lane opponent at 10 minutes.")

    if m.get("kp") is not None and m["kp"] < 0.40 and role in ("JUNGLE", "UTILITY", "MIDDLE") and mins >= 15:
        add("bad", 2, "Not in the fights", f"Kill participation {round(m['kp'] * 100)}%: you were away from most fights. Group earlier for drakes and teamfights.")
    elif m.get("kp") is not None and m["kp"] >= 0.70:
        add("good", 1.5, "Always there", f"Kill participation {round(m['kp'] * 100)}%.")
    if role in ("MIDDLE", "BOTTOM") and m.get("dmg_share") is not None and m["dmg_share"] < 0.16 and mins >= 15:
        add("bad", 1.5, "Low damage for a carry", f"Only {round(m['dmg_share'] * 100)}% of your team's damage. Stay in fights longer, position to keep hitting.")
    if m["deaths_pm"] <= 0.15 and mins >= 20:
        add("good", 2, "Clean game", f"Only {m['d']} deaths in {mins:.0f} minutes.")

    bad.sort(key=lambda f: -f["sev"])
    good.sort(key=lambda f: -f["sev"])
    findings = [{k: v for k, v in f.items() if k != "sev"} for f in bad[:3] + good[:2 if len(bad) < 3 else 1]]

    # ---------- the game over time ----------
    phases = []
    cs_d = m.get("cs_delta") or {}
    for i, name in enumerate(WINDOWS):
        if i * 600 >= m["dur"]:
            break
        row = {"label": name.replace("-end", "+").replace("-", "–"), "cs": None if role == "UTILITY" else _r(_num(cs_d.get(name), None)),
               "deaths": sum(1 for x in d_list if _window(x["t"]) == i) if d_list else None,
               "wards": sum(1 for x in wards if _window(x["t"]) == i) if wards else None}
        if row["cs"] is not None or row["deaths"] is not None:
            phases.append(row)

    return {"tiles": tiles, "findings": findings, "phases": phases, "role": role,
            "trend": trend(history, dict(compact(m), role=role)), "has_timeline": bool(d_list or wards)}


def _r(x, digits=1):
    return None if x is None else round(x, digits)


def build(detail, timeline, champ_key, champ_id, role, history, game_id=None):
    """The whole breakdown for the finished game, or None if it can't be read."""
    m = metrics_of(detail, champ_key)
    if not m:
        return None
    deaths, kills, wards = events_of(timeline, m["pid"])
    role = m.get("role") or role
    if not role:        # modes without lanes (Swiftplay): benchmarks per role would be wrong, say nothing
        return None
    out = analyze(m, role, history, deaths, wards)
    out.update({"game_id": game_id, "champ": champ_id, "win": m["win"], "dur": m["dur"], "k": m["k"], "d": m["d"], "a": m["a"],
                "at": int(time.time())})
    return out
