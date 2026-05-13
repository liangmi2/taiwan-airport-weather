import os
import re
import json
import time
import html
import calendar
import requests
from datetime import datetime, timezone, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


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

# 這幾個比較容易遇到夜間沒有即時報文，所以固定用 AOAWS 補強
LIMITED_AIRPORTS = ["RCBS", "RCNN", "RCYU"]


def parse_metar_obs_time(raw_report):
    """
    從 METAR / SPECI 裡面的 131606Z 解析成 Unix timestamp。
    131606Z = 本月 13 日 16:06 UTC
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
    從報文抓能見度，例如 9999 / 8000 / 5000。
    前端 app.js 也會自己從 rawOb 解析，這裡主要是備援。
    """
    match = re.search(r"\s(\d{4})\s", raw_report)

    if not match:
        return ""

    meters = int(match.group(1))

    if meters == 9999:
        return "6.2"

    return str(round(meters / 1609.34, 2))


def load_old_weather():
    """
    讀取舊的 local_weather.json。
    如果某機場這次沒抓到，就用舊資料補上。
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
        print("讀取舊 local_weather.json 失敗：", e)
        return {}


def normalize_raw_report(raw):
    """
    清理 METAR / SPECI 字串。
    重點：SPECI 不可以被錯誤改成 METAR SPECI。
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

    # 有些來源可能只給：RCYU 131606Z 26002KT...
    # 這種才補 METAR
    if re.match(r"^[A-Z]{4}\s+\d{6}Z", raw):
        return "METAR " + raw

    return raw


def trim_report(raw_report, icao):
    """
    從可能很長的網頁文字中，盡量切出乾淨的 METAR / SPECI 報文。
    """
    raw_report = normalize_raw_report(raw_report)

    stop_words = [
        " TAF ",
        " Station ",
        " 最新報告 ",
        " 機場天氣 ",
        " 觀測資料 ",
        " 全球機場天氣 ",
        " Copyright ",
        " 臺灣-",
        " 台灣-",
        " 臺灣 -",
        " 台灣 -",
        " 風向 ",
        " 風速 ",
        " 能見度 ",
        " 雲冪 "
    ]

    for word in stop_words:
        if word in raw_report:
            raw_report = raw_report.split(word)[0].strip()

    raw_report = raw_report.replace("=", "").strip()

    # 優先切到 QNH + 可選 NOSIG + 可選 RMK
    refined = re.match(
        rf"^((?:METAR|SPECI)\s+{icao}\s+\d{{6}}Z\s+.*?\sQ\d{{4}}"
        rf"(?:\s+NOSIG)?"
        rf"(?:\s+RMK\s+[A-Z0-9./+\- ]{{1,100}})?)",
        raw_report
    )

    if refined:
        raw_report = refined.group(1).strip()

    raw_report = re.sub(r"\s+", " ", raw_report).strip()
    return raw_report


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
    raw_report = trim_report(raw_report, icao)

    return {
        "icaoId": icao,
        "obsTime": parse_metar_obs_time(raw_report),
        "rawOb": raw_report,
        "visib": parse_visibility_from_raw(raw_report)
    }


def fetch_from_aviationweather():
    """
    第一來源：AviationWeather API。
    只抓最近 6 小時，並且每個機場只保留最新一筆。
    """
    ids = ",".join(AIRPORTS)

    url = (
        "https://aviationweather.gov/api/data/metar"
        f"?ids={ids}&format=json&taf=false&hours=6"
    )

    headers = {
        "User-Agent": "taiwan-airport-weather/1.0"
    }

    print("正在抓取 AviationWeather METAR API...")
    print("URL:", url)

    result = {}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()

        if not isinstance(data, list):
            print("AviationWeather 回傳格式不是 list")
            return result

        print("AviationWeather API 回傳筆數：", len(data))

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
                "visib": visibility
            }

            # 同一個機場只保留最新一筆
            if icao not in result:
                result[icao] = new_item
            else:
                old_time = int(result[icao].get("obsTime", 0))
                if obs_time > old_time:
                    result[icao] = new_item

        print("AviationWeather 整理後機場數：", len(result))

        for icao in AIRPORTS:
            if icao in result:
                print(f"AviationWeather 最新 {icao}: {result[icao]['rawOb']}")
            else:
                print(f"AviationWeather 沒有回傳 {icao}")

    except Exception as e:
        print("AviationWeather 抓取失敗：", e)

    return result


def extract_report_from_content(content, icao):
    """
    從 AOAWS 頁面內容中找 METAR 或 SPECI。
    支援：
    METAR RCYU 131606Z ...
    SPECI RCYU 131606Z ...
    RCYU 131606Z ...
    """
    if not content:
        return ""

    content = html.unescape(content)
    content = content.replace("\u00a0", " ")
    content = content.replace("\\n", " ")
    content = content.replace("\\/", "/")
    content = re.sub(r"<[^>]+>", " ", content)
    content = re.sub(r"\s+", " ", content).strip()

    patterns = [
        # 標準原始報文：METAR RCYU 131606Z ... 或 SPECI RCYU 131606Z ...
        rf"\b((?:METAR|SPECI)\s+{icao}\s+\d{{6}}Z\s+[^=]{{10,320}}=?)",

        # 沒有 METAR / SPECI 開頭：RCYU 131606Z ...
        rf"\b({icao}\s+\d{{6}}Z\s+[^=]{{10,320}}=?)"
    ]

    for pattern in patterns:
        matches = re.finditer(pattern, content)

        for match in matches:
            raw_report = trim_report(match.group(1), icao)

            if is_valid_report(icao, raw_report):
                return raw_report

    return ""


