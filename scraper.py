import os
import re
import json
import time
import html
import calendar
import requests
from datetime import datetime, timezone, timedelta


AIRPORTS = [
    "RCTP",  # 桃園
    "RCSS",  # 松山
    "RCKH",  # 高雄
    "RCMQ",  # 台中
    "RCBS",  # 金門
    "RCNN",  # 台南
    "RCYU",  # 花蓮
    "RCQC"   # 馬公
]

AOAWS_API_URL = "https://aoaws.anws.gov.tw/Report/get_metar_speci"
AOAWS_REFERER = "https://aoaws.anws.gov.tw/Report#gsc.tab=0"


def log(*args):
    print(*args, flush=True)


def parse_metar_obs_time(raw_report):
    """
    從 METAR / SPECI 裡的 131700Z 解析成 Unix timestamp。
    131700Z = 本月 13 日 17:00 UTC
    """
    try:
        match = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", raw_report)

        if not match:
            return int(time.time())

        day = int(match.group(1))
        hour = int(match.group(2))
        minute = int(match.group(3))

        now = datetime.now(timezone.utc)
        year = now.year
        month = now.month

        last_day = calendar.monthrange(year, month)[1]

        if day > last_day:
            return int(time.time())

        dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)

        # 避免月底跨月時解析到未來日期
        if dt - now > timedelta(days=1):
            month -= 1

            if month == 0:
                month = 12
                year -= 1

            dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)

        return int(dt.timestamp())

    except Exception:
        return int(time.time())


def parse_visibility_from_raw(raw_report):
    """
    從 METAR / SPECI 原文抓能見度，例如 9999 / 8000 / 4800。
    local_weather.json 的 visib 保留英里格式給前端備援。
    """
    match = re.search(r"\s(\d{4})\s", raw_report)

    if not match:
        return ""

    meters = int(match.group(1))

    if meters == 9999:
        return "6.2"

    return str(round(meters / 1609.34, 2))


def normalize_raw_report(raw):
    """
    清理 METAR / SPECI 字串。
    重點：SPECI 不要被錯改成 METAR SPECI。
    """
    if not raw:
        return ""

    raw = html.unescape(str(raw))
    raw = raw.replace("\\n", " ")
    raw = raw.replace("\\/", "/")
    raw = raw.replace("\u00a0", " ")
    raw = raw.replace("=", "")
    raw = re.sub(r"\s+", " ", raw).strip()

    if raw.startswith("METAR ") or raw.startswith("SPECI "):
        return raw

    # 有些來源可能只給：RCYU 131700Z ...
    if re.match(r"^[A-Z]{4}\s+\d{6}Z", raw):
        return "METAR " + raw

    return raw


def is_valid_report(icao, raw_report):
    if not raw_report:
        return False

    if not re.search(rf"\b(?:METAR|SPECI)\s+{icao}\s+\d{{6}}Z\b", raw_report):
        return False

    if "KT" not in raw_report:
        return False

    if not re.search(r"\bM?\d{2}/M?\d{2}\b", raw_report):
        return False

    if not re.search(r"\bQ\d{4}\b", raw_report):
        return False

    return True


def make_weather_item(icao, raw_report):
    raw_report = normalize_raw_report(raw_report)

    return {
        "icaoId": icao,
        "obsTime": parse_metar_obs_time(raw_report),
        "rawOb": raw_report,
        "visib": parse_visibility_from_raw(raw_report),
        "status": "updated"
    }


def load_old_weather():
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


def collect_report_items(obj):
    """
    AOAWS 回傳結構可能是 list，也可能包在 dict 裡。
    這個函式會遞迴找出含有 content/station 的資料。
    """
    items = []

    if isinstance(obj, list):
        for x in obj:
            items.extend(collect_report_items(x))

    elif isinstance(obj, dict):
        if "content" in obj and "station" in obj:
            items.append(obj)

        for value in obj.values():
            if isinstance(value, (list, dict)):
                items.extend(collect_report_items(value))

    return items


