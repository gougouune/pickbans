import requests
import json
import urllib3
import os
import time

urllib3.disable_warnings()

def get_client_credentials():
    possible_paths = [
        "C:/Riot Games/League of Legends/lockfile",
        "D:/Riot Games/League of Legends/lockfile",
        "C:/Program Files/Riot Games/League of Legends/lockfile",
        "J:/Riot Games/League of Legends/lockfile",
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            with open(path) as f:
                content = f.read()
                parts = content.split(":")
                port = parts[2]
                password = parts[3]
                return port, password
    
    return None, None

def load_champ_names():
    try:
        with open("D:/PICKBANS/champion_ids.json") as f:
            data = json.load(f)
            return {int(k): v for k, v in data.items()}
    except:
        print("champion_ids.json not found - run setup_champdata.py first")
        return {}

def parse_champselect(data, champ_names):
    my_team = []
    their_team = []
    bans = []

    my_cell_id = data.get("localPlayerCellId", -1)

    for action_group in data.get("actions", []):
        for action in action_group:
            if action.get("type") == "ban" and action.get("completed"):
                champ_id = action.get("championId", 0)
                if champ_id and champ_id in champ_names:
                    bans.append(champ_names[champ_id])

    for player in data.get("myTeam", []):
        champ_id = player.get("championId", 0)
        name = champ_names.get(champ_id, "Not picked yet") if champ_id else "Not picked yet"
        my_team.append({
            "name": name,
            "position": player.get("assignedPosition", "?").upper() or "?",
            "isYou": player.get("cellId") == my_cell_id,
            "locked": champ_id != 0
        })

    for player in data.get("theirTeam", []):
        champ_id = player.get("championId", 0)
        name = champ_names.get(champ_id, "Not picked yet") if champ_id else "Not picked yet"
        their_team.append({
            "name": name,
            "position": player.get("assignedPosition", "?").upper() or "?",
            "locked": champ_id != 0
        })

    return my_team, their_team, bans

def display(my_team, their_team, bans):
    os.system("cls")
    print("=" * 40)
    print("      PICKBANS.COM - DRAFT")
    print("=" * 40)

    print("\nYOUR TEAM:")
    for p in my_team:
        you = " <- YOU" if p.get("isYou") else ""
        locked = "[LOCKED]" if p["locked"] else "[waiting]"
        print(f"  {locked} [{p['position']}] {p['name']}{you}")

    print("\nENEMY TEAM:")
    for p in their_team:
        locked = "[LOCKED]" if p["locked"] else "[waiting]"
        print(f"  {locked} [{p['position']}] {p['name']}")

    print(f"\nBANS: {', '.join(bans) if bans else 'None yet'}")
    print("\n--- refreshing every 3s, Ctrl+C to stop ---")

def watch_champselect():
    port, password = get_client_credentials()
    
    if not port:
        print("Could not find lockfile - is League client open?")
        return
    
    print(f"Found client on port {port}")
    print("Waiting for champ select...")

    champ_names = load_champ_names()
    
    while True:
        url = f"https://127.0.0.1:{port}/lol-champ-select/v1/session"
        
        try:
            r = requests.get(
                url,
                auth=requests.auth.HTTPBasicAuth("riot", password),
                verify=False,
                timeout=5
            )
            
            if r.status_code == 200:
                data = r.json()
                my_team, their_team, bans = parse_champselect(data, champ_names)
                display(my_team, their_team, bans)
                time.sleep(3)
            else:
                print(".", end="", flush=True)
                time.sleep(2)
                
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"\nError: {e}")
            time.sleep(2)

if __name__ == "__main__":
    watch_champselect()
    input("Press Enter to close...")