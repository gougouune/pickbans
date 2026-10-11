"""The live brain: scores every champion for your role and fills the rec categories.

Pure functions, no I/O — recomputed from scratch on every draft change (fast: ~170 champs).
"""
from .pack import ROLES

TIER_VALUE = {"S": 1.0, "A": 0.8, "B": 0.6, "C": 0.4, "D": 0.25}
GRADES = [(0.76, "S"), (0.66, "A"), (0.56, "B"), (0.46, "C"), (0.0, "D")]

# What a full team wants. trait -> (label, target total for 5 champions)
NEEDS = [
    ("EN", "Engage", 5),
    ("FR", "Frontline", 5),
    ("PE", "Peel", 4),
    ("CC", "Crowd control", 8),
    ("SU", "Heals / shields", 2),
    ("WC", "Waveclear", 5),
]

WEIGHTS = {"comfort": 0.30, "meta": 0.20, "team": 0.20, "enemy": 0.15, "lane": 0.15}
# once your lane opponent is known, the matchup matters more
WEIGHTS_OPP = {"comfort": 0.27, "meta": 0.16, "team": 0.17, "enemy": 0.15, "lane": 0.25}


# laning favors early champs a little
_EARLY = {"E": 1, "M": 0, "L": -1}
# OP.GG tiers: 1 = OP … 5 = weak
_TIER_LETTER = {0: "S", 1: "S", 2: "A", 3: "B", 4: "C", 5: "D"}


def grade(score):
    return next(g for t, g in GRADES if score >= t)