def fetch_from_aoaws_by_selenium(target_airports):
    """
    第二來源：AOAWS 台灣航空氣象服務網。
    用 Selenium 補抓 AviationWeather 沒有的機場，尤其 RCBS / RCNN / RCYU。
    """
    target_airports = list(dict.fromkeys(target_airports))

    if not target_airports:
        return {}

    print("開始用 AOAWS 補抓機場：", ", ".join(target_airports))

    result = {}
    remaining = set(target_airports)
    driver = None

    chrome_options = Options()
    chrome_options.page_load_strategy = "none"

    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")

    urls = [
        "https://aoaws.anws.gov.tw/Report",
        "https://aoaws.anws.gov.tw/#gsc.tab=0",
        "https://aoaws.anws.gov.tw/",
        "https://aoaws.anws.gov.tw/AWS/obs.php"
    ]

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(25)

        for url in urls:
            if not remaining:
                break

            print("正在開啟 AOAWS:", url)

            try:
                driver.get(url)
            except Exception as e:
                print("AOAWS driver.get timeout，繼續讀取目前頁面：", e)
                try:
                    driver.execute_script("window.stop();")
                except Exception:
                    pass

            time.sleep(8)

            html_content = driver.page_source or ""

            try:
                text_content = driver.execute_script(
                    "return document.body ? document.body.innerText : '';"
                )
            except Exception:
                text_content = ""

            print("AOAWS page_source 長度：", len(html_content))
            print("AOAWS innerText 長度：", len(text_content))

            current_content = html_content + "\n" + text_content

            for check_icao in list(remaining):
                if check_icao in current_content:
                    print(f"AOAWS 內容中有找到 {check_icao} 字樣")
                else:
                    print(f"AOAWS 內容中沒有找到 {check_icao} 字樣")

                raw_report = extract_report_from_content(current_content, check_icao)

                if raw_report:
                    result[check_icao] = make_weather_item(check_icao, raw_report)
                    remaining.remove(check_icao)
                    print(f"AOAWS 補抓成功 {check_icao}: {raw_report}")
                else:
                    print(f"AOAWS 目前頁面仍找不到 {check_icao}")

        if remaining:
            print("AOAWS 最後仍找不到：", ", ".join(sorted(remaining)))

    except Exception as e:
        print("AOAWS Selenium 補抓失敗：", e)

    finally:
        if driver is not None:
            driver.quit()

    return result


def merge_weather(aviation_weather, aoaws_weather):
    """
    合併 AviationWeather 與 AOAWS。
    如果 AOAWS 比較新，就覆蓋。
    如果 AviationWeather 沒有某機場，AOAWS 有，就補上。
    """
    merged = dict(aviation_weather)

    for icao, item in aoaws_weather.items():
        if not item.get("rawOb"):
            continue

        new_time = int(item.get("obsTime", 0))
        old_time = int(merged.get(icao, {}).get("obsTime", 0))

        if icao not in merged or new_time >= old_time:
            print(f"使用 AOAWS 補強/覆蓋 {icao}: {item['rawOb']}")
            merged[icao] = item
        else:
            print(f"AOAWS 有 {icao}，但資料較舊，不覆蓋")

    return merged


def fetch_aoaws_metar():
    print("目前工作目錄：", os.getcwd())

    old_weather = load_old_weather()

    # 第一階段：先抓 AviationWeather
    aviation_weather = fetch_from_aviationweather()

    # 第二階段：AOAWS 固定補強缺資料 + 軍民合用/非全天候機場
    aoaws_targets = []

    for icao in AIRPORTS:
        if icao not in aviation_weather:
            aoaws_targets.append(icao)

    for icao in LIMITED_AIRPORTS:
        aoaws_targets.append(icao)

    aoaws_targets = list(dict.fromkeys(aoaws_targets))

    aoaws_weather = fetch_from_aoaws_by_selenium(aoaws_targets)

    new_weather = merge_weather(aviation_weather, aoaws_weather)

    weather_data = []

    for icao in AIRPORTS:
        if icao in new_weather and new_weather[icao].get("rawOb"):
            item = new_weather[icao]
            item["status"] = "updated"
            weather_data.append(item)

        elif icao in old_weather and old_weather[icao].get("rawOb"):
            print(f"{icao} 這次沒抓到，保留舊資料")

            item = old_weather[icao]
            item["status"] = "old_data_kept"
            weather_data.append(item)

        else:
            print(f"{icao} 沒有新資料，也沒有舊資料，建立空資料")

            weather_data.append({
                "icaoId": icao,
                "obsTime": int(time.time()),
                "rawOb": "",
                "visib": "",
                "status": "暫無最新報文，可能為非作業時段"
            })

    with open("local_weather.json", "w", encoding="utf-8") as f:
        json.dump(weather_data, f, ensure_ascii=False, indent=4)

    print("資料已成功寫入 local_weather.json")
    print("最後輸出筆數：", len(weather_data))

    print("========== 最後輸出內容 ==========")
    for item in weather_data:
        print(item["icaoId"], "=>", item.get("rawOb", ""))


if __name__ == "__main__":
    fetch_aoaws_metar()
