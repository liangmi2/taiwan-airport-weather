from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import re
import json

def fetch_aoaws_metar():
    url = "https://aoaws.anws.gov.tw/AWS/obs.php"
    
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    # 禁用圖片加載以提升速度
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    
    driver = None
    try:
        print("🤖 啟動雲端模擬瀏覽器...")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        print(f"🌐 前往 AOAWS 網站: {url}")
        driver.get(url)
        
        # 關鍵：等待畫面上出現 "RCTP" (桃園機場) 的文字，最長等 30 秒
        print("⏳ 等待氣象數據渲染...")
        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'RCTP')]"))
            )
            print("✅ 數據加載成功！")
        except:
            print("⚠️ 等待超時，嘗試直接讀取內容...")

        # 額外緩衝 3 秒確保 JavaScript 跑完
        time.sleep(3)
        
        # 取得完整網頁內容
        search_content = driver.page_source
        print(f"📄 抓取內容長度: {len(search_content)}")
        
        airports = ["RCTP", "RCSS", "RCKH", "RCMQ", "RCBS", "RCWA", "RCYU", "RCQC"]
        weather_data = []

        for icao in airports:
            # 正則表達式抓取報文
            pattern = rf"({icao}\s+\d{{6}}Z.*?)(?:=|<|\n)"
            match = re.search(pattern, search_content)
            
            if match:
                raw_metar = match.group(1).replace("<", "").replace("=", "").strip()
                
                # 能見度解析
                visib_match = re.search(r"\s(\d{4})\s", raw_metar)
                visibility_miles = ""
                if visib_match:
                    meters = int(visib_match.group(1))
                    visibility_miles = "6.2" if meters == 9999 else str(round(meters / 1609.34, 2))

                weather_data.append({
                    "icaoId": icao,
                    "obsTime": int(time.time()),
                    "rawOb": raw_metar,
                    "visib": visibility_miles
                })
                print(f"✔️ {icao} 已擷取")

        if weather_data:
            with open('local_weather.json', 'w', encoding='utf-8') as f:
                json.dump(weather_data, f, ensure_ascii=False, indent=4)
            print(f"\n🎉 成功抓取 {len(weather_data)} 筆資料並存入 JSON")
        else:
            raise RuntimeError("❌ 網頁內容解析失敗，未抓到任何資料")
            
    except Exception as e:
        print(f"❗ 執行錯誤: {e}")
        exit(1) # 讓 GitHub Actions 知道失敗了
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    fetch_aoaws_metar()
