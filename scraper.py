from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
import re
import json

def fetch_aoaws_metar():
    url = "https://aoaws.anws.gov.tw/AWS/obs.php"
    
    # 設定 Chrome 為無頭模式，並加入「雲端環境專用」的穩定參數
    chrome_options = Options()
    chrome_options.add_argument("--headless")                  # 必須：在背景執行不彈出視窗
    chrome_options.add_argument("--no-sandbox")                # 雲端 Linux 環境必須
    chrome_options.add_argument("--disable-dev-shm-usage")     # 防止雲端容器記憶體溢出崩潰
    chrome_options.add_argument("--disable-gpu")               # 停用 GPU 硬體加速
    chrome_options.add_argument("--window-size=1920,1080")     # 設定虛擬螢幕大小確保排版正常
    
    print("🤖 正在雲端背景啟動模擬瀏覽器...")
    try:
        # 自動下載並設定對應版本的 ChromeDriver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        print(f"🌐 正在前往 AOAWS 網站並等待資料載入...")
        driver.get(url)
        
        # 讓瀏覽器等待 10 秒，確保動態 JavaScript 已經把氣象資料畫到畫面上
        time.sleep(10) 
        
        # 抓取「渲染完畢後」的完整網頁原始碼
        html_content = driver.page_source
        
        airports = ['RCTP', 'RCSS', 'RCKH', 'RCMQ', 'RCBS', 'RCWA', 'RCYU', 'RCQC']
        weather_data = []
        
        for icao in airports:
            # 匹配特徵：ICAO代碼 + 6位數字Z(時間) + 任意字元直到遇到換行或標籤
            pattern = rf'({icao}\s+\d{{6}}Z.*?)(?:=|<|\n)'
            match = re.search(pattern, html_content)
            
            if match:
                raw_metar = match.group(1).replace('<', '').replace('=', '').strip()
                
                # 從報文中萃取能見度數字 (例如 9999 或 4000)
                visib_match = re.search(r'\s(\d{4})\s', raw_metar)
                visibility_miles = ""
                
                if visib_match:
                    meters = int(visib_match.group(1))
                    if meters == 9999:
                        visibility_miles = "6.2" # 航空氣象中 9999 代表 10 公里以上
                    else:
                        # 換算為前端 app.js 預期接收的英里格式，讓前端再去轉回公尺
                        visibility_miles = str(round(meters / 1609.34, 2))
                        
                weather_data.append({
                    "icaoId": icao,
                    "obsTime": int(time.time()),
                    "rawOb": raw_metar,
                    "visib": visibility_miles
                })
                print(f"✅ 成功抓取 {icao} 最新報文")
            else:
                print(f"⚠️ 網頁中找不到 {icao} 的資料")
                
        # 存入 json 提供給前端 PWA 讀取
        if weather_data:
            with open('local_weather.json', 'w', encoding='utf-8') as f:
                json.dump(weather_data, f, ensure_ascii=False, indent=4)
            print("\n🎉 資料已成功整理並存入 local_weather.json！")
        else:
            print("\n❌ 抓取失敗：網頁中未解析到任何機場資料。")
            
    except Exception as e:
        print(f"執行發生錯誤: {e}")
    finally:
        try:
            driver.quit() # 確保最後有把背景瀏覽器關閉，釋放雲端資源
        except:
            pass

if __name__ == "__main__":
    fetch_aoaws_metar()