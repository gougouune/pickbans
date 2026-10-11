import requests
import json
import urllib3
urllib3.disable_warnings()

def download_champ_data():
    versions_url = "https://ddragon.leagueoflegends.com/api/versions.json"
    versions = requests.get(versions_url).json()
    latest = versions[0]
    print(f"Latest patch: {latest}")

    champ_url = f"https://ddragon.leagueoflegends.com/cdn/{latest}/data/en_US/champion.json"
    data = requests.get(champ_url).json()

    id_to_name = {}
    for champ_name, champ_data in data["data"].items():
        champ_id = int(champ_data["key"])
        id_to_name[champ_id] = champ_data["name"]

    with open("D:/PICKBANS/champion_ids.json", "w") as f:
        json.dump(id_to_name, f, indent=2)

    print(f"✅ Saved {len(id_to_name)} champions to champion_ids.json")
    print(f"Example: {list(id_to_name.items())[:5]}")

if __name__ == "__main__":
    download_champ_data()
