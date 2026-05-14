const airports = {
  RCTP: { name: "桃園國際機場", iata: "TPE", type: "major" },
  RCSS: { name: "台北松山機場", iata: "TSA", type: "major" },
  RCKH: { name: "高雄小港機場", iata: "KHH", type: "major" },
  RCMQ: { name: "台中清泉崗機場", iata: "RMQ", type: "mixed" },
  RCBS: { name: "金門尚義機場", iata: "KNH", type: "limited" },
  RCNN: { name: "台南機場", iata: "TNN", type: "limited" },
  RCYU: { name: "花蓮機場", iata: "HUN", type: "limited" },
  RCQC: { name: "馬公機場", iata: "MZG", type: "major" }
};

const officialUrl = "https://aoaws.anws.gov.tw/";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function getWindDirection(degrees) {
  if (!degrees) return "--";
  if (degrees === "VRB") return "風向不定";
  const deg = parseInt(degrees, 10);
  if (Number.isNaN(deg)) return "--";
  const dirs = ["北風", "東北風", "東風", "東南風", "南風", "西南風", "西風", "西北風", "北風"];
  return dirs[Math.round((deg % 360) / 45)];
}

function knotsToKmh(knots) {
  return Math.round(knots * 1.852);
}

function parseWind(rawMetar) {
  const metar = String(rawMetar || "").toUpperCase();
  const windMatch = metar.match(/\b(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?KT\b/);
  if (!windMatch) return "--";

  const direction = windMatch[1];
  const speedKt = parseInt(windMatch[2], 10);
  const gustKt = windMatch[3] ? parseInt(windMatch[3], 10) : null;

  if (Number.isNaN(speedKt)) return "--";
  if (speedKt === 0) return "無風";

  const dirName = getWindDirection(direction);
  const speedKmh = knotsToKmh(speedKt);
  let text = `${dirName} ${speedKmh} km/h`;

  if (gustKt !== null && !Number.isNaN(gustKt)) {
    text += `，陣風 ${knotsToKmh(gustKt)} km/h`;
  }
  return text;
}

function parseTemperature(rawMetar) {
  const metar = String(rawMetar || "").toUpperCase();
  const tempMatch = metar.match(/\b(M?\d{2})\/(M?\d{2}|\/\/)?\b/);
  if (!tempMatch) return "--";

  const tempText = tempMatch[1].replace("M", "-");
  const tempValue = parseInt(tempText, 10);
  if (Number.isNaN(tempValue)) return "--";
  return `${tempValue}°C`;
}

function parseVisibilityMeters(weather) {
  const rawMetar = String(weather?.rawOb || "").toUpperCase();
  const meterMatch = rawMetar.match(/\b(\d{4})\b/);

  if (meterMatch) {
    const meters = parseInt(meterMatch[1], 10);
    if (!Number.isNaN(meters)) {
      if (meters === 9999) return 10000;
      return meters;
    }
  }

  const visib = weather?.visib;
  if (visib !== undefined && visib !== null && visib !== "") {
    const milesText = String(visib).replace("+", "");
    const miles = parseFloat(milesText);
    if (!Number.isNaN(miles)) {
      return Math.round(miles * 1609.34);
    }
  }
  return null;
}

function formatVisibility(weather) {
  const meters = parseVisibilityMeters(weather);
  if (meters === null) return "--";
  if (meters >= 9999) return "10000 公尺以上";
  return `${meters} 公尺`;
}

function getWeatherInfo(rawMetar) {
  const metar = String(rawMetar || "").toUpperCase();
  if (!metar) return { icon: "?", text: "暫無最新報文", empty: true };
  if (metar.includes("TS")) return { icon: "⛈️", text: "雷雨", empty: false };
  if (metar.includes("+RA")) return { icon: "🌧️", text: "大雨", empty: false };
  if (metar.includes("-RA") || metar.includes(" RA ") || metar.includes("DZ") || metar.includes("SHRA") || metar.includes("VCSH")) {
    return { icon: "🌧️", text: "下雨", empty: false };
  }
  if (metar.includes("FG") || metar.includes("BR") || metar.includes("HZ") || metar.includes("FU")) {
    return { icon: "🌫️", text: "霧霾", empty: false };
  }
  if (metar.includes("OVC") || metar.includes("BKN")) return { icon: "☁️", text: "陰天", empty: false };
  if (metar.includes("SCT") || metar.includes("FEW")) return { icon: "⛅", text: "多雲", empty: false };
  if (metar.includes("CAVOK") || metar.includes("SKC") || metar.includes("CLR")) {
    return { icon: "☀️", text: "晴朗", empty: false };
  }
  return { icon: "🌤️", text: "良好", empty: false };
}

function formatObsTime(obsTime) {
  if (!obsTime) return "";
  const timestamp = Number(obsTime);
  if (Number.isNaN(timestamp)) return "";
  const date = new Date(timestamp * 1000);
  if (Number.isNaN(date.getTime())) return "";

  return date.toLocaleString("zh-TW", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function isStaleWeather(weather) {
  if (!weather || !weather.obsTime) return true;
  const now = Date.now();
  const obsTimeMs = Number(weather.obsTime) * 1000;
  if (Number.isNaN(obsTimeMs)) return true;
  const diffHours = (now - obsTimeMs) / 1000 / 60 / 60;
  return diffHours > 6;
}

function getStationStatus(icao, weather) {
  const airport = airports[icao];
  const isLimited = airport?.type === "limited";

  if (weather && weather.rawOb) {
    if (isLimited && isStaleWeather(weather)) {
      return { text: "非作業時段", className: "status-warn", note: "此機場可能因夜間非作業時段，暫無最新報文。" };
    }
    return { text: "資料正常", className: "status-ok", note: "" };
  }

  if (isLimited) {
    return { text: "暫無資料", className: "status-error", note: "此機場可能因夜間非作業時段，暫無最新報文。" };
  }
  return { text: "暫無資料", className: "status-error", note: "目前無法取得此機場的最新氣象資料。" };
}

function getLatestObsTime(data) {
  if (!Array.isArray(data) || data.length === 0) return "";
  const latest = data.reduce((max, item) => {
    const t = Number(item?.obsTime || 0);
    return t > max ? t : max;
  }, 0);
  if (!latest) return "";
  return formatObsTime(latest);
}

function updateLastUpdateText(data) {
  const el = document.getElementById("last-update");
  if (!el) return;
  const latest = getLatestObsTime(data);

  if (latest) {
    el.innerHTML = `
      ⏱️ 最後更新：
      <strong>${escapeHtml(latest)}</strong>
      <span>（畫面每 5 分鐘刷新資料）</span>
    `;
  } else {
    el.innerHTML = "⏱️ 尚未取得更新時間";
  }
}

// 核心抓取邏輯 (取代原本的 fetchWeather)
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
        body: '' 
      });

      if (res.ok) {
        const data = await res.json();
        if (data.latest_airport_list && data.latest_airport_list.Taiwan) {
          data.latest_airport_list.Taiwan.forEach(airport => {
            const stid = airport.STID;
            if (missing.includes(stid)) {
              let report = airport.REPORT.replace(/\n/g, " ").replace(/=/g, "").trim();
              
              // 解析時間戳記
              let obsTime = Math.floor(Date.now() / 1000);