def fetch_from_aoaws_api():
    """
    直接打 AOAWS 官方 XHR API：
    https://aoaws.anws.gov.tw/Report/get_metar_speci

    Payload 格式：
    search_airports[]=RCTP
    search_airports[]=RCSS
    ...
    """
    log("正在抓取 AOAWS 官方 METAR/SPECI API...")
    log("URL:", AOAWS_API_URL)

    result = {}

    headers = {
        "User-Agent": "taiwan-airport-weather/1.0",
        "Referer": AOAWS_REFERER,
        "Origin": "https://aoaws.anws.gov.tw",
        "X-Requested-With": "XMLHttpRequest"
    }

    # Form Data：重複的 search_airports[]
    data = []

    for icao in AIRPORTS:
        data.append(("search_airports[]", icao))

    try:
        session = requests.Session()

        # 先進 Report 頁面拿 cookie，比較像正常瀏覽器流程
        session.get(AOAWS_REFERER, headers=headers, timeout=20)

        response = session.post(
            AOAWS_API_URL,
            headers=headers,
            data=data,
            timeout=30
        )

        response.raise_for_status()

        try:
            payload = response.json()
        except Exception:
            log("AOAWS 回傳不是 JSON，前 500 字：")
            log(response.text[:500])
            return result

        report_items = collect_report_items(payload)

        log("AOAWS API 回傳報文筆數：", len(report_items))

        for item in report_items:
            icao = item.get("station")
            raw_report = item.get("content", "")

            if icao not in AIRPORTS:
                continue

            raw_report = normalize_raw_report(raw_report)

            if not is_valid_report(icao, raw_report):
                log(f"AOAWS {icao} 報文格式不完整，略過：{raw_report}")
                continue

            weather_item = make_weather_item(icao, raw_report)

            # 同一機場只保留最新
            if icao not in result:
                result[icao] = weather_item
            else:
                old_time = int(result[icao].get("obsTime", 0))
                new_time = int(weather_item.get("obsTime", 0))

                if new_time >= old_time:
                    result[icao] = weather_item

        log("AOAWS 整理後機場數：", len(result))

        for icao in AIRPORTS:
            if icao in result:
                log(f"AOAWS 最新 {icao}: {result[icao]['rawOb']}")
            else:
                log(f"AOAWS 沒有回傳 {icao}")

    except Exception as e:
        log("AOAWS API 抓取失敗：", e)

    return result


def fetch_from_aviationweather():
    """
    備援來源：AviationWeather API。
    如果 AOAWS 有機場缺資料，再用它補。
    """
    ids = ",".join(AIRPORTS)

    url = (
        "https://aviationweather.gov/api/data/metar"
        f"?ids={ids}&format=json&taf=false&hours=6"
    )

    headers = {
        "User-Agent": "taiwan-airport-weather/1.0"
    }

    log("正在抓取 AviationWeather 備援 API...")
    log("URL:", url)

    result = {}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()

        if not isinstance(data, list):
            log("AviationWeather 回傳格式不是 list")
            return result

        log("AviationWeather API 回傳筆數：", len(data))

        for item in data:
            icao = item.get("icaoId")

            if icao not in AIRPORTS:
                continue

            raw_report = item.get("rawOb", "").strip()

            if not raw_report:
                continue

            raw_report = normalize_raw_report(raw_report)

            if not is_valid_report(icao, raw_report):
                continue

            obs_time = parse_metar_obs_time(raw_report)

            visib = item.get("visib")

            if visib is None or visib == "":
                visibility = parse_visibility_from_raw(raw_report)
            else:
                visibility = str(visib).replace("+", "")

            new_item = {
                "icaoId": icao,
                "obsTime": obs_time,
                "rawOb": raw_report,
                "visib": visibility,
                "status": "updated"
            }

            if icao not in result:
                result[icao] = new_item
            else:
                old_time = int(result[icao].get("obsTime", 0))
                if obs_time > old_time:
                    result[icao] = new_item

        log("AviationWeather 整理後機場數：", len(result))

    except Exception as e:
        log("AviationWeather 抓取失敗：", e)

    return result


def merge_weather(primary, backup):
    """
    AOAWS 優先，AviationWeather 補缺。
    """
    merged = dict(primary)

    for icao, item in backup.items():
        if icao not in merged and item.get("rawOb"):
            log(f"使用 AviationWeather 補缺 {icao}: {item['rawOb']}")
            merged[icao] = item

    return merged


def fetch_aoaws_metar():
    log("目前工作目錄：", os.getcwd())

    old_weather = load_old_weather()

    aoaws_weather = fetch_from_aoaws_api()

    missing = [
        icao
        for icao in AIRPORTS
        if icao not in aoaws_weather
    ]

    aviation_weather = {}

    if missing:
        log("AOAWS 缺少機場，啟用 AviationWeather 備援：", ", ".join(missing))
        aviation_weather = fetch_from_aviationweather()

    new_weather = merge_weather(aoaws_weather, aviation_weather)

    weather_data = []

    for icao in AIRPORTS:
        if icao in new_weather and new_weather[icao].get("rawOb"):
            weather_data.append(new_weather[icao])

        elif icao in old_weather and old_weather[icao].get("rawOb"):
            log(f"{icao} 這次沒抓到，保留舊資料")

            item = old_weather[icao]
            item["status"] = "old_data_kept"
            weather_data.append(item)

        else:
            log(f"{icao} 沒有新資料，也沒有舊資料，建立空資料")

            weather_data.append({
                "icaoId": icao,
                "obsTime": 0,
                "rawOb": "",
                "visib": "",
                "status": "暫無最新報文，可能為非作業時段"
            })

    with open("local_weather.json", "w", encoding="utf-8") as f:
        json.dump(weather_data, f, ensure_ascii=False, indent=4)

    log("資料已成功寫入 local_weather.json")
    log("最後輸出筆數：", len(weather_data))

    log("========== 最後輸出內容 ==========")
    for item in weather_data:
        log(item["icaoId"], "=>", item.get("rawOb", ""))


if __name__ == "__main__":
    fetch_aoaws_metar()
