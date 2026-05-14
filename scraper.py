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

AOAWS_API_URL = "https://aoaws.anws.gov.tw/Report/get_metar_speci"
AOAWS_REFERER = "https://aoaws.anws.gov.tw/Report#gsc.tab=0"

# 完整的 API 請求資料
AOAWS_PAYLOAD = (
    "search_airports%5B%5D=RCSS&search_airports%5B%5D=RCTP&search_airports%5B%5D=RCMQ&"
    "search_airports%5B%5D=RCKU&search_airports%5B%5D=RCNN&search_airports%5B%5D=RCKH&"
    "search_airports%5B%5D=RCKW&search_airports%5B%5D=RCYU&search_airports%5B%5D=RCFN&"
    "search_airports%5B%5D=RCGI&search_airports%5B%5D=RCLY&search_airports%5B%5D=RCMT&"
    "search_airports%5B%5D=RCFG&search_airports%5B%5D=RCQC&search_airports%5B%5D=RCBS&"
    "search_airports%5B%5D=RCWA&search_airports%5B%5D=RCCM&search_airports%5B%5D=RCLM&"
    "time_item=recent_time&time_select=1"
)

def log(*args):
    print(*args, flush=True)

def parse_metar_obs_time(raw_report):
    try:
        match = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", raw_report)
        if not match: return int(time.time())
        day, hour, minute = map(int, match.groups())
        now = datetime.now(timezone.utc)
        year, month = now.year, now.month
        last_day = calendar.monthrange(year, month)[1]
        if day > last_day: return int(time.time())
        dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        if dt - now > timedelta(days=1):
            month -= 1
            if month == 0: month, year = 12, year - 1
            dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception: return int(time.time())

def parse_visibility_from_raw(raw_report):
    match = re.search(r"\s(\d{4})\s", raw_report)
    if not match: return ""
    meters = int(match.group(1))
    if meters == 9999: return "6.2"
    return str(round(meters / 1609.34, 2))

def normalize_raw_report(raw):
    if not raw: return ""
    raw = html.unescape(str(raw))
    raw = raw.replace("\\n", " ").replace("\\/", "/").replace('\\"', '"').replace("\u00a0", " ").replace("=", "")
    raw = re.sub(r"\s+", " ", raw).strip()
    if raw.startswith("METAR ") or raw.startswith("SPECI "): return raw
    if re.match(r"^[A-Z]{4}\s+\d{6}Z", raw): return "METAR " + raw
    return raw

def is_valid_report(icao, raw_report):
    """寬容的檢查邏輯：只要有機場代碼、時間、風速(KT)就視為有效資料"""
    if not raw_report: return False
    if not re.search(rf"\b(?:METAR|SPECI)\s+{icao}\s+\d{{6}}Z\b", raw_report): return False
    if "KT" not in raw_report: return False
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
    if not os.path.exists("local_weather.json"): return {}
    try:
        with open("local_weather.json", "r", encoding="utf-8") as f:
            old_data = json.load(f)
        if not isinstance(old_data, list): return {}
        return {item.get("icaoId"): item for item in old_data if item.get("icaoId")}
    except Exception as e:
        log("讀取舊資料失敗：", e)
        return {}

def collect_report_items(obj):
    items = []
    if isinstance(obj, list):
        for x in obj: items.extend(collect_report_items(x))
    elif isinstance(obj, dict):
        if "content" in obj and "station" in obj: items.append(obj)
        for value in obj.values():
            if isinstance(value, (list, dict)): items.extend(collect_report_items(value))
    return items

def extract_reports_from_response_text(response_text):
    result = {}
    if not response_text: return result
    text = html.unescape(response_text).replace("\\/", "/").replace("\\n", " ").replace('\\"', '"').replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    for icao in AIRPORTS:
        pattern = rf"((?:METAR|SPECI)\s+{icao}\s+\d{{6}}Z\s+.*?=)"
        matches = list(re.finditer(pattern, text))
        for match in matches:
            raw_report = normalize_raw_report(match.group(1))
            if not is_valid_report(icao, raw_report): continue
            item = make_weather_item(icao, raw_report)
            if icao not in result or int(item.get("obsTime", 0)) >= int(result[icao].get("obsTime", 0)):
                result[icao] = item
    return result

