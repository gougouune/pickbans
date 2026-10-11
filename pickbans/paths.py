"""Where things live, both from source and inside the PyInstaller .exe."""
import os
import sys

if getattr(sys, "frozen", False):
    BUNDLE_DIR = os.path.join(sys._MEIPASS, "pickbans")
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))

WEB_DIR = os.path.join(BUNDLE_DIR, "web")
BUNDLED_PACK = os.path.join(BUNDLE_DIR, "data", "pack.json")

USER_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PICKBANS")
USER_PACK = os.path.join(USER_DIR, "pack.json")
HISTORY_FILE = os.path.join(USER_DIR, "history.json")
LOG_FILE = os.path.join(USER_DIR, "pickbans.log")

os.makedirs(USER_DIR, exist_ok=True)
