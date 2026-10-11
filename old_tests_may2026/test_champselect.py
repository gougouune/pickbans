import requests
import json
import urllib3
urllib3.disable_warnings()

def test_champselect():
    # This is the champ select endpoint
    url = "https://127.0.0.1:2999/liveclientdata/playerlist"
    
    # Also test the champ select specific endpoint
    champ_select_url = "https://127.0.0.1:2999/liveclientdata/activeplayername"
    
    try:
        r = requests.get(champ_select_url, verify=False, timeout=5)
        print("Your summoner name:")
        print(r.json())
        print()
        
        r2 = requests.get(url, verify=False, timeout=5)
        players = r2.json()
        print("All players in game:")
        for p in players:
            print(f"  {p['riotId']} → {p['championName']} ({p['team']})")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_champselect()