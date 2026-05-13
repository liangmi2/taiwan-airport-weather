const airports = {
  RCTP: "桃園國際機場 (TPE)",
  RCSS: "台北松山機場 (TSA)",
  RCKH: "高雄小港機場 (KHH)",
  RCMQ: "台中清泉崗機場 (RMQ)",
  RCBS: "金門尚義機場 (KNH)",
  RCNN: "台南機場 (TNN)",
  RCYU: "花蓮機場 (HUN)",
  RCQC: "馬公機場 (MZG)"
};

// 官方資料連結
const officialUrl = "https://aoaws.anws.gov.tw/";

// HTML 防呆，避免 METAR 裡有特殊字元影響畫面
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// 風向角度轉中文
function getWindDirection(degrees) {
  if (!degrees) return "--";

  if (degrees === "VRB") {
    return "風向不定";
  }

  const deg = parseInt(degrees, 10);

  if (Number.isNaN(deg)) {
    return "--";
  }

  const dirs = [
    "北風",
    "東北風",
    "東風",
    "東南風",
    "南風",
    "西南風",
    "西風",
    "西北風",
    "北風"
  ];

  return dirs[Math.round((deg % 360) / 45)];
}

// 蒲福風級，輸入 knots
function getBeaufortScale(knots) {
  if (knots < 1) return 0;
  if (knots <= 3) return 1;
  if (knots <= 6) return 2;
  if (knots <= 10) return 3;
  if (knots <= 16) return 4;
  if (knots <= 21) return 5;
  if (knots <= 27) return 6;
  if (knots <= 33) return 7;
  if (knots <= 40) return 8;
  if (knots <= 47) return 9;
  if (knots <= 55) return 10;
  if (knots <= 63) return 11;
  return 12;
}

// 判斷天氣圖示與文字
function getWeatherInfo(rawMetar) {
  const metar = String(rawMetar || "").toUpperCase();

  if (!metar) {
    return {
      icon: "❓",
      text: "未知"
    };
  }

  if (metar.includes("TS")) {
    return {
      icon: "⛈️",
      text: "雷雨"
    };
  }

  if (metar.includes("+RA")) {
    return {
      icon: "🌧️",
      text: "大雨"
    };
  }

  if (
    metar.includes("-RA") ||
    metar.includes(" RA ") ||
    metar.includes("DZ") ||
    metar.includes("SHRA") ||
    metar.includes("VCSH")
  ) {
    return {
      icon: "🌧️",
      text: "下雨"
    };
  }

  if (
    metar.includes("FG") ||
    metar.includes("BR") ||
    metar.includes("HZ") ||
    metar.includes("FU")
  ) {
    return {
      icon: "🌫️",
      text: "霧霾"
    };
  }

  if (metar.includes("OVC") || metar.includes("BKN")) {
    return {
      icon: "☁️",
      text: "陰天"
    };
  }

  if (metar.includes("SCT") || metar.includes("FEW")) {
    return {
      icon: "⛅",
      text: "多雲"
    };
  }

  if (metar.includes("CAVOK") || metar.includes("SKC") || metar.includes("CLR")) {
    return {
      icon: "☀️",
      text: "晴朗"
    };
  }

  return {
    icon: "🌤️",
    text: "良好"
  };
}

// 解析能見度
function parseVisibility(weather) {
  const rawMetar = String(weather?.rawOb || "").toUpperCase();

  // 台灣 METAR 常見 9999 / 8000 / 7000，這裡優先讀原始報文的公尺值
  const meterMatch = rawMetar.match(/\b(\d{4})\b/);

  if (meterMatch) {
    const meters = parseInt(meterMatch[1], 10);

    if (!Number.isNaN(meters)) {
      if (meters === 9999) {
        return "10000 公尺以上";
      }

      return `${meters} 公尺`;
    }
  }

  // 備援：AviationWeather API 的 visib 通常是 statute miles
  const visib = weather?.visib;

  if (visib !== undefined && visib !== null && visib !== "") {
    const visibText = String(visib).replace("+", "");
    const miles = parseFloat(visibText);

    if (!Number.isNaN(miles)) {
      const meters = Math.round(miles * 1609.34);

      if (String(visib).includes("+")) {
        return `${meters} 公尺以上`;
      }

      return `${meters} 公尺`;
    }
  }

  return "--";
}

