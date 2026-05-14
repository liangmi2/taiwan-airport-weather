async function fetchWeather() {
  const loadingDiv = document.getElementById("loading");
  const container = document.getElementById("weather-cards");

  if (!container) return;

  if (loadingDiv) {
    loadingDiv.style.display = "block";
    loadingDiv.style.color = "#708392";
    loadingDiv.innerText = "正在即時連線抓取各機場氣象報文...";
  }

  // 使用上方定義好的 airports 清單
  const icaos = Object.keys(airports);
  let weatherMap = {};

  // 1. 先向 NOAA 發送請求 (支援跨網域 CORS，穩定且速度快)
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

  // 2. 檢查是否有缺漏 (通常是 RCBS, RCYU)，觸發前端 ANWS 備援機制
  const missing = icaos.filter(icao => !weatherMap[icao] || !weatherMap[icao].rawOb);
  
  if (missing.length > 0) {
    console.log(`NOAA 缺少 ${missing.join(', ')}，啟動 ANWS 前端備援...`);
    try {
      // 透過公開的 CORS Proxy 繞過瀏覽器的安全性跨網域阻擋
      const targetUrl = 'https://aoaws.anws.gov.tw/Home/get_metar_data';
      const proxyUrl = `https://corsproxy.io/?url=${encodeURIComponent(targetUrl)}`;
      
      const res = await fetch(proxyUrl, {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'Content-Type': 'application/x-www-form-urlencoded'
        },
        body: '' // 發送空 Payload 觸發全台資料回傳
      });

      if (res.ok) {
        const data = await res.json();
        if (data.latest_airport_list && data.latest_airport_list.Taiwan) {
          data.latest_airport_list.Taiwan.forEach(airport => {
            const stid = airport.STID;
            if (missing.includes(stid)) {
              let report = airport.REPORT.replace(/\n/g, " ").replace(/=/g, "").trim();
              
              // 在 JS 中解析時間戳記
              let obsTime = Math.floor(Date.now() / 1000);
              const timeMatch = report.match(/\b(\d{2})(\d{2})(\d{2})Z\b/);
              if (timeMatch) {
                 const now = new Date();
                 const dt = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), parseInt(timeMatch[1], 10), parseInt(timeMatch[2], 10), parseInt(timeMatch[3], 10)));
                 obsTime = Math.floor(dt.getTime() / 1000);
              }
              
              // 在 JS 中解析能見度並轉為英里 (配合前端原有邏輯)
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
      }
    } catch (err) {
      console.error("ANWS 備援抓取失敗:", err);
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

  // 更新畫面的更新時間與天氣卡片
  updateLastUpdateText(finalData);
  displayWeather(finalData);

  if (loadingDiv) {
    loadingDiv.style.display = "none";
  }
}
