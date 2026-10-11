import requests
import json

def test_riot_connection():
    url = "https://127.0.0.1:2999/liveclientdata/allgamedata"
    
    try:
        response = requests.get(url, verify=False, timeout=5)
        data = response.json()
        print("✅ Connected to League client!")
        print(json.dumps(data, indent=2))
        
    except requests.exceptions.ConnectionError:
        print("❌ Can't connect - make sure League is open and you're in a game/lobby")
    except requests.exceptions.Timeout:
        print("❌ Timeout - League client not responding")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_riot_connection()