// 解析風向風速
function parseWind(rawMetar) {
  const metar = String(rawMetar || "").toUpperCase();

  const windMatch = metar.match(/\b(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?KT\b/);

  if (!windMatch) {
    return "--";
  }

  const direction = windMatch[1];
  const speedKt = parseInt(windMatch[2], 10);
  const gustKt = windMatch[3] ? parseInt(windMatch[3], 10) : null;

  if (Number.isNaN(speedKt)) {
    return "--";
  }

  if (speedKt === 0) {
    return "無風";
  }

  const dirName = getWindDirection(direction);
  const beaufort = getBeaufortScale(speedKt);

  let windText = `${dirName} ${beaufort} 級風`;

  if (gustKt !== null && !Number.isNaN(gustKt)) {
    const gustBeaufort = getBeaufortScale(gustKt);
    windText += `，陣風 ${gustBeaufort} 級`;
  }

  return windText;
}

// 解析溫度
function parseTemperature(rawMetar) {
  const metar = String(rawMetar || "").toUpperCase();

  const tempMatch = metar.match(/\b(M?\d{2})\/(M?\d{2}|\/\/)?\b/);

  if (!tempMatch) {
    return "--";
  }

  const temp = tempMatch[1].replace("M", "-");
  const tempValue = parseInt(temp, 10);

  if (Number.isNaN(tempValue)) {
    return "--";
  }

  return `${tempValue}°C`;
}

// 解析觀測時間
function formatObsTime(obsTime) {
  if (!obsTime) {
    return "";
  }

  const timestamp = Number(obsTime);

  if (Number.isNaN(timestamp)) {
    return "";
  }

  const date = new Date(timestamp * 1000);

  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return date.toLocaleString("zh-TW", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

// 建立 weather map，避免同機場多筆資料時取最新
function buildWeatherMap(data) {
  const weatherMap = {};

  if (!Array.isArray(data)) {
    return weatherMap;
  }

  data.forEach(item => {
    if (!item || !item.icaoId) {
      return;
    }

    const icao = item.icaoId;

    if (!weatherMap[icao]) {
      weatherMap[icao] = item;
      return;
    }

    const oldTime = Number(weatherMap[icao].obsTime || 0);
    const newTime = Number(item.obsTime || 0);

    if (newTime >= oldTime) {
      weatherMap[icao] = item;
    }
  });

  return weatherMap;
}

// 讀取 local_weather.json
async function fetchWeather() {
  const loadingDiv = document.getElementById("loading");
  const container = document.getElementById("weather-cards");

  if (!container) {
    console.error("找不到 #weather-cards 容器");
    return;
  }

  if (loadingDiv) {
    loadingDiv.style.display = "block";
    loadingDiv.style.color = "#7f8c8d";
    loadingDiv.innerText = "正在讀取氣象資料...";
  }

  const localUrl = `./local_weather.json?t=${Date.now()}`;

  try {
    const res = await fetch(localUrl, {
      cache: "no-store"
    });

    if (!res.ok) {
      throw new Error(`讀取 local_weather.json 失敗，HTTP ${res.status}`);
    }

    const data = await res.json();

    if (!Array.isArray(data)) {
      throw new Error("local_weather.json 格式不是陣列");
    }

    if (data.length === 0 && loadingDiv) {
      loadingDiv.innerText = "⚠️ local_weather.json 目前是空的。";
    }

    displayWeather(data, data.length === 0);
  } catch (err) {
    console.error(err);

    if (loadingDiv) {
      loadingDiv.style.display = "block";
      loadingDiv.style.color = "#c0392b";
      loadingDiv.innerText = "⚠️ 無法讀取本地氣象資料，請確認 local_weather.json 是否存在。";
    }

    displayWeather([], true);
  }
}

// 顯示卡片
function displayWeather(data, keepLoadingDivVisible = false) {
  const container = document.getElementById("weather-cards");
  const loadingDiv = document.getElementById("loading");

  if (!container) {
    return;
  }

  container.innerHTML = "";

  if (loadingDiv && !keepLoadingDivVisible) {
    loadingDiv.style.display = "none";
  }

  const weatherMap = buildWeatherMap(data);

  Object.keys(airports).forEach(icao => {
    const airportName = airports[icao];
    const weather = weatherMap[icao];

    let rawMetar = "目前沒有抓到這個機場的資料";
    let visibilityText = "--";
    let windText = "--";
    let tempText = "--";
    let obsTimeText = "";
    let weatherInfo = {
      icon: "❓",
      text: "未知"
    };

    if (weather && weather.rawOb) {
      rawMetar = weather.rawOb;
      visibilityText = parseVisibility(weather);
      windText = parseWind(rawMetar);
      tempText = parseTemperature(rawMetar);
      obsTimeText = formatObsTime(weather.obsTime);
      weatherInfo = getWeatherInfo(rawMetar);
    }

    const card = document.createElement("div");
    card.className = "card";

    card.innerHTML = `
      <h2>${escapeHtml(airportName)}</h2>

      <div class="weather-main">
        <div class="weather-icon">${weatherInfo.icon}</div>
        <div class="weather-summary">
          <div class="temperature">${escapeHtml(tempText)}</div>
          <div class="condition">${escapeHtml(weatherInfo.text)}</div>
        </div>
      </div>

      <div class="info-box">
        <div class="info-row">
          <span class="label">🌬️ 風向風速</span>
          <span class="value">${escapeHtml(windText)}</span>
        </div>

        <div class="info-row">
          <span class="label">👁️ 能見度</span>
          <span class="value visibility">${escapeHtml(visibilityText)}</span>
        </div>
      </div>

      <div class="metar-box">
        ${escapeHtml(rawMetar)}
      </div>

      ${obsTimeText ? `<div class="update-time">更新時間：${escapeHtml(obsTimeText)}</div>` : ""}

      <a class="radar-button" href="${officialUrl}" target="_blank" rel="noopener noreferrer">
        🔍 官方雷達與資料
      </a>
    `;

    container.appendChild(card);
  });
}

// 頁面載入後執行
document.addEventListener("DOMContentLoaded", () => {
  fetchWeather();

  // 每 5 分鐘自動刷新一次
  setInterval(fetchWeather, 5 * 60 * 1000);
});
