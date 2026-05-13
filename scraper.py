import os
import requests
import json
import time
import re
from datetime import datetime, timezone
import urllib3

# 關閉憑證警告，避免向政府網站請求時因憑證驗證問題報錯
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    """從 METAR 原始報文解析時間 (備援使用)"""
    try:
        match = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", raw_metar)
        if not match:
            # 如果報文裡找不到時間，直接回傳當下時間，避免回傳 0 導致前端顯示異常
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
    """從 METAR 原始報文解析能見度 (轉為英里字串)"""
    match = re.search(r"\s(\d{4})\s", raw_metar)
    if not match:
        return ""
    
    meters = int(match.group(1))
    if meters == 9999:
        return "6.2" # 前端預期 9999 代表大於 10km，轉換為大約 6.2 英里
    return str(round(meters / 1609.34, 2))

def load_old_weather():
    if not os.path.exists("local_weather.json"):
        return {}
    try:
        with open("local_weather.json", "r", encoding="utf-8") as f:
            old_data = json.load(f)
        if not isinstance(old_data, list):
            return {}
        return {item.get("icaoId"): item for item in old_data if item.get("icaoId")}
    except Exception as e:
        log("讀取舊 local_weather.json 失敗：", e)
        return {}

def normalize_raw_metar(raw_metar):
    raw_metar = str(raw_metar or "").strip()
    raw_metar = raw_metar.replace("=", "")
    raw_metar = re.sub(r"\s+", " ", raw_metar)
    return raw_metar

def fetch_all_anws_data():
    """備援機制：一次性抓取台灣官方 (ANWS) 所有機場的 JSON 資料"""
    url = "https://aoaws.anws.gov.tw/Home/get_metar_data"
    
    # 【強化偽裝】補齊標準瀏覽器 POST 請求所需的所有 Headers
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://aoaws.anws.gov.tw",
        "Referer": "https://aoaws.anws.gov.tw/",
        "Connection": "keep-alive"
    }
    
    try:
        log("啟動備援：向 ANWS 請求全台機場 JSON 資料...")
        # 即使沒有要傳資料，也要傳送一個空的字串當作 payload，強迫產生 Content-Length
        res = requests.post(url, headers=headers, data="", timeout=15, verify=False)
        res.raise_for_status()
        
        # 加上容錯處理：確認回傳的真的是 JSON
        try:
            data = res.json()
        except ValueError:
            log("ANWS 回傳的不是有效的 JSON 格式！")
            return {}
            
        anws_dict = {}
        if "latest_airport_list" in data and "Taiwan" in data["latest_airport_list"]:
            for airport in data["latest_airport_list"]["Taiwan"]:
                stid = airport.get("STID")
                if stid:
                    report = airport.get("REPORT", "").replace("\n", " ").replace("=", "").strip()
                    anws_dict[stid] = report
        
        log(f"備援資料抓取完畢，共取得 {len(anws_dict)} 筆機場資料。")
        return anws_dict
        
    except requests.exceptions.RequestException as e:
        log(f"抓取 ANWS 連線失敗: {e}")
        if hasattr(e, 'response') and e.response is not None:
            log(f"伺服器狀態碼: {e.response.status_code}")
        return {}

def fetch_aoaws_metar():
    old_weather = load_old_weather()
    ids = ",".join(AIRPORTS)
    
    # 1. 先嘗試從 NOAA 抓取主要資料
    noaa_url = f"https://aviationweather.gov/api/data/metar?ids={ids}&format=json&taf=false&hours=6"
    headers = {"User-Agent": "taiwan-airport-weather/1.0"}
    
    log("正在抓取 AviationWeather METAR API...")
    by_icao = {}
    
    try:
        response = requests.get(noaa_url, headers=headers, timeout=30)
        response.raise_for_status()
        noaa_data = response.json()
        
        for item in noaa_data:
            icao = item.get("icaoId")
            if icao not in AIRPORTS:
                continue
                
            raw_metar = normalize_raw_metar(item.get("rawOb", ""))
            if not raw_metar:
                continue
                
            obs_time = parse_obs_time(item.get("obsTime") or item.get("reportTime"))
            if not obs_time:
                obs_time = parse_metar_time(raw_metar)
                
            visib = item.get("visib")
            visib_str = parse_visibility_from_raw(raw_metar) if (visib is None or visib == "") else str(visib).replace("+", "")
            
            new_item = {
                "icaoId": icao,
                "obsTime": obs_time,
                "rawOb": raw_metar,
                "visib": visib_str,
                "status": "updated"
            }
            
            # 保留最新的一筆資料
            if icao not in by_icao or int(new_item.get("obsTime", 0)) >= int(by_icao[icao].get("obsTime", 0)):
                by_icao[icao] = new_item
                
    except Exception as e:
        log(f"抓取 NOAA API 發生錯誤: {e}")

    # 2. 整合資料與備援機制
    weather_data = []
    anws_cache = None  # 延遲載入備援資料，有需要才抓
    
    for icao in AIRPORTS:
        if icao in by_icao:
            weather_data.append(by_icao[icao])
            log(f"成功抓取 {icao} (NOAA): {by_icao[icao]['rawOb']}")
            
        else:
            log(f"NOAA 缺少 {icao} 資料，觸發備援...")
            # 如果還沒抓過備援資料，就抓一次
            if anws_cache is None:
                anws_cache = fetch_all_anws_data()
                
            # 從備援資料中尋找
            if anws_cache and icao in anws_cache and anws_cache[icao]:
                anws_raw_metar = anws_cache[icao]
                obs_time = parse_metar_time(anws_raw_metar)
                visib_miles = parse_visibility_from_raw(anws_raw_metar)
                
                weather_data.append({
                    "icaoId": icao,
                    "obsTime": obs_time,
                    "rawOb": anws_raw_metar,
                    "visib": visib_miles,
                    "status": "updated_from_anws"
                })
                log(f"成功抓取 {icao} (ANWS): {anws_raw_metar}")
                
            # 若備援也找不到，嘗試使用舊資料
            elif icao in old_weather and old_weather[icao].get("rawOb"):
                log(f"{icao} NOAA 與 ANWS 皆無新資料，保留舊資料")
                old_item = old_weather[icao]
                old_item["status"] = "old_data_kept"
                weather_data.append(old_item)
                
            # 完全沒有資料
            else:
                log(f"{icao} 完全無資料，建立空資料")
                weather_data.append({
                    "icaoId": icao,
                    "obsTime": 0,
                    "rawOb": "",
                    "visib": "",
                    "status": "暫無最新報文，可能為非作業時段"
                })

    # 3. 輸出結果
    if not weather_data:
        raise RuntimeError("未取得任何 METAR 資料")

    with open("local_weather.json", "w", encoding="utf-8") as f:
        json.dump(weather_data, f, ensure_ascii=False, indent=4)
        
    log("資料已成功寫入 local_weather.json")
    
    # 印出最終結果供確認
    log("========== 最後輸出內容 ==========")
    for item in weather_data:
        log(f"{item['icaoId']} => {item.get('rawOb', '無資料')}")

if __name__ == "__main__":
    fetch_aoaws_metar()
