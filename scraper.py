import os
import re
import json
import time
import html
import calendar
import requests
from datetime import datetime, timezone, timedelta


# 首頁要顯示的 8 個機場
AIRPORTS = [
    "RCTP",  # 桃園國際機場
    "RCSS",  # 台北松山機場
    "RCKH",  # 高雄小港機場
    "RCMQ",  # 台中清泉崗機場
    "RCBS",  # 金門尚義機場
    "RCNN",  # 台南機場
    "RCYU",  # 花蓮機場
    "RCQC"   # 馬公機場
]


# AOAWS 官方 XHR API
AOAWS_API_URL = "https://aoaws.anws.gov.tw/Report/get_metar_speci"
AOAWS_REFERER = "https://aoaws.anws.gov.tw/Report#gsc.tab=0"


# 你在 Chrome DevTools Payload 裡找到的完整 Form Data
# 這裡保留臺北飛航情報區全部機場，最後再過濾出首頁要顯示的 8 個。
AOAWS_PAYLOAD = (
    "search_airports%5B%5D=RCSS&"
    "search_airports%5B%5D=RCTP&"
    "search_airports%5B%5D=RCMQ&"
    "search_airports%5B%5D=RCKU&"
    "search_airports%5B%5D=RCNN&"
    "search_airports%5B%5D=RCKH&"
    "search_airports%5B%5D=RCKW&"
    "search_airports%5B%5D=RCYU&"
    "search_airports%5B%5D=RCFN&"
    "search_airports%5B%5D=RCGI&"
    "search_airports%5B%5D=RCLY&"
    "search_airports%5B%5D=RCMT&"
    "search_airports%5B%5D=RCFG&"
    "search_airports%5B%5D=RCQC&"
    "search_airports%5B%5D=RCBS&"
    "search_airports%5B%5D=RCWA&"
    "search_airports%5B%5D=RCCM&"
    "search_airports%5B%5D=RCLM&"
    "time_item=recent_time&"
    "time_select=1"
)


def log(*args):
    print(*args, flush=True)


def parse_metar_obs_time(raw_report):
    """
    從 METAR / SPECI 裡面的 131700Z 解析成 Unix timestamp。
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

        # 避免月底跨月時，解析到未來日期
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
    local_weather.json 的 visib 保留英里格式，給前端備援。
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
    注意：SPECI 不可以被錯改成 METAR SPECI。
    """
    if not raw:
        return ""

    raw = html.unescape(str(raw))
    raw = raw.replace("\\n", " ")
    raw = raw.replace("\\/", "/")
    raw = raw.replace('\\"', '"')
    raw = raw.replace("\u00a0", " ")
    raw = raw.replace("=", "")
    raw = re.sub(r"\s+", " ", raw).strip()

    if raw.startswith("METAR ") or raw.startswith("SPECI "):
        return raw

    # 有些來源可能只給：RCYU 131700Z 21001KT...
    # 這種才補 METAR
    if re.match(r"^[A-Z]{4}\s+\d{6}Z", raw):
        return "METAR " + raw

    return raw


def is_valid_report(icao, raw_report):
    """
    確認是不是有效 METAR / SPECI。
    """
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
    """
    讀取舊的 local_weather.json。
    如果某機場這次抓不到，就保留舊資料。
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


def collect_report_items(obj):
    """
    AOAWS 回傳結構可能是 list，也可能包在 dict 裡。
    遞迴找出含有 content / station 的資料。
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


def extract_reports_from_response_text(response_text):
    """
    備援解析：
    如果 JSON 結構變了，就直接從 response.text 裡抓 METAR / SPECI 原文。
    """
    result = {}

    if not response_text:
        return result

    text = html.unescape(response_text)
    text = text.replace("\\/", "/")
    text = text.replace("\\n", " ")
    text = text.replace('\\"', '"')
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)

    for icao in AIRPORTS:
        pattern = rf"((?:METAR|SPECI)\s+{icao}\s+\d{{6}}Z\s+.*?=)"
        matches = list(re.finditer(pattern, text))

        for match in matches:
            raw_report = normalize_raw_report(match.group(1))

            if not is_valid_report(icao, raw_report):
                continue

            item = make_weather_item(icao, raw_report)

            if icao not in result:
                result[icao] = item
            else:
                old_time = int(result[icao].get("obsTime", 0))
                new_time = int(item.get("obsTime", 0))

                if new_time >= old_time:
                    result[icao] = item

    return result


def fetch_from_aoaws_api():
    """
    第一來源：AOAWS 官方 METAR / SPECI API。
    直接 POST，不先 GET /Report，避免 GitHub Actions 卡在 /Report timeout。
    """
    log("正在抓取 AOAWS 官方 METAR/SPECI API...")
    log("URL:", AOAWS_API_URL)

    result = {}

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://aoaws.anws.gov.tw",
        "Referer": AOAWS_REFERER,
        "X-Requested-With": "XMLHttpRequest"
    }

    for attempt in range(1, 4):
        try:
            log(f"AOAWS API 第 {attempt} 次嘗試...")

            response = requests.post(
                AOAWS_API_URL,
                headers=headers,
                data=AOAWS_PAYLOAD,
                timeout=(30, 30)
            )

            log("AOAWS HTTP 狀態：", response.status_code)
            log("AOAWS Content-Type：", response.headers.get("content-type", ""))
            log("AOAWS response 長度：", len(response.text))

            for check_icao in ["RCBS", "RCYU", "RCNN"]:
                if check_icao in response.text:
                    log(f"AOAWS response 內有找到 {check_icao}")
                else:
                    log(f"AOAWS response 內沒有找到 {check_icao}")

            response.raise_for_status()

            # 第一層：JSON 解析
            try:
                payload = response.json()
                report_items = collect_report_items(payload)

                log("AOAWS JSON 解析報文筆數：", len(report_items))

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

                    if icao not in result:
                        result[icao] = weather_item
                    else:
                        old_time = int(result[icao].get("obsTime", 0))
                        new_time = int(weather_item.get("obsTime", 0))

                        if new_time >= old_time:
                            result[icao] = weather_item

            except Exception as e:
                log("AOAWS JSON 解析失敗：", e)

            # 第二層：response.text regex 備援
            text_result = extract_reports_from_response_text(response.text)

            for icao, item in text_result.items():
                if icao not in result:
                    log(f"AOAWS text 備援抓到 {icao}: {item['rawOb']}")
                    result[icao] = item
                else:
                    old_time = int(result[icao].get("obsTime", 0))
                    new_time = int(item.get("obsTime", 0))

                    if new_time >= old_time:
                        result[icao] = item

            log("AOAWS 整理後機場數：", len(result))

            for icao in AIRPORTS:
                if icao in result:
                    log(f"AOAWS 最新 {icao}: {result[icao]['rawOb']}")
                else:
                    log(f"AOAWS 沒有回傳 {icao}")

            return result

        except Exception as e:
            log(f"AOAWS API 第 {attempt} 次失敗：", e)

            if attempt < 3:
                time.sleep(5)

    log("AOAWS API 三次都失敗，改用 AviationWeather 備援")
    return result


def fetch_from_aviationweather():
    """
    備援來源：AviationWeather API。
    如果 AOAWS 抓不到，再用它補。
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

        for icao in AIRPORTS:
            if icao in result:
                log(f"AviationWeather 最新 {icao}: {result[icao]['rawOb']}")
            else:
                log(f"AviationWeather 沒有回傳 {icao}")

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
