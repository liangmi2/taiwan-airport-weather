const airports = {
  RCTP: {
    name: "桃園國際機場",
    iata: "TPE",
    type: "major"
  },
  RCSS: {
    name: "台北松山機場",
    iata: "TSA",
    type: "major"
  },
  RCKH: {
    name: "高雄小港機場",
    iata: "KHH",
    type: "major"
  },
  RCMQ: {
    name: "台中清泉崗機場",
    iata: "RMQ",
    type: "mixed"
  },
  RCBS: {
    name: "金門尚義機場",
    iata: "KNH",
    type: "limited"
  },
  RCNN: {
    name: "台南機場",
    iata: "TNN",
    type: "limited"
  },
  RCYU: {
    name: "花蓮機場",
    iata: "HUN",
    type: "limited"
  },
  RCQC: {
    name: "馬公機場",
    iata: "MZG",
    type: "major"
  }
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

function knotsToKmh(knots) {
  return Math.round(knots * 1.852);
}

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

  if (!tempMatch) {
    return "--";
  }

  const tempText = tempMatch[1].replace("M", "-");
  const tempValue = parseInt(tempText, 10);

  if (Number.isNaN(tempValue)) {
    return "--";
  }

  return `${tempValue}°C`;
}

function parseVisibilityMeters(weather) {
  const rawMetar = String(weather?.rawOb || "").toUpperCase();

  const meterMatch = rawMetar.match(/\b(\d{4})\b/);

  if (meterMatch) {
    const meters = parseInt(meterMatch[1], 10);

    if (!Number.isNaN(meters)) {
      if (meters === 9999) {
        return 10000;
      }

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

  if (meters === null) {
    return "--";
  }

  if (meters >= 9999) {
    return "10000 公尺以上";
  }

  return `${meters} 公尺`;
}

function getWeatherInfo(rawMetar) {
  const metar = String(rawMetar || "").toUpperCase();

  if (!metar) {
    return {
      icon: "?",
      text: "暫無最新報文",
      empty: true
    };
  }

  if (metar.includes("TS")) {
    return {
      icon: "⛈️",
      text: "雷雨",
      empty: false
    };
  }

  if (metar.includes("+RA")) {
    return {
      icon: "🌧️",
      text: "大雨",
      empty: false
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
      text: "下雨",
      empty: false
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
      text: "霧霾",
      empty: false
    };
  }

  if (metar.includes("OVC") || metar.includes("BKN")) {
    return {
      icon: "☁️",
      text: "陰天",
      empty: false
    };
  }

  if (metar.includes("SCT") || metar.includes("FEW")) {
    return {
      icon: "⛅",
      text: "多雲",
      empty: false
    };
  }

  if (metar.includes("CAVOK") || metar.includes("SKC") || metar.includes("CLR")) {
    return {
      icon: "☀️",
      text: "晴朗",
      empty: false
    };
  }

  return {
    icon: "🌤️",
    text: "良好",
    empty: false
  };
}

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

function isStaleWeather(weather) {
  if (!weather || !weather.obsTime) {
    return true;
  }

  const now = Date.now();
  const obsTimeMs = Number(weather.obsTime) * 1000;

  if (Number.isNaN(obsTimeMs)) {
    return true;
  }

  const diffHours = (now - obsTimeMs) / 1000 / 60 / 60;

  return diffHours > 6;
}

function getStationStatus(icao, weather) {
  const airport = airports[icao];
  const isLimited = airport?.type === "limited";

  if (weather && weather.rawOb) {
    if (isLimited && isStaleWeather(weather)) {
      return {
        text: "非作業時段",
        className: "status-warn",
        note: "此機場可能因夜間非作業時段，暫無最新報文。"
      };
    }

    return {
      text: "資料正常",
      className: "status-ok",
      note: ""
    };
  }

  if (isLimited) {
    return {
      text: "暫無資料",
      className: "status-error",
      note: "此機場可能因夜間非作業時段，暫無最新報文。"
    };
  }

  return {
    text: "暫無資料",
    className: "status-error",
    note: "目前無法取得此機場的最新氣象資料。"
  };
}

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

function getLatestObsTime(data) {
  if (!Array.isArray(data) || data.length === 0) {
    return "";
  }

  const latest = data.reduce((max, item) => {
    const t = Number(item?.obsTime || 0);
    return t > max ? t : max;
  }, 0);

  if (!latest) {
    return "";
  }

  return formatObsTime(latest);
}

function updateLastUpdateText(data) {
  const el = document.getElementById("last-update");

  if (!el) {
    return;
  }

  const latest = getLatestObsTime(data);

  if (latest) {
    el.innerHTML = `⏱️ 最後更新：<strong>${escapeHtml(latest)}</strong> <span>（每 5 分鐘自動更新）</span>`;
  } else {
    el.innerHTML = "⏱️ 尚未取得更新時間";
  }
}

async function fetchWeather() {
  const loadingDiv = document.getElementById("loading");
  const container = document.getElementById("weather-cards");

  if (!container) {
    console.error("找不到 #weather-cards 容器");
    return;
  }

  if (loadingDiv) {
    loadingDiv.style.display = "block";
    loadingDiv.style.color = "#708392";
    loadingDiv.innerText = "正在讀取機場氣象資料...";
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

    updateLastUpdateText(data);
    displayWeather(data);

    if (loadingDiv) {
      loadingDiv.style.display = "none";
    }
  } catch (err) {
    console.error(err);

    if (loadingDiv) {
      loadingDiv.style.display = "block";
      loadingDiv.style.color = "#d93025";
      loadingDiv.innerText = "⚠️ 無法讀取 local_weather.json，請確認資料檔是否存在。";
    }

    updateLastUpdateText([]);
    displayWeather([]);
  }
}

function createCard(icao, weather) {
  const airport = airports[icao];
  const airportName = `${airport.name} (${airport.iata})`;

  const hasWeather = Boolean(weather && weather.rawOb);
  const rawMetar = hasWeather ? weather.rawOb : "";

  const weatherInfo = getWeatherInfo(rawMetar);
  const tempText = hasWeather ? parseTemperature(rawMetar) : "--";
  const windText = hasWeather ? parseWind(rawMetar) : "--";
  const visibilityText = hasWeather ? formatVisibility(weather) : "--";
  const obsTimeText = hasWeather ? formatObsTime(weather.obsTime) : "";

  const status = getStationStatus(icao, weather);

  const card = document.createElement("article");
  card.className = "card";

  const iconClass = weatherInfo.empty ? "weather-icon empty" : "weather-icon";

  card.innerHTML = `
    <div class="card-header">
      <h2 class="card-title">${escapeHtml(airportName)}</h2>
      <span class="status-badge ${escapeHtml(status.className)}">${escapeHtml(status.text)}</span>
    </div>

    <div class="weather-main">
      <div class="${iconClass}">${escapeHtml(weatherInfo.icon)}</div>
      <div class="weather-summary">
        <div class="temperature">${escapeHtml(tempText)}</div>
        <div class="condition">${escapeHtml(weatherInfo.text)}</div>
      </div>
    </div>

    <div class="info-box">
      <div class="info-item">
        <div class="info-label">🚩 風向風速</div>
        <div class="info-value">${escapeHtml(windText)}</div>
      </div>

      <div class="info-item">
        <div class="info-label">👁️ 能見度</div>
        <div class="info-value visibility-value">${escapeHtml(visibilityText)}</div>
      </div>
    </div>

    <div class="card-bottom">
      ${
        hasWeather
          ? `
            <div class="metar-box">${escapeHtml(rawMetar)}</div>
            ${
              obsTimeText
                ? `<div class="update-time">🕒 更新時間：${escapeHtml(obsTimeText)}${status.text === "非作業時段" ? "（可能為非作業時段）" : ""}</div>`
                : ""
            }
          `
          : `
            <div class="empty-note">
              ${escapeHtml(status.note)}
              <br />
              上次資料：--
            </div>
          `
      }

      <a class="radar-button" href="${officialUrl}" target="_blank" rel="noopener noreferrer">
        🔍 官方雷達與資料
        <span class="external-icon">↗</span>
      </a>
    </div>
  `;

  return card;
}

function displayWeather(data) {
  const container = document.getElementById("weather-cards");

  if (!container) {
    return;
  }

  container.innerHTML = "";

  const weatherMap = buildWeatherMap(data);

  Object.keys(airports).forEach(icao => {
    const weather = weatherMap[icao];
    const card = createCard(icao, weather);
    container.appendChild(card);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  fetchWeather();

  setInterval(fetchWeather, 5 * 60 * 1000);
});
