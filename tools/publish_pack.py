"""Build the data pack that every installed app downloads (run by .github/workflows/update-pack.yml).

python tools/publish_pack.py --out public [--previous previous] [--max-age-days 3] [--no-fetch]

--previous: folder holding what is currently published (pack.json, stats.json). Used to keep stats between
            runs and to avoid republishing when nothing changed (apps only download when built_at moves).
Writes  out/pack.json (minified)  out/manifest.json (tiny, checked at every app launch)  out/stats.json (cache).
"""
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pickbans import __version__  # noqa: E402
from pickbans.pack import build_pack  # noqa: E402

APP_URL = "https://github.com/gougouune/pickbans/releases/latest"
KB = os.path.join(ROOT, "tools", "kb")


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


out = arg("--out", os.path.join(ROOT, "public"))
previous = arg("--previous")
stats_path = os.path.join(KB, "stats.json")

# 1. start from the freshest stats we have (repo seed vs what's published)
prev_stats = load(os.path.join(previous, "stats.json")) if previous else None
seed = load(stats_path)
if prev_stats and (not seed or prev_stats.get("fetched_at", 0) > seed.get("fetched_at", 0)):
    shutil.copyfile(os.path.join(previous, "stats.json"), stats_path)

# 2. refresh from OP.GG when the patch changed or the stats are getting old
if "--no-fetch" not in sys.argv:
    cmd = [sys.executable, os.path.join(ROOT, "tools", "fetch_stats.py"), "--max-age-days", arg("--max-age-days", "3")]
    if subprocess.run(cmd).returncode != 0:
        print("WARNING: stats fetch failed — publishing with the stats we already have")

# 3. build, and keep the old built_at if nothing really changed
pack = build_pack(KB)
prev_pack = load(os.path.join(previous, "pack.json")) if previous else None
strip = lambda p: {k: v for k, v in p.items() if k != "built_at"}
changed = not prev_pack or strip(prev_pack) != strip(pack)
if not changed:
    pack["built_at"] = prev_pack["built_at"]

os.makedirs(out, exist_ok=True)
with open(os.path.join(out, "pack.json"), "w", encoding="utf-8") as f:
    json.dump(pack, f, separators=(",", ":"))
shutil.copyfile(stats_path, os.path.join(out, "stats.json"))
manifest = {"version": pack["version"], "built_at": pack["built_at"], "stats_at": pack.get("stats_at"),
            "matchups_version": pack.get("matchups_version"), "champions": len(pack["champions"]),
            "pairs": sum(len(t) for r in pack.get("matchups", {}).values() for t in r.values()),
            "app_version": __version__, "app_url": APP_URL, "published_at": int(time.time()) if changed else None}
if not changed and previous:
    manifest = load(os.path.join(previous, "manifest.json")) or manifest
    manifest.update(app_version=__version__, app_url=APP_URL)
with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=1)

size = os.path.getsize(os.path.join(out, "pack.json")) // 1024
print(f"{'CHANGED' if changed else 'unchanged'}: patch {pack['version']}, {manifest['pairs']} matchup pairs, pack {size} KB -> {out}")
if os.environ.get("GITHUB_OUTPUT"):
    with open(os.environ["GITHUB_OUTPUT"], "a") as f:
        f.write(f"changed={'true' if changed else 'false'}\n")
