// 核心抓取邏輯 (強化容錯版)
async function fetchWeather() {
  const loadingDiv = document.getElementById("loading");
  const container = document.getElementById("weather-cards");

  if (!container) return;

  if (loadingDiv) {
    loadingDiv.style.display = "block";
    loadingDiv.style.color = "#708392";
    loadingDiv.innerText = "正在即時連線抓取各機場氣象報文...";
  }

  const icaos = Object.keys(airports);
  let weatherMap = {};

  try {
    // 1. 先向 NOAA 發送請求
    try {
      const noaaUrl = `https://aviationweather.gov/api/data/metar?ids=${icaos.join(',')}&format=json&taf=false&hours=6`;
      const res = await fetch(noaaUrl);
      if (res.ok) {
        const data = await res.json();
        data.forEach(item => {
          if (icaos.includes(item.icaoId)) {
            const newTime = Number(item.obsTime || item.reportTime || 0);
            const oldTime = weatherMap[item.icaoId] ? Number(weatherMap[item.icaoId].obsTime) : 0;
            if (newTime >= oldTime) {
              weatherMap[item.icaoId] = item;
              weatherMap[item.icaoId].status = 'updated';
            }
          }
        });
      }
    } catch (err) {
      console.error("NOAA API 抓取失敗:", err);
    }

    // 2. 檢查缺漏，觸發前端 ANWS 備援
    const missing = icaos.filter(icao => !weatherMap[icao] || !weatherMap[icao].rawOb);
    
    if (missing.length > 0) {
      console.log(`NOAA 缺少 ${missing.join(', ')}，啟動 ANWS 前端備援...`);
      try {
        const targetUrl = 'https://aoaws.anws.gov.tw/Home/get_metar_data';
        const proxyUrl = `https://corsproxy.io/?url=${encodeURIComponent(targetUrl)}`;
        
        const res = await fetch(proxyUrl, {
          method: 'POST',
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded'
          },
          body: '' 
        });

        if (res.ok) {
          const data = await res.json();
          if (data.latest_airport_list && data.latest_airport_list.Taiwan) {
            data.latest_airport_list.Taiwan.forEach(airport => {
              const stid = airport.STID;
              
              // 【加上防呆】確認 target 存在且 REPORT 不是空值才進行處理
              if (missing.includes(stid) && airport.REPORT) {
                let report = String(airport.REPORT).replace(/\n/g, " ").replace(/=/g, "").trim();
                
                // 解析時間戳記
                let obsTime = Math.floor(Date.now() / 1000);
                const timeMatch = report.match(/\b(\d{2})(\d{2})(\d{2})Z\b/);
                if (timeMatch) {
                   const now = new Date();
                   const dt = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), parseInt(timeMatch[1], 10), parseInt(timeMatch[2], 10), parseInt(timeMatch[3], 10)));
                   obsTime = Math.floor(dt.getTime() / 1000);
                }
                
                // 解析能見度
                let visib = "";
                const visMatch = report.match(/\s(\d{4})\s/);
                if (visMatch) {
                   const meters = parseInt(visMatch[1], 10);
                   visib = meters >= 9999 ? "6.2" : (meters / 1609.34).toFixed(2);
                }

                weatherMap[stid] = {
                  icaoId: stid,
                  obsTime: obsTime,
                  rawOb: report,
                  visib: visib,
                  status: 'updated_from_anws'
                };
              }
            });
          }
        } else {
          console.error("Proxy 伺服器回傳錯誤狀態碼:", res.status);
        }
      } catch (err) {
        console.error("ANWS 備援連線失敗 (可能是 Proxy 或 CORS 阻擋):", err);
      }
    }

    // 3. 整理最終陣列並交給畫面渲染
    const finalData = icaos.map(icao => {
      if (weatherMap[icao] && weatherMap[icao].rawOb) {
         return weatherMap[icao];
      }
      return {
        icaoId: icao,
        obsTime: 0,
        rawOb: "",
        visib: "",
        status: "暫無最新報文，可能為非作業時段"
      };
    });

    updateLastUpdateText(finalData);
    displayWeather(finalData);

  } catch (fatalError) {
    // 【終極防護】如果發生任何預期外的嚴重當機，把錯誤印出來，並顯示錯誤給使用者看
    console.error("發生嚴重錯誤:", fatalError);
    if (loadingDiv) {
      loadingDiv.style.color = "#d93025";
      loadingDiv.innerHTML = "⚠️ 載入時發生錯誤，請按 <strong>F12</strong> 查看 Console 主控台。";
    }
    return; // 終止執行
  }

  // 正常跑完後隱藏讀取文字
  if (loadingDiv) {
    loadingDiv.style.display = "none";
  }
}
