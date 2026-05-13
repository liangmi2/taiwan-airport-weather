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


def parse_metar_obs_time(raw_report):
    """
    從 METAR / SPECI 內的 131606Z 解析成 Unix timestamp。
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
    從 METAR / SPECI 原文抓能見度，例如 9999 / 8000 / 7000。
    轉成前端原本使用的英里格式。
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
    若這次某機場抓不到新資料，就用舊資料補上。
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
    重點：
    1. 保留 METAR 開頭
    2. 保留 SPECI 開頭
    3. 不要把 SPECI 錯誤改成 METAR SPECI
    """
    if not raw:
        return ""

    raw = html.unescape(str(raw))
    raw = raw.replace("\\n", " ")
    raw = raw.replace("\\/", "/")
    raw = raw.replace("=", "")
    raw = re.sub(r"\s+", " ", raw).strip()

    if raw.startswith("METAR ") or raw.startswith("SPECI "):
        return raw

    # 有些來源可能只給：RCYU 131606Z 26002KT...
    # 這種才補 METAR
    if re.match(r"^[A-Z]{4}\s+\d{6}Z", raw):
        return "METAR " + raw

    return raw


def make_weather_item(icao, raw_report):
    raw_report = normalize_raw_report(raw_report)

    return {
        "icaoId": icao,
        "obsTime": parse_metar_obs_time(raw_report),
        "rawOb": raw_report,
        "visib": parse_visibility_from_raw(raw_report)
    }


def fetch_from_aviationweather():
    """
    第一來源：AviationWeather API。
    這個來源比較穩，但有時不會回傳台灣所有機場。
    """
    ids = ",".join(AIRPORTS)

    url = (
        "https://aviationweather.gov/api/data/metar"
        f"?ids={ids}&format=json&taf=false&hours=24"
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

        print("AviationWeather API 回傳筆數：", len(data))

        for item in data:
            icao = item.get("icaoId")

            if icao not in AIRPORTS:
                continue

            raw_report = item.get("rawOb", "").strip()

            if not raw_report:
                continue

            raw_report = normalize_raw_report(raw_report)

            # 支援 METAR / SPECI
            if not (
                raw_report.startswith("METAR ") or
                raw_report.startswith("SPECI ")
            ):
                raw_report = normalize_raw_report(raw_report)

            visib = item.get("visib")

            if visib is None or visib == "":
                visibility = parse_visibility_from_raw(raw_report)
            else:
                visibility = str(visib).replace("+", "")

            result[icao] = {
                "icaoId": icao,
                "obsTime": parse_metar_obs_time(raw_report),
                "rawOb": raw_report,
                "visib": visibility
            }

            print(f"AviationWeather 成功抓取 {icao}: {raw_report}")

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
    content = content.replace("\\n", " ")
    content = content.replace("\\/", "/")
    content = re.sub(r"<[^>]+>", " ", content)
    content = re.sub(r"\s+", " ", content)

    patterns = [
        # METAR / SPECI 開頭
        rf"\b((?:METAR|SPECI)\s+{icao}\s+\d{{6}}Z\s+.*?)(?=\s+(?:METAR|SPECI)\s+[A-Z]{{4}}\s+\d{{6}}Z|=|$)",

        # 沒有 METAR / SPECI 開頭
        rf"\b({icao}\s+\d{{6}}Z\s+.*?)(?=\s+[A-Z]{{4}}\s+\d{{6}}Z|=|$)"
    ]

    for pattern in patterns:
        match = re.search(pattern, content)

        if match:
            raw_report = normalize_raw_report(match.group(1))

            # 防止抓太長，把網頁其他文字吃進來
            stop_words = [
                " TAF ",
                " Station ",
                " 最新報告 ",
                " 機場天氣 ",
                " 觀測資料 ",
                " 全球機場天氣 ",
                " Copyright "
            ]

            for word in stop_words:
                if word in raw_report:
                    raw_report = raw_report.split(word)[0].strip()

            raw_report = raw_report.strip()

            if icao in raw_report and re.search(r"\d{6}Z", raw_report):
                return raw_report

    return ""


def fetch_from_aoaws_by_selenium(missing_airports):
    """
    第二來源：AOAWS 台灣航空氣象服務網。
    用來補 AviationWeather 沒有回傳的機場。
    """
    if not missing_airports:
        return {}

    print("開始用 AOAWS 補抓缺少的機場：", ", ".join(missing_airports))

    result = {}
    driver = None

    chrome_options = Options()
    chrome_options.page_load_strategy = "none"

    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--window-size=1920,1080")

    urls = [
        "https://aoaws.anws.gov.tw/#gsc.tab=0",
        "https://aoaws.anws.gov.tw/",
        "https://aoaws.anws.gov.tw/AWS/obs.php",
        "https://aoaws.anws.gov.tw/Report"
    ]

    all_content = ""

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(30)

        for url in urls:
            print("正在開啟 AOAWS:", url)

            try:
                driver.get(url)
            except Exception as e:
                print("AOAWS driver.get timeout，繼續讀取目前頁面：", e)
                try:
                    driver.execute_script("window.stop();")
                except Exception:
                    pass

            time.sleep(12)

            html_content = driver.page_source or ""

            try:
                text_content = driver.execute_script(
                    "return document.body ? document.body.innerText : '';"
                )
            except Exception:
                text_content = ""

            print("AOAWS page_source 長度：", len(html_content))
            print("AOAWS innerText 長度：", len(text_content))

            all_content += "\n" + html_content + "\n" + text_content

        for icao in missing_airports:
            raw_report = extract_report_from_content(all_content, icao)

            if raw_report:
                result[icao] = make_weather_item(icao, raw_report)
                print(f"AOAWS 補抓成功 {icao}: {raw_report}")
            else:
                print(f"AOAWS 仍找不到 {icao}")

    except Exception as e:
        print("AOAWS Selenium 補抓失敗：", e)

    finally:
        if driver is not None:
            driver.quit()

    return result


def fetch_aoaws_metar():
    print("目前工作目錄：", os.getcwd())

    old_weather = load_old_weather()

    new_weather = fetch_from_aviationweather()

    missing = [
        icao
        for icao in AIRPORTS
        if icao not in new_weather
    ]

    if missing:
        aoaws_weather = fetch_from_aoaws_by_selenium(missing)
        new_weather.update(aoaws_weather)

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
