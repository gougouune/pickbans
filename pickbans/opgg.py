"""Real stats from OP.GG's public MCP endpoint (no key needed).

Used by the data pipeline (tools/fetch_stats.py, ~250 calls once per patch) and lightly by the app
(a handful of calls to refresh tiers + your own champions). Keep the volume low: it's a free service.
"""
import json
import re
import time
import urllib.request

URL = "https://mcp-api.op.gg/mcp"
POS = {"TOP": "top", "JUNGLE": "jungle", "MIDDLE": "mid", "BOTTOM": "adc", "UTILITY": "support"}
TIER_LETTER = {0: "S", 1: "S", 2: "A", 3: "B", 4: "C", 5: "D"}


def call(tool, args, timeout=60):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": args}}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream", "User-Agent": "PICKBANS"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
    msg = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
    if "error" in msg:
        raise RuntimeError(str(msg["error"])[:200])
    res = msg["result"]
    text = res["content"][0]["text"]
    if res.get("isError"):
        raise RuntimeError(text[:200])
    return text


def api_name(champ):
    """'Renata Glasc' -> RENATA_GLASC, "Vel'Koz" -> VEL_KOZ (OP.GG wants UPPER_SNAKE_CASE)."""
    name = champ["name"].upper().replace("'", "").replace(".", "")  # Cho'Gath -> CHOGATH, Dr. Mundo -> DR_MUNDO
    return re.sub(r"[^A-Z0-9]+", "_", name).strip("_")


def safe_opponent(lane_ids, champions, not_this):
    """Any lane champion with a plain one-word name: the matchup-guide call needs a valid opponent name."""
    for cid in lane_ids:
        if cid != not_this and champions[cid]["name"].isalpha():
            return champions[cid]
    return champions[next(c for c in lane_ids if c != not_this)]


def name_variants(champ):
    seen = []
    for v in (api_name(champ), re.sub(r"[^A-Z0-9]+", "_", champ["name"].upper()).strip("_"),
              re.sub(r"[^A-Z0-9]", "", champ["name"].upper()), champ["id"].upper(),
              re.sub(r"(?<=[a-z])(?=[A-Z])", "_", champ["id"]).upper()):
        if v not in seen:
            seen.append(v)
    return seen


# ---------- compact "class Foo: a,b / Foo(1,2)" format ----------

def parse_compact(text):
    """OP.GG answers field-filtered calls in a compact class notation. Returns nested dicts/lists."""
    classes = {m.group(1): m.group(2).split(",") for m in re.finditer(r"^class (\w+): (.*)$", text, re.M)}
    body = text[text.rindex("\n\n") + 2:] if "\n\n" in text else text
    pos = 0

    def ws():
        nonlocal pos
        while pos < len(body) and body[pos] in " \n\t":
            pos += 1

    def value():
        nonlocal pos
        ws()
        c = body[pos]
        if c == '"':
            end = pos + 1
            while body[end] != '"' or body[end - 1] == "\\":
                end += 1
            s = json.loads(body[pos:end + 1])
            pos = end + 1
            return s
        if c == "[":
            pos += 1
            out = []
            ws()
            while body[pos] != "]":
                out.append(value())
                ws()
                if body[pos] == ",":
                    pos += 1
                ws()
            pos += 1
            return out
        m = re.compile(r"[A-Za-z_]\w*").match(body, pos)
        if m:
            word = m.group(0)
            pos = m.end()
            if pos < len(body) and body[pos] == "(":
                pos += 1
                args = []
                ws()
                while body[pos] != ")":
                    args.append(value())
                    ws()
                    if body[pos] == ",":
                        pos += 1
                    ws()
                pos += 1
                return dict(zip(classes.get(word, []), args))
            return {"null": None, "None": None, "true": True, "false": False, "True": True, "False": False}.get(word, word)
        m = re.compile(r"-?\d+(\.\d+)?([eE]-?\d+)?").match(body, pos)
        pos = m.end()
        return float(m.group(0)) if "." in m.group(0) or "e" in m.group(0).lower() else int(m.group(0))

    return value()


