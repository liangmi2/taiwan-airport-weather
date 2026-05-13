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
    "RCNN",  # 台南
    "RCYU",  # 花蓮
    "RCQC"   # 馬公
]

# 關避憑證警告，避免向政府網站請求時因憑證驗證問題報錯
import requests
import urllib3

# 關閉憑證警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

url = "https://aoaws.anws.gov.tw/Home/get_metar_data"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://aoaws.anws.gov.tw/",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01"
}

print("發送測試請求至 ANWS...")

try:
    # 這次我們不加 data={}，並補齊了完整的瀏覽器 Accept 標頭
    res = requests.post(url, headers=headers, timeout=15, verify=False)
    
    print(f"連線狀態碼: {res.status_code}")
    print("=" * 40)
    
    if res.status_code == 200:
        print("連線成功！回傳內容前 300 字元：")
        print(res.text[:300])
    else:
        print("伺服器拒絕請求！")
        print(res.text[:300])
        
except Exception as e:
    print(f"發生連線錯誤：{e}")


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
        return "6.2"
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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://aoaws.anws.gov.tw/",
        "X-Requested-With": "XMLHttpRequest"  # 偽裝成前端 AJAX 請求
    }
    
    try:
        log("啟動備援：向 ANWS 請求全台機場 JSON 資料...")
        
        # 加上 data={} 強制發送 Content-Length，並加上 verify=False 避免憑證阻擋
        res = requests.post(url, headers=headers, data={}, timeout=15, verify=False)
        res.raise_for_status()
        data = res.json()
        
        anws_dict = {}
        if "latest_airport_list" in data and "Taiwan" in data["latest_airport_list"]:
            for airport in data["latest_airport_list"]["Taiwan"]:
                stid = airport.get("STID")
                if stid:
                    report = airport.get("REPORT", "").replace("\n", " ").replace("=", "").strip()
                    anws_dict[stid] = report
        return anws_dict
        
    except Exception as e:
        log(f"抓取 ANWS JSON 失敗: {e}")
        # 如果失敗，印出伺服器回傳的狀態碼方便我們除錯
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
            # NOAA 沒抓到，觸發備援機制
            if anws_cache is None:
                anws_cache = fetch_all_anws_data()
                
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
                
            elif icao in old_weather and old_weather[icao].get("rawOb"):
                log(f"{icao} NOAA 與 ANWS 皆無新資料，保留舊資料")
                old_item = old_weather[icao]
                old_item["status"] = "old_data_kept"
                weather_data.append(old_item)
                
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

if __name__ == "__main__":
    fetch_aoaws_metar()
