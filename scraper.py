import requests
import json
import time
import re
from datetime import datetime, timezone


AIRPORTS = ["RCTP", "RCSS", "RCKH", "RCMQ", "RCBS", "RCWA", "RCYU", "RCQC"]


def parse_obs_time(value):
    if not value:
        return int(time.time())

    try:
        # AviationWeather 通常是 2026-05-13T04:00:00Z 這類格式
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return int(time.time())


def parse_visibility_from_raw(raw_metar):
    """
    備援：如果 API 沒給 visib，就從 METAR 原始報文抓 9999 / 4000 這種公尺能見度。
    前端原本吃英里，所以這裡轉成英里字串。
    """
    match = re.search(r"\s(\d{4})\s", raw_metar)
    if not match:
        return ""

    meters = int(match.group(1))

    if meters == 9999:
        return "6.2"

    return str(round(meters / 1609.34, 2))


def fetch_aoaws_metar():
    ids = ",".join(AIRPORTS)

    url = (
        "https://aviationweather.gov/api/data/metar"
        f"?ids={ids}&format=json&taf=false&hours=3"
    )

    headers = {
        "User-Agent": "taiwan-airport-weather/1.0 contact: github-actions"
    }

    print("正在抓取 METAR API...")
    print("URL:", url)

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    data = response.json()

    print("API 回傳筆數：", len(data))

    by_icao = {}

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

        by_icao[icao] = {
            "icaoId": icao,
            "obsTime": obs_time,
            "rawOb": raw_metar,
            "visib": visibility_miles
        }

        print(f"成功抓取 {icao}: {raw_metar}")

    weather_data = []

    for icao in AIRPORTS:
        if icao in by_icao:
            weather_data.append(by_icao[icao])
        else:
            print(f"找不到 {icao} 的 METAR")

    print("整理後筆數：", len(weather_data))

    if not weather_data:
        raise RuntimeError("未取得任何 METAR 資料")

    with open("local_weather.json", "w", encoding="utf-8") as f:
        json.dump(weather_data, f, ensure_ascii=False, indent=4)

    print("資料已成功寫入 local_weather.json")


if __name__ == "__main__":
    fetch_aoaws_metar()
