import os
import requests
import json
import time
import re
from datetime import datetime, timezone


AIRPORTS = [
    "RCTP",  # 桃園
    "RCSS",  # 松山
    "RCKH",  # 高雄
    "RCMQ",  # 台中
    "RCBS",  # 金門
    "RCNN",  # 台南，注意不是 RCWA
    "RCYU",  # 花蓮
    "RCQC"   # 馬公
]


def log(*args):
    print(*args, flush=True)


def parse_obs_time(value):
    if not value:
        return int(time.time())

    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return int(time.time())


def parse_metar_time(raw_metar):
    """
    備援：從 METAR 的 131700Z 解析時間。
    """
    try:
        match = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", raw_metar)

        if not match:
            return int(time.time())

        day = int(match.group(1))
        hour = int(match.group(2))
        minute = int(match.group(3))

        now = datetime.now(timezone.utc)
        dt = datetime(now.year, now.month, day, hour, minute, tzinfo=timezone.utc)

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


def load_old_weather():
    """
    讀取舊的 local_weather.json。
    如果金門、花蓮這次沒抓到，就保留舊資料。
    """
    if not os.path.exists("local_weather.json"):
        return {}

    try:
        with open("local_weather.json", "r", encoding="utf-8") as f:
            old_data = json.load(f)

        if not isinstance(old_data, list):
            return {}

        return {
            item.get("icaoId"): item
            for item in old_data
            if item.get("icaoId")
        }

    except Exception as e:
        log("讀取舊 local_weather.json 失敗：", e)
        return {}


def normalize_raw_metar(raw_metar):
    raw_metar = str(raw_metar or "").strip()
    raw_metar = raw_metar.replace("=", "")
    raw_metar = re.sub(r"\s+", " ", raw_metar)

    return raw_metar


def fetch_aoaws_metar():
    old_weather = load_old_weather()

    ids = ",".join(AIRPORTS)

    url = (
        "https://aviationweather.gov/api/data/metar"
        f"?ids={ids}&format=json&taf=false&hours=6"
    )

    headers = {
        "User-Agent": "taiwan-airport-weather/1.0 contact: github-actions"
    }

    log("正在抓取 AviationWeather METAR API...")
    log("URL:", url)

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    data = response.json()

    log("API 回傳筆數：", len(data))

    by_icao = {}

    for item in data:
        icao = item.get("icaoId")

        if icao not in AIRPORTS:
            continue

        raw_metar = normalize_raw_metar(item.get("rawOb", ""))

        if not raw_metar:
            continue

        obs_time = parse_obs_time(
            item.get("obsTime")
            or item.get("reportTime")
            or item.get("receiptTime")
        )

        # 如果 API 沒有時間，就從 METAR 本身解析
        if not obs_time:
            obs_time = parse_metar_time(raw_metar)

        visib = item.get("visib")

        if visib is None or visib == "":
            visibility_miles = parse_visibility_from_raw(raw_metar)
        else:
            visibility_miles = str(visib).replace("+", "")

        new_item = {
            "icaoId": icao,
            "obsTime": obs_time,
            "rawOb": raw_metar,
            "visib": visibility_miles,
            "status": "updated"
        }

        # 同一機場如果有多筆，只保留最新
        if icao not in by_icao:
            by_icao[icao] = new_item
        else:
            old_time = int(by_icao[icao].get("obsTime", 0))
            new_time = int(new_item.get("obsTime", 0))

            if new_time >= old_time:
                by_icao[icao] = new_item

    weather_data = []

    for icao in AIRPORTS:
        if icao in by_icao:
            weather_data.append(by_icao[icao])
            log(f"成功抓取 {icao}: {by_icao[icao]['rawOb']}")

        elif icao in old_weather and old_weather[icao].get("rawOb"):
            log(f"{icao} 這次沒抓到，保留舊資料")

            old_item = old_weather[icao]
            old_item["status"] = "old_data_kept"
            weather_data.append(old_item)

        else:
            log(f"{icao} 沒有新資料，也沒有舊資料，建立空資料")

            weather_data.append({
                "icaoId": icao,
                "obsTime": 0,
                "rawOb": "",
                "visib": "",
                "status": "暫無最新報文，可能為非作業時段"
            })

    log("整理後筆數：", len(weather_data))

    if not weather_data:
        raise RuntimeError("未取得任何 METAR 資料")

    with open("local_weather.json", "w", encoding="utf-8") as f:
        json.dump(weather_data, f, ensure_ascii=False, indent=4)

    log("資料已成功寫入 local_weather.json")

    log("========== 最後輸出內容 ==========")
    for item in weather_data:
        log(item["icaoId"], "=>", item.get("rawOb", ""))


if __name__ == "__main__":
    fetch_aoaws_metar()
