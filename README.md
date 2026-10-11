# PICKBANS

League of Legends champ-select helper for beginners. No builds, no runes — just:

- **Ban recs** during the ban phase (what beats your pool, what you lose to, what's strong in your role — never what your team hovers)
- **Comfy / Ideal / Lane counter / Cheese** picks, each with an **S–D grade** + colored border, updating live on every pick, ban and hover
- **Playstyle** labels per champ (so you know which build to go get elsewhere)
- **Missing**: what your comp still lacks (engage, frontline, peel, CC, heals, waveclear, magic/physical damage)
- **Quick match assessment** when the draft locks: how the game will feel, traps to watch (e.g. *"Careful, Shen might randomly pull up bot lane with ult"*), your lane matchup, the plan

Read-only: it never clicks, locks or bans anything in the client.

## Use it

Double-click `dist\PICKBANS.exe`. A small window opens next to the client and connects by itself when League is running.
First launch: Windows may say "Windows protected your PC" → **More info → Run anyway** (the exe isn't code-signed).

No League open? Click **Try the demo** — a scripted champ select plays out.

## Dev

```
python -m pickbans            # run from source (opens the window)
python -m pickbans --demo     # start straight into the demo draft
python tools/try_engine.py    # print the engine's output for every step of the demo draft
python tools/build_pack.py    # rebuild pickbans/data/pack.json from tools/kb/*.txt + Riot's roster
powershell -ExecutionPolicy Bypass -File build.ps1   # build dist\PICKBANS.exe
```

Python 3.10+, standard library only (PyInstaller just for the .exe).

### Layout

| Path | What |
|---|---|
| `pickbans/app.py` | Main loop: watches the client, runs the engine, serves the UI, opens the window (Edge app mode) |
| `pickbans/lcu.py` | Read-only League client connection (finds port/token from the running process or the lockfile) |
| `pickbans/draft.py` | Raw champ-select session → simple draft dict; guesses enemy roles |
| `pickbans/engine.py` | Scoring + rec categories + grades + Missing + ban recs |
| `pickbans/assess.py` | Quick match assessment (template sentences + pack notes, no AI at runtime) |
| `pickbans/profile.py` | Your mastery, recent games, and a local log of your matchups (learns your real winrates) |
| `pickbans/pack.py` | Data pack load + auto-update on new patch (new champs get traits guessed from Riot tags) |
| `pickbans/demo.py` | Scripted fake champ select (real LCU-shaped sessions) |
| `pickbans/web/` | UI (plain HTML/CSS/JS) |
| `tools/kb/` | **The knowledge base** — edit these to improve recs |

User data lives in `%APPDATA%\PICKBANS\` (auto-updated pack, matchup history, log).
The running app serves its own log at `http://127.0.0.1:47800/api/log` — handy when the process that reads files sees a different AppData (e.g. tools launched from the packaged Claude desktop app).

Only one instance runs: launching again just reopens the window of the running one. `--port N` skips that check (dev).

`pickbans/live.py` reads Riot's Live Client Data API (`https://127.0.0.1:2999`, only during a game) for the in-game panel: clock, level-6 alerts, drake/baron timers, phase advice. It deliberately does NOT track enemy summoner/ability cooldowns.

### Knowledge base (`tools/kb/`)

- `champs.txt` — positions, damage type, playstyles, traits (EN engage, PE peel, CC, PO poke, DI dive, FR frontline, SU heals/shields, BU burst, DP sustained damage, TS tank shred, WC waveclear, MO mobility, SP split push, GL global, PI pick), scaling, difficulty
- `notes_*.txt` — lane counters (`weak_vs`), how to play, how to lane against, team-level "watch out"
- `meta.txt` — **baseline** tier list per role (not live stats yet)
- `cheese.txt` — off-meta picks and the conditions that trigger them

### Real stats (OP.GG)

`pickbans/opgg.py` talks to OP.GG's public MCP endpoint (`https://mcp-api.op.gg/mcp`, no key).

```
python tools/fetch_stats.py   # once per patch: lane tiers + every champion's matchup table (~270 calls, ~15 min, resumable)
python tools/build_pack.py    # merges tools/kb/stats.json into the pack
python tools/try_home.py      # offline check of the home screen data with a fake client
```

- `pack["stats"][role][champ]` = win/pick/ban rate, tier (1 = OP … 5 = weak), rank, previous-patch rank.
- `pack["matchups"][role][champ][opponent]` = `[games, wins]`. `Engine.pair()` reads it both ways and shrinks toward 50% on small samples.
- The hand-written `meta.txt` / `weak_vs` lists are only a fallback when a pair has no stats.
- The app itself only refreshes lane tiers (one call, at most every 3 days). Keep call volume low — it's a free service.

### Auto-update (distribution)

- `.github/workflows/update-pack.yml` runs daily on GitHub: `tools/publish_pack.py` refetches stats only on a new patch or after 3 days, then force-pushes `pack.json` + `manifest.json` + `stats.json` to the `data` branch (only when something changed).
- Every app reads `REMOTE_BASE/manifest.json` (see `pickbans/pack.py`) at launch and downloads `pack.json` only if it's newer. Host unreachable → keeps its pack.
- Plan B inside the app: lane tiers (1 OP.GG call / 3 days) and the matchup tables of the champions the user plays (`refresh_pool`, ≤ 8 calls) when the published pack is behind the live patch.
- New app version: bump `pickbans/__init__.py`, push a tag `vX.Y.Z` → `build-exe.yml` attaches `PICKBANS.exe` to a release; apps show "New version available".
- `python tools/try_update.py` checks the whole chain locally.

Home screen (`pickbans/home.py`): recent Summoner's Rift games, a matchup notebook per champion you play, did-you-know cards + quiz.

### Scoring (engine.py)

Each champ that fits your role gets 5 sub-scores (0–1): comfort (mastery + recent games + your winrate), meta tier, team fit (fills what's Missing), vs enemy comp (tanks → tank shred, dive → peel, poke → engage…), lane matchup. Weighted sum → grade S ≥ .76, A ≥ .66, B ≥ .56, C ≥ .46, else D. Lane weight goes up once your opponent is known.