# ---------- the two calls PICKBANS needs ----------

_META_FIELDS = "champion,play,win_rate,pick_rate,ban_rate,role_rate,tier,rank,rank_prev_patch"


def lane_meta(resolve):
    """{role: {champ id: {wr, pr, br, rr, tier, rank, prev, play}}} for every lane, one call.
    resolve: champion display name -> champ id (or None)."""
    fields = [f"data.positions.{p}[].{{{_META_FIELDS}}}" for p in POS.values()]
    data = parse_compact(call("lol_list_lane_meta_champions", {"position": "all", "desired_output_fields": fields}))
    positions = data["data"]["positions"]
    out = {}
    for role, key in POS.items():
        out[role] = {}
        for row in positions.get(key) or []:
            cid = resolve(row["champion"])
            if cid:
                out[role][cid] = {"wr": row["win_rate"], "pr": row["pick_rate"], "br": row["ban_rate"], "rr": row["role_rate"],
                                  "tier": row["tier"], "rank": row["rank"], "prev": row["rank_prev_patch"], "play": row["play"]}
    return out


def matchup_table(champ, role, any_opponent, key_to_id):
    """{opponent id: [games, wins for `champ`]} — the champion's whole matchup table in that lane, one call."""
    last = None
    for name in name_variants(champ):
        try:
            text = call("lol_get_lane_matchup_guide", {"position": POS[role], "my_champion": name,
                                                       "opponent_champion": api_name(any_opponent)})
            data = json.loads(text)["data"]
            return {key_to_id[c["champion_id"]]: [c["play"], c["win"]]
                    for c in data.get("counters") or [] if c.get("champion_id") in key_to_id and c.get("play")}
        except Exception as e:  # wrong name variant, timeout…
            last = e
            time.sleep(0.5)
    raise RuntimeError(f"{champ['id']} {role}: {last}")


_RANK_FIELDS = [
    "data.summary.positions[].name",
    "data.summary.positions[].stats.{play,win_rate,pick_rate,ban_rate,role_rate}",
    "data.summary.positions[].stats.tier_data.{tier,rank,rank_prev_patch}",
    "data.weak_counters[].{champion_id,play,win}",
    "data.strong_counters[].{champion_id,play,win}",
]
_POS_NAME = {"TOP": "TOP", "JUNGLE": "JUNGLE", "MIDDLE": "MID", "BOTTOM": "ADC", "UTILITY": "SUPPORT"}


def rank_stats(champ, role, rank, key_to_id):
    """Stats for ONE rank (e.g. "gold"): lane win/pick/ban rate + tier, and the few head-to-heads OP.GG
    gives per rank (3 best + 3 worst). Returns (stat dict or None, {opponent id: [games, wins]})."""
    last = None
    for name in name_variants(champ):
        try:
            data = parse_compact(call("lol_get_champion_analysis", {
                "game_mode": "ranked", "champion": name, "position": POS[role], "tier": rank,
                "desired_output_fields": _RANK_FIELDS}))["data"]
            stat = None
            for pos in (data.get("summary") or {}).get("positions") or []:
                if pos.get("name") == _POS_NAME[role] and pos.get("stats"):
                    st, td = pos["stats"], pos["stats"].get("tier_data") or {}
                    stat = {"wr": st["win_rate"], "pr": st["pick_rate"], "br": st["ban_rate"], "rr": st["role_rate"],
                            "tier": td.get("tier", 4), "rank": td.get("rank", 99), "prev": td.get("rank_prev_patch"),
                            "play": st["play"]}
            pairs = {key_to_id[c["champion_id"]]: [c["play"], c["win"]]
                     for c in (data.get("weak_counters") or []) + (data.get("strong_counters") or [])
                     if c.get("champion_id") in key_to_id and c.get("play")}
            return stat, pairs
        except Exception as e:
            last = e
            time.sleep(0.5)
    raise RuntimeError(f"{champ['id']} {role} {rank}: {last}")
