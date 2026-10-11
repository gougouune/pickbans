"""Build pickbans/data/pack.json from tools/kb/*.txt + Riot's current roster.

Run from the project root:  python tools/build_pack.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pickbans.pack import build_pack  # noqa: E402

pack = build_pack(os.path.join(ROOT, "tools", "kb"))
out = os.path.join(ROOT, "pickbans", "data", "pack.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    json.dump(pack, f, indent=1)

guessed = [c["name"] for c in pack["champions"].values() if c["guessed"]]
no_notes = [c["name"] for c in pack["champions"].values() if not c["play"]]
print(f"Patch {pack['version']}: {len(pack['champions'])} champions -> {out}")
print(f"Guessed (not in KB): {guessed or 'none'}")
print(f"Missing notes: {no_notes or 'none'}")
