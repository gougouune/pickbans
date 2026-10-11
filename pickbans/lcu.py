"""Read-only connection to the League client (LCU API). PICKBANS never clicks, locks or bans anything."""
import logging
import os
import re
import subprocess
import urllib.error

from . import net

log = logging.getLogger("pickbans.lcu")

_LOCKFILE_DIRS = [
    r"C:\Riot Games\League of Legends",
    r"D:\Riot Games\League of Legends",
    r"C:\Program Files\Riot Games\League of Legends",
    r"C:\Program Files (x86)\Riot Games\League of Legends",
    r"E:\Riot Games\League of Legends",
]
_PRODUCT_SETTINGS = r"C:\ProgramData\Riot Games\Metadata\league_of_legends.live\league_of_legends.live.product_settings.yaml"


def find_credentials():
    """(port, token) of the running client, or None."""
    creds = _from_process()
    if creds:
        return creds
    for d in _install_dirs():
        lock = os.path.join(d, "lockfile")
        if os.path.exists(lock):
            try:
                with open(lock) as f:
                    parts = f.read().split(":")
                return parts[2], parts[3]
            except (OSError, IndexError):
                pass
    return None


def _from_process():
    if os.name != "nt":
        return None
    cmd = ["powershell", "-NoProfile", "-Command",
           "(Get-CimInstance Win32_Process -Filter \"name='LeagueClientUx.exe'\").CommandLine"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=8,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:
        return None
    port = re.search(r"--app-port=(\d+)", out)
    token = re.search(r"--remoting-auth-token=([\w-]+)", out)
    if port and token:
        return port.group(1), token.group(1)
    return None


def _install_dirs():
    dirs = list(_LOCKFILE_DIRS)
    try:
        with open(_PRODUCT_SETTINGS, encoding="utf-8") as f:
            m = re.search(r'product_install_full_path:\s*"?([^"\n]+)', f.read())
            if m:
                dirs.insert(0, m.group(1).strip())
    except OSError:
        pass
    return dirs


class LCU:
    def __init__(self, port, token):
        self.base = f"https://127.0.0.1:{port}"
        self.auth = ("riot", token)

    def get(self, path, timeout=5):
        """JSON for the endpoint, None if it doesn't exist right now (404). Raises if the client is gone."""
        try:
            return net.get_json(self.base + path, timeout=timeout, auth=self.auth, insecure=True)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    # --- endpoints PICKBANS uses ---
    def phase(self):
        return self.get("/lol-gameflow/v1/gameflow-phase")

    def session(self):
        return self.get("/lol-champ-select/v1/session")

    def pickable_ids(self):
        return self.get("/lol-champ-select/v1/pickable-champion-ids") or []

    def summoner(self):
        return self.get("/lol-summoner/v1/current-summoner")

    def mastery(self):
        return self.get("/lol-champion-mastery/v1/local-player/champion-mastery") or []

    def match_history(self, count=60):
        data = self.get(f"/lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex={count}", timeout=30)
        return ((data or {}).get("games") or {}).get("games") or []

    def owned_ids(self):
        champs = self.get("/lol-champions/v1/owned-champions-minimal") or []
        return [c["id"] for c in champs if c.get("ownership", {}).get("owned")]
