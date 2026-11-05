"""Your own opinion of a champion, set by right-clicking it anywhere in the tool.

love / like  you enjoy playing it  -> goes in your pool, ranked higher in your picks
hate         you hate playing AGAINST it -> pushed up the ban recs, flagged when an enemy picks it
ban          off-limits -> never recommended to you, always first in the ban recs
"""
import json
import os

from . import paths

MARKS_FILE = os.path.join(paths.USER_DIR, "marks.json")
KINDS = ("love", "like", "hate", "ban")
BONUS = {"love": 0.10, "like": 0.05}   # added to a pick's score
MARKS = {}                              # champion id -> kind (shared, set by the app)


def load():
    MARKS.clear()
    try:
        with open(MARKS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        MARKS.update({c: k for c, k in data.items() if k in KINDS})
    except (OSError, ValueError):
        pass
    return MARKS


def set_mark(champ, kind):
    """kind None / '' clears it. Returns the marks."""
    if kind in KINDS:
        MARKS[champ] = kind
    else:
        MARKS.pop(champ, None)
    try:
        with open(MARKS_FILE, "w", encoding="utf-8") as f:
            json.dump(MARKS, f, indent=1)
    except OSError:
        pass
    return MARKS


def get(champ):
    return MARKS.get(champ)


def banned():
    return [c for c, k in MARKS.items() if k == "ban"]


def hated():
    return [c for c, k in MARKS.items() if k == "hate"]


def liked():
    return [c for c, k in MARKS.items() if k in ("love", "like")]
