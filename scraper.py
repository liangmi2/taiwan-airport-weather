from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
import re
import json
import os


def fetch_aoaws_metar():
    driver = None
    url = "https://aoaws.anws.gov.tw/AWS/obs.php"

    chrome_options = Options()
    chrome_options.page_load_strategy = "none"

    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--window-size=1920,1080")

    print("目前工作目錄：", os.getcwd())
    print("正在雲端背景啟動模擬瀏覽器...")

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)

        driver.set_page_load_timeout(30)

        print("正在前往 AOAWS 網站並等待資料載入...")

        try:
            driver.get(url)
        except Exception as e:
            print("driver.get timeout，但繼續嘗試讀取目前頁面：", e)
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass

        time.sleep(15)

        html_content = driver.page_source
        text_content = driver.execute_script("return document.body ? document.body.innerText : '';")

        print("page_source 長度：", len(html_content))
        print("innerText 長度：", len(text_content))

        search_content = text_content if text_content else html_content

        airports = ["RCTP", "RCSS", "RCKH", "RCMQ", "RCBS", "RCWA", "RCYU", "RCQC"]
        weather_data = []

        for icao in airports:
            pattern = rf"({icao}\s+\d{{6}}Z.*?)(?:=|<|\n)"
            match = re.search(pattern, search_content)

            if match:
                raw_metar = match.group(1).replace("<", "").replace("=", "").strip()

                visib_match = re.search(r"\s(\d{4})\s", raw_metar)
                visibility_miles = ""

                if visib_match:
                    meters = int(visib_match.group(1))
                    if meters == 9999:
                        visibility_miles = "6.2"
                    else:
                        visibility_miles = str(round(meters / 1609.34, 2))

                weather_data.append({
                    "icaoId": icao,
                    "obsTime": int(time.time()),
                    "rawOb": raw_metar,
                    "visib": visibility_miles
                })

                print(f"成功抓取 {icao} 最新報文：{raw_metar}")
            else:
                print(f"網頁中找不到 {icao} 的資料")

        print("抓到幾筆資料：", len(weather_data))

        if weather_data:
            with open("local_weather.json", "w", encoding="utf-8") as f:
                json.dump(weather_data, f, ensure_ascii=False, indent=4)

            print("資料已成功整理並存入 local_weather.json！")
        else:
            print("抓取失敗：網頁中未解析到任何機場資料。")
            raise RuntimeError("未解析到任何機場資料")

    finally:
        if driver is not None:
            driver.quit()


if __name__ == "__main__":
    fetch_aoaws_metar()