def fetch_from_aoaws_api():
    log("🌐 正在抓取 AOAWS 官方 API...")
    result = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://aoaws.anws.gov.tw",
        "Referer": AOAWS_REFERER,
        "X-Requested-With": "XMLHttpRequest"
    }
    for attempt in range(1, 4):
        try:
            response = requests.post(AOAWS_API_URL, headers=headers, data=AOAWS_PAYLOAD, timeout=30)
            response.raise_for_status()
            
            # 嘗試解析 JSON
            try:
                payload = response.json()
                report_items = collect_report_items(payload)
                for item in report_items:
                    icao, raw_report = item.get("station"), item.get("content", "")
                    if icao in AIRPORTS and is_valid_report(icao, normalize_raw_report(raw_report)):
                        weather_item = make_weather_item(icao, raw_report)
                        if icao not in result or int(weather_item["obsTime"]) >= int(result[icao]["obsTime"]):
                            result[icao] = weather_item
            except: pass
            
            # 備援：正則掃描文字
            text_result = extract_reports_from_response_text(response.text)
            for icao, item in text_result.items():
                if icao not in result or int(item["obsTime"]) >= int(result[icao]["obsTime"]):
                    result[icao] = item
            return result
        except Exception as e:
            log(f"AOAWS 第 {attempt} 次失敗: {e}")
            time.sleep(5)
    return result

def fetch_from_aviationweather():
    """備援 API：擴大至 12 小時，確保花蓮關場後仍有資料"""
    ids = ",".join(AIRPORTS)
    url = f"https://aviationweather.gov/api/data/metar?ids={ids}&format=json&taf=false&hours=12"
    log("🌐 正在抓取 AviationWeather 備援 (12小時內)...")
    result = {}
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        for item in data:
            icao = item.get("icaoId")
            raw_report = normalize_raw_report(item.get("rawOb", "").strip())
            if icao in AIRPORTS and is_valid_report(icao, raw_report):
                obs_time = parse_metar_obs_time(raw_report)
                visib = str(item.get("visib", "")).replace("+", "") or parse_visibility_from_raw(raw_report)
                new_item = {"icaoId": icao, "obsTime": obs_time, "rawOb": raw_report, "visib": visib, "status": "updated"}
                if icao not in result or obs_time > int(result[icao].get("obsTime", 0)):
                    result[icao] = new_item
    except Exception as e: log("備援抓取失敗：", e)
    return result

def fetch_aoaws_metar():
    old_weather = load_old_weather()
    aoaws_weather = fetch_from_aoaws_api()
    
    missing = [icao for icao in AIRPORTS if icao not in aoaws_weather]
    aviation_weather = fetch_from_aviationweather() if missing else {}
    
    # 合併兩者資料
    new_weather = dict(aoaws_weather)
    for icao, item in aviation_weather.items():
        if icao not in new_weather: new_weather[icao] = item

    weather_data = []
    for icao in AIRPORTS:
        if icao in new_weather:
            weather_data.append(new_weather[icao])
        elif icao in old_weather:
            item = old_weather[icao]
            item["status"] = "old_data_kept"
            weather_data.append(item)
        else:
            weather_data.append({"icaoId": icao, "obsTime": 0, "rawOb": "", "visib": "", "status": "暫無報文"})

    with open("local_weather.json", "w", encoding="utf-8") as f:
        json.dump(weather_data, f, ensure_ascii=False, indent=4)
    log("🎉 氣象資料更新完成，JSON 已成功寫入。")

if __name__ == "__main__":
    fetch_aoaws_metar()