class Engine:
    def __init__(self, pack):
        self.pack = pack
        self.champs = pack["champions"]
        self.key_to_id = {c["key"]: cid for cid, c in self.champs.items()}

    # ---------- helpers ----------
    def t(self, cid, trait):
        return self.champs.get(cid, {}).get("traits", {}).get(trait, 0)

    def stat(self, cid, role):
        """Real lane stats (win/pick/ban rate, tier, rank) when the pack has them."""
        return self.pack.get("stats", {}).get(role, {}).get(cid)

    def tier(self, cid, role):
        c = self.champs.get(cid, {})
        if self.pack.get("stats"):
            s = self.stat(cid, role)
            if s:
                return _TIER_LETTER.get(s["tier"], "C")
            return "C" if role in c.get("positions", []) else "D"
        if role not in c.get("positions", []):
            return "D"
        return self.pack["meta"].get(role, {}).get(cid, "B")

    def role_ok(self, cid, role, profile):
        return role in self.champs[cid]["positions"] or bool(self.stat(cid, role)) or profile.played_in(cid, role) >= 2

    def role_rate(self, cid, role):
        """How likely this champion is in this lane (0..1) — stats first, knowledge base as fallback."""
        s = self.stat(cid, role)
        if s:
            return max(0.05, s["rr"] * min(1.0, s["pr"] * 20 + 0.2))
        pos = self.champs.get(cid, {}).get("positions", [])
        return (0.5, 0.2, 0.08)[pos.index(role)] if role in pos[:3] else 0.0

    def _table(self, key, role, a, b):
        table = self.pack.get(key, {}).get(role, {})
        if b in table.get(a, {}):
            games, wins = table[a][b]
            return games, wins
        if a in table.get(b, {}):
            games, wins = table[b][a]
            return games, games - wins
        return None

    def pair(self, role, a, b):
        """(win rate of a vs b in that lane, games) from real stats, or None.
        Base = the full table (Emerald+), shrunk toward 50% on small samples. When the pack also has a
        head-to-head at the target rank (Gold), it pulls the number toward what happens at that rank."""
        base = self._table("matchups", role, a, b)
        rank = self._table("matchups_rank", role, a, b)
        if base and base[0] >= 30:
            wr, games = (base[1] + 100) / (base[0] + 200), base[0]
        elif rank:
            wr, games = 0.5, 0
        else:
            return None
        if rank:
            wr = (rank[1] + wr * 150) / (rank[0] + 150)
            games += rank[0]
        return wr, games

    def totals(self, ids, hovers=()):
        tot = {}
        for cid, w in [(c, 1.0) for c in ids] + [(c, 0.6) for c in hovers]:
            for k, v in self.champs.get(cid, {}).get("traits", {}).items():
                tot[k] = tot.get(k, 0) + v * w
        return tot

    # ---------- team analysis ----------
    def missing(self, ally_ids, hovers=()):
        tot = self.totals(ally_ids, hovers)
        filled = len(ally_ids) + 0.6 * len(hovers)
        out = []
        for trait, label, target in NEEDS:
            have = tot.get(trait, 0)
            out.append({"trait": trait, "label": label, "have": round(have, 1), "target": target,
                        "ratio": round(min(1.0, have / target), 2)})
        for m in out:
            m["missing"] = filled >= 1 and m["ratio"] < 0.5
        dmg = self.damage_mix(list(ally_ids) + list(hovers))
        if filled >= 2 and dmg["AP"] == 0:
            out.append({"trait": "AP", "label": "Magic damage", "have": 0, "target": 1, "ratio": 0, "missing": True})
        if filled >= 2 and dmg["AD"] == 0:
            out.append({"trait": "AD", "label": "Physical damage", "have": 0, "target": 1, "ratio": 0, "missing": True})
        return out

    def damage_mix(self, ids):
        mix = {"AD": 0.0, "AP": 0.0}
        for cid in ids:
            d = self.champs.get(cid, {}).get("dmg", "AD")
            if d == "MIX":
                mix["AD"] += 0.5
                mix["AP"] += 0.5
            else:
                mix[d] += 1
        return mix

    def enemy_profile(self, enemy_ids):
        tot = self.totals(enemy_ids)
        n = len(enemy_ids)
        tanks = sum(1 for c in enemy_ids if self.t(c, "FR") >= 3)
        melee = sum(1 for c in enemy_ids if self.champs.get(c, {}).get("range") == "M")
        tags = []
        if tanks >= 3:
            tags.append(f"{tanks} tanks")
        if tot.get("DI", 0) + tot.get("BU", 0) * 0.5 >= 8:
            tags.append("Heavy dive / burst")
        if tot.get("PO", 0) >= 6:
            tags.append("Poke")
        if tot.get("EN", 0) >= 7:
            tags.append("Lots of engage")
        if tot.get("SU", 0) >= 4:
            tags.append("Lots of heals")
        if n >= 3 and tot.get("CC", 0) <= 3:
            tags.append("Low CC")
        if n >= 4 and tot.get("FR", 0) <= 3:
            tags.append("Squishy")
        dmg = self.damage_mix(enemy_ids)
        if n >= 3 and dmg["AP"] <= 0.5:
            tags.append("Almost all AD")
        if n >= 3 and dmg["AD"] <= 0.5:
            tags.append("Almost all AP")
        return {"tot": tot, "n": n, "tanks": tanks, "melee": melee, "tags": tags}

    # ---------- scoring ----------
    def team_fit(self, cid, ally_ids, hovers):
        if not ally_ids and not hovers:
            return 0.5, None
        tot = self.totals(ally_ids, hovers)
        gain = 0.0
        best_label, best_gain = None, 0
        for trait, label, target in NEEDS:
            gap = max(0.0, target - tot.get(trait, 0))
            g = min(gap, self.t(cid, trait))
            gain += g
            if g > best_gain:
                best_label, best_gain = label, g
        dmg = self.damage_mix(ally_ids)
        mine = self.champs[cid]["dmg"]
        if len(ally_ids) >= 2:
            if dmg["AP"] == 0 and mine in ("AP", "MIX"):
                gain += 2
                best_label = best_label or "Magic damage"
            if dmg["AD"] == 0 and mine in ("AD", "MIX"):
                gain += 2
                best_label = best_label or "Physical damage"
        score = min(1.0, 0.25 + gain / 7)
        return score, (best_label if best_gain >= 2 or best_label in ("Magic damage", "Physical damage") else None)

    def vs_enemy(self, cid, ep):
        if ep["n"] == 0:
            return 0.5, None
        t = lambda k: self.t(cid, k)
        tot = ep["tot"]
        s, why = 0.0, []
        if ep["tanks"] >= 2:
            s += 0.07 * t("TS") * (ep["tanks"] - 1)
            if t("TS") >= 2:
                why.append((0.07 * t("TS") * (ep["tanks"] - 1), f"Shreds tanks — they have {ep['tanks']}"))
        dive = tot.get("DI", 0) + tot.get("BU", 0) * 0.5
        if dive >= 6:
            s += 0.05 * (t("PE") + t("FR"))
            if self.champs[cid]["range"] == "R" and t("MO") <= 1 and t("PE") == 0:
                s -= 0.12
            if t("PE") >= 2:
                why.append((0.05 * t("PE"), "Peel vs their divers"))
        if tot.get("PO", 0) >= 5:
            s += 0.05 * (t("EN") + t("SU"))
            if t("EN") >= 2:
                why.append((0.1, "Engage beats their poke"))
        if tot.get("EN", 0) >= 6:
            s += 0.05 * t("PE")
        if ep["n"] >= 3 and tot.get("FR", 0) <= 3:
            s += 0.05 * (t("BU") + t("PI") + t("DI")) / 1.5
            if t("BU") + t("PI") >= 4:
                why.append((0.1, "Their team is squishy"))
        if ep["n"] >= 3 and tot.get("CC", 0) <= 3 and t("DP") >= 3:
            s += 0.1
            why.append((0.1, "They have little CC to stop you"))
        why.sort(key=lambda x: -x[0])
        return max(0.0, min(1.0, 0.5 + s)), (why[0][1] if why else None)

    def lane(self, cid, opp, profile, role=None):
        if not opp or cid not in self.champs:
            return 0.5, None
        c, o = self.champs[cid], self.champs.get(opp, {})
        s, why = 0.0, None
        role = role or c["positions"][0]
        real = self.pair(role, cid, opp)
        if real:  # real head-to-head win rate beats anything hand-written
            wr, games = real
            s += max(-0.42, min(0.42, (wr - 0.5) * 7))
            if wr >= 0.52:
                why = f"Wins {round(wr * 100)}% vs {o.get('name', opp)}"
            elif wr <= 0.48:
                why = f"Only {round(wr * 100)}% vs {o.get('name', opp)}"
        else:
            if cid in o.get("weak_vs", []):
                s += 0.25
                why = f"Counters {o.get('name', opp)}"
            if opp in c.get("weak_vs", []):
                s -= 0.25
                why = f"Hard matchup vs {o.get('name', opp)}"
            if role in ("TOP", "MIDDLE") and c["range"] != o.get("range"):
                s += 0.08 if c["range"] == "R" else -0.08
            if role != "JUNGLE":
                s += 0.05 * (_EARLY.get(c["scaling"], 0) - _EARLY.get(o.get("scaling"), 0))
        w, g = profile.matchup(cid, opp)
        if g >= 2:
            s += (w / g - 0.5) * 0.4
            if w / g >= 0.6:
                why = why or f"You win this matchup ({w}/{g})"
        return max(0.0, min(1.0, 0.5 + s)), why

    def score(self, cid, ctx):
        role, profile = ctx["role"], ctx["profile"]
        comfort = profile.comfort(cid)
        tier = self.tier(cid, role)
        meta = TIER_VALUE[tier]
        team, team_why = self.team_fit(cid, ctx["allies"], ctx["hovers"])
        enemy, enemy_why = self.vs_enemy(cid, ctx["ep"])
        lane, lane_why = self.lane(cid, ctx["opp"], profile, role)
        parts = {"comfort": comfort, "meta": meta, "team": team, "enemy": enemy, "lane": lane}
        weights = WEIGHTS_OPP if ctx["opp"] else WEIGHTS
        total = sum(weights[k] * v for k, v in parts.items())
        if self.champs[cid]["difficulty"] >= 3 and comfort < 0.25:
            total -= 0.06
        if ctx["no_profile"]:
            total += 0.04 * (2 - self.champs[cid]["difficulty"])
        reasons = []
        rec = profile.games.get(cid)
        if comfort >= 0.4:
            reasons.append(f"You play it a lot ({rec['games']} recent games)" if rec and rec["games"] >= 3 else "High mastery")
        for w in (lane_why, team_why and f"Adds {team_why.lower()} your team lacks", enemy_why):
            if w:
                reasons.append(w)
        if tier == "S":
            st = self.stat(cid, role)
            reasons.append(f"S tier this patch ({round(st['wr'] * 100)}% wins)" if st else "Strong pick in this role")
        elif tier in ("C", "D") and comfort < 0.4:
            reasons.append("Weaker in this role right now")
        wr = profile.winrate(cid)
        if wr is not None and wr >= 0.6:
            reasons.append(f"You win {round(wr * 100)}% on it")
        if ctx["no_profile"] and self.champs[cid]["difficulty"] == 1:
            reasons.append("Easy to learn")
        return {"id": cid, "score": round(total, 3), "grade": grade(total), "parts": {k: round(v, 2) for k, v in parts.items()},
                "tier": tier, "reasons": reasons[:3]}

    # ---------- the main call ----------
    def recommend(self, draft, profile):
        role = draft.get("my_role") or profile.main_role() or "MIDDLE"
        allies = [a["champ"] for a in draft["allies"] if a["champ"] and not a["is_me"]]
        hovers = [a["hover"] for a in draft["allies"] if a["hover"] and not a["is_me"]]
        enemies = [e["champ"] for e in draft["enemies"] if e["champ"]]
        opp = next((e["champ"] for e in draft["enemies"] if e["champ"] and e.get("role") == role), None)
        me = next((a for a in draft["allies"] if a["is_me"]), {})
        taken = set(allies) | set(enemies) | set(draft["bans"]) | set(hovers)
        no_profile = not profile.mastery and not profile.games
        ctx = {"role": role, "profile": profile, "allies": allies, "hovers": hovers, "opp": opp,
               "ep": self.enemy_profile(enemies), "no_profile": no_profile}

        pool = [cid for cid in self.champs if cid not in taken and profile.owns(cid) and self.role_ok(cid, role, profile)]
        scored = {cid: self.score(cid, ctx) for cid in pool}
        by = lambda key: sorted(scored.values(), key=key, reverse=True)

        if no_profile:
            comfy = by(lambda r: r["parts"]["meta"] * 0.5 + (0.5 if self.champs[r["id"]]["difficulty"] == 1 else 0) + r["score"] * 0.2)[:3]
        else:
            comfy = [r for r in by(lambda r: r["parts"]["comfort"]) if r["parts"]["comfort"] > 0.05][:3]
        ideal = by(lambda r: r["score"])[:3]
        counter = []
        if opp:
            counter = [r for r in by(lambda r: r["parts"]["lane"] * 0.6 + r["parts"]["comfort"] * 0.2 + r["parts"]["meta"] * 0.2)
                       if r["parts"]["lane"] > 0.55][:3]

        my_champ = me.get("champ")
        return {
            "role": role,
            "role_guessed": not draft.get("my_role"),
            "opponent": opp,
            "comfy": comfy,
            "ideal": ideal,
            "counter": counter,
            "cheese": self.cheese(role, ctx, taken, draft["bans"], profile),
            "bans": self.ban_recs(role, draft, profile, comfy, hovers),
            "missing": self.missing(allies + ([my_champ] if my_champ else []), hovers + ([me.get("hover")] if me.get("hover") else [])),
            "enemy_tags": ctx["ep"]["tags"],
            "my_pick": self.my_pick(my_champ or me.get("hover"), opp, ctx) if (my_champ or me.get("hover")) else None,
        }

    def cheese(self, role, ctx, taken, bans, profile):
        ep = ctx["ep"]
        tot = ep["tot"]
        out = []
        banned_marksmen = sum(1 for b in bans if "Marksman" in self.champs.get(b, {}).get("tags", []))
        cond = {
            "always": True,
            "no_tanks": ep["n"] >= 3 and ep["tanks"] <= 1,
            "many_tanks": ep["tanks"] >= 3,
            "all_melee": ep["n"] >= 3 and ep["melee"] >= min(4, ep["n"]),
            "squishy": ep["n"] >= 3 and tot.get("FR", 0) <= 3,
            "no_cc": ep["n"] >= 3 and tot.get("CC", 0) <= 3,
            "class_banned:Marksman": banned_marksmen >= 3,
        }
        for c in self.pack["cheese"]:
            if c["role"] != role or c["id"] in taken or not profile.owns(c["id"]):
                continue
            if not cond.get(c["trigger"], False):
                continue
            r = self.score(c["id"], ctx)
            if c["trigger"] == "always" and r["score"] < 0.5:
                continue
            r["reasons"] = [c["why"]] + [x for x in r["reasons"] if x != c["why"]][:1]
            r["special"] = c["trigger"] != "always"
            out.append(r)
        # dynamic: off-meta champ their comp really hates
        for cid in self.champs:
            if cid in taken or not self.role_ok(cid, role, profile) or not profile.owns(cid):
                continue
            if self.tier(cid, role) in ("C", "D") and ep["n"] >= 3:
                e, why = self.vs_enemy(cid, ep)
                if e >= 0.75 and why:
                    r = self.score(cid, ctx)
                    if r["score"] < GRADES[3][0]:
                        continue
                    r["reasons"] = [f"Off-meta, but {why[0].lower() + why[1:]}"]
                    r["special"] = True
                    out.append(r)
        out.sort(key=lambda r: (r.get("special", False), r["score"]), reverse=True)
        seen, res = set(), []
        for r in out:
            if r["id"] not in seen:
                seen.add(r["id"])
                res.append(r)
        return res[:2]

    def ban_recs(self, role, draft, profile, comfy, hovers):
        banned = set(draft["bans"])
        picked = {a["champ"] for a in draft["allies"] if a["champ"]} | {e["champ"] for e in draft["enemies"] if e["champ"]}
        protect = set(hovers) | {a["hover"] for a in draft["allies"] if a["hover"]} | {r["id"] for r in comfy}
        worst = dict(profile.worst_matchups())
        pool_ids = [r["id"] for r in comfy]
        out = []
        for cid, c in self.champs.items():
            if cid in banned or cid in picked or cid in protect:
                continue
            st = self.stat(cid, role)
            in_lane = bool(st) or role in c["positions"][:2]
            s, why = 0.0, None
            if in_lane:
                tv = TIER_VALUE[self.tier(cid, role)]
                s += 0.5 * tv
                if st:
                    s += min(0.15, st["pr"] * 1.5)  # popular = you'll actually face it
                if tv >= 1.0:
                    why = "S tier in your role" + (f" ({round(st['wr'] * 100)}% wins)" if st else "")
                # how badly does it beat the champs you play?
                for p in pool_ids:
                    real = self.pair(role, p, cid)
                    if real and real[0] <= 0.475:
                        s += (0.5 - real[0]) * 6
                        why = f"Your {self.champs[p]['name']} only wins {round(real[0] * 100)}% vs it"
                    elif not real and cid in self.champs[p].get("weak_vs", []):
                        s += 0.2
                        why = why or f"Counters your {self.champs[p]['name']}"
            if cid in worst:
                s += 0.5
                why = f"You lose to it ({round(worst[cid] * 100)}% wins)"
            if s >= 0.5:
                out.append({"id": cid, "score": round(s, 2), "reasons": [why or "Strong in your role"]})
        out.sort(key=lambda r: -r["score"])
        return out[:3]

    def my_pick(self, cid, opp, ctx):
        c = self.champs.get(cid)
        if not c:
            return None
        lane, lane_why = self.lane(cid, opp, ctx["profile"], ctx["role"])
        return {"id": cid, "styles": c["styles"], "play": c.get("play", ""),
                "vs": self.champs.get(opp, {}).get("vs", "") if opp else "",
                "lane": round(lane, 2), "lane_why": lane_why}


def role_label(role):
    return {"TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid", "BOTTOM": "Bot", "UTILITY": "Support"}.get(role, role or "?")


__all__ = ["Engine", "ROLES", "grade", "role_label"]
