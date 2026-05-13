import requests
import json
import time
import re
import os
from datetime import datetime


AIRPORTS = ["RCTP", "RCSS", "RCKH", "RCMQ", "RCBS", "RCNN", "RCYU", "RCQC"]


def parse_obs_time(value):
    if not value:
        return int(time.time())

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return int(time.time())


def parse_visibility_from_raw(raw_metar):
    match = re.search(r"\s(\d{4})\s", raw_metar)

    if not match:
        return ""

    meters = int(match.group(1))

    if meters == 9999:
        return "6.2"

    return str(round(meters / 1609.34, 2))


def load_old_weather():
    if not os.path.exists("local_weather.json"):
        return {}

    try:
        with open("local_weather.json", "r", encoding="utf-8") as f:
            old_data = json.load(f)

        return {
            item.get("icaoId"): item
            for item in old_data
            if item.get("icaoId")
        }

    except Exception as e:
        print("讀取舊 local_weather.json 失敗：", e)
        return {}


def fetch_aoaws_metar():
    ids = ",".join(AIRPORTS)

    url = (
        "https://aviationweather.gov/api/data/metar"
        f"?ids={ids}&format=json&taf=false&hours=24"
    )

    headers = {
        "User-Agent": "taiwan-airport-weather/1.0"
    }

    print("正在抓取 METAR API...")
    print("URL:", url)

    old_weather = load_old_weather()

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    data = response.json()

    print("API 回傳筆數：", len(data))

    new_weather = {}

    for item in data:
        icao = item.get("icaoId")

        if icao not in AIRPORTS:
            continue

        raw_metar = item.get("rawOb", "").strip()

        if not raw_metar:
            continue

        obs_time = parse_obs_time(
            item.get("obsTime")
            or item.get("reportTime")
            or item.get("receiptTime")
        )

        visib = item.get("visib")

        if visib is None or visib == "":
            visibility_miles = parse_visibility_from_raw(raw_metar)
        else:
            visibility_miles = str(visib).replace("+", "")

        new_weather[icao] = {
            "icaoId": icao,
            "obsTime": obs_time,
            "rawOb": raw_metar,
            "visib": visibility_miles
        }

        print(f"成功抓取 {icao}: {raw_metar}")

    weather_data = []

    for icao in AIRPORTS:
        if icao in new_weather:
            weather_data.append(new_weather[icao])
        elif icao in old_weather:
            print(f"{icao} 這次 API 沒回傳，保留舊資料")
            weather_data.append(old_weather[icao])
        else:
            print(f"{icao} 沒有新資料，也沒有舊資料，建立空資料")
            weather_data.append({
                "icaoId": icao,
                "obsTime": int(time.time()),
                "rawOb": "",
                "visib": ""
            })

    with open("local_weather.json", "w", encoding="utf-8") as f:
        json.dump(weather_data, f, ensure_ascii=False, indent=4)

    print("資料已成功寫入 local_weather.json")
    print("最後輸出筆數：", len(weather_data))


if __name__ == "__main__":
    fetch_aoaws_metar()
