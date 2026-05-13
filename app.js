const airports = {
    'RCTP': '桃園國際機場 (TPE)',
    'RCSS': '台北松山機場 (TSA)',
    'RCKH': '高雄小港機場 (KHH)',
    'RCMQ': '台中清泉崗機場 (RMQ)',
    'RCBS': '金門尚義機場 (KNH)',
    'RCNN': '台南機場 (TNN)',
    'RCYU': '花蓮機場 (HUN)',
    'RCQC': '馬公機場 (MZG)'
};

// 翻譯風向角度
function getWindDirection(degrees) {
    if (degrees === 'VRB') return '風向不定';
    const deg = parseInt(degrees, 10);
    const dirs = ['北風', '東北風', '東風', '東南風', '南風', '西南風', '西風', '西北風', '北風'];
    return dirs[Math.round((deg % 360) / 45)];
}

// 蒲福氏風級換算 (依據節數 Knots 轉換)
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

// 翻譯天氣狀態與雲量為 Emoji 圖示
function getWeatherInfo(metar) {
    if (metar.includes('TS')) return { icon: '⛈️', text: '雷陣雨' };
    if (metar.includes('RA') || metar.includes('DZ') || metar.includes('SH')) return { icon: '🌧️', text: '下雨' };
    if (metar.includes('FG') || metar.includes('BR') || metar.includes('HZ')) return { icon: '🌫️', text: '霧霾' };
    if (metar.includes('OVC') || metar.includes('BKN')) return { icon: '☁️', text: '陰天' };
    if (metar.includes('SCT') || metar.includes('FEW')) return { icon: '⛅', text: '多雲' };
    if (metar.includes('CAVOK') || metar.includes('SKC') || metar.includes('CLR')) return { icon: '☀️', text: '晴朗' };
    return { icon: '🌤️', text: '良好' }; 
}

async function fetchWeather() {
    const loadingDiv = document.getElementById('loading');
    const container = document.getElementById('weather-cards');
    container.innerHTML = ''; 
    loadingDiv.style.display = 'block';
    loadingDiv.style.color = '#7f8c8d'; 
    loadingDiv.innerText = '正在讀取氣象資料...';

    const localUrl = `./local_weather.json?t=${new Date().getTime()}`;

    try {
        const res = await fetch(localUrl);
        if (!res.ok) throw new Error('找不到檔案');
        const data = await res.json();

        if (!Array.isArray(data) || data.length === 0) {
            loadingDiv.innerText = '⚠️ 本地資料庫為空，請確認 Python 腳本是否正常執行。';
            displayWeather([], true);
        } else {
            displayWeather(data, false); 
        }
    } catch (err) {
        loadingDiv.innerText = '⚠️ 無法讀取本地氣象資料。請確認 local_weather.json 檔案是否存在。';
        displayWeather([], true); 
    }
}

function displayWeather(data, keepLoadingDivVisible = false) {
    const container = document.getElementById('weather-cards');
    
    if (!keepLoadingDivVisible) {
        document.getElementById('loading').style.display = 'none';
    }

    const weatherMap = {};
    if (Array.isArray(data)) {
        data.forEach(item => {
            if (!weatherMap[item.icaoId] || item.obsTime > weatherMap[item.icaoId].obsTime) {
                weatherMap[item.icaoId] = item;
            }
        });
    }

    Object.keys(airports).forEach(icao => {
        const weather = weatherMap[icao];
        const card = document.createElement('div');
        card.className = 'card';

        let visibilityText = '--';
        let rawMetar = '暫無資料';
        let windText = '--';
        let tempText = '--';
        let weatherInfo = { icon: '❓', text: '未知' };

        if (weather && weather.rawOb) {
            rawMetar = weather.rawOb;
            weatherInfo = getWeatherInfo(rawMetar);
            
            // 解析能見度
            if (weather.visib) {
                const miles = parseFloat(weather.visib);
                if (!isNaN(miles)) {
                    visibilityText = `${Math.round(miles * 1609.34)} 公尺`;
                } else if (weather.visib.includes('+')) {
                    const val = parseFloat(weather.visib.replace('+', ''));
                    visibilityText = `大於 ${Math.round(val * 1609.34)} 公尺`;
                }
            }

            // 解析風向、風速與陣風，並加入級數換算
            const windMatch = rawMetar.match(/\b(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?KT\b/);
            if (windMatch) {
                const dirName = getWindDirection(windMatch[1]);
                const speedKt = parseInt(windMatch[2], 10);
                const speedKmh = Math.round(speedKt * 1.852);
                const beaufortLvl = getBeaufortScale(speedKt);
                
                let gustText = '';
                if (windMatch[3]) {
                    const gustKt = parseInt(windMatch[3], 10);
                    const gustKmh = Math.round(gustKt * 1.852);
                    const gustBeaufortLvl = getBeaufortScale(gustKt);
                    gustText = ` (陣風 ${gustBeaufortLvl} 級)`;
                }
                // 將顯示文字組合起來
                windText = `${dirName} ${beaufortLvl} 級風${gustText}`;
            }

            // 解析溫度
            const tempMatch = rawMetar.match(/\b(M?\d{2})\/(M?\d{2})?\b/);
            if (tempMatch) {
                let tempStr = tempMatch[1].replace('M', '-');
                tempText = `${parseInt(tempStr, 10)}°C`;
            }
        }

        const aoawsUrl = `https://aoaws.anws.gov.tw/`;

        // 卡片視覺排版
        card.innerHTML = `
            <div class="airport-name" style="text-align: center; font-size: 1.1em; color: #7f8c8d;">${airports[icao]}</div>
            
            <div style="display: flex; justify-content: center; align-items: center; gap: 15px; margin: 20px 0;">
                <div style="font-size: 4em; line-height: 1;">${weatherInfo.icon}</div>
                <div style="display: flex; flex-direction: column;">
                    <div style="font-size: 2.5em; font-weight: bold; color: #2c3e50; line-height: 1;">${tempText}</div>
                    <div style="font-size: 1.1em; color: #34495e; font-weight: bold; margin-top: 5px;">${weatherInfo.text}</div>
                </div>
            </div>

            <div style="background: #f1f2f6; border-radius: 8px; padding: 12px; margin-bottom: 15px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 8px; border-bottom: 1px dashed #ced6e0; padding-bottom: 8px;">
                    <span style="color: #747d8c;">🌬️ 風向風速</span>
                    <span style="font-weight: bold; color: #2f3542;">${windText}</span>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #747d8c;">👁️ 能見度</span>
                    <span style="font-weight: bold; color: #e74c3c;">${visibilityText}</span>
                </div>
            </div>

            <div class="raw-metar" style="font-size: 0.75em;">${rawMetar}</div>
            <a href="${aoawsUrl}" target="_blank" style="display: block; text-align: center; margin-top: 15px; padding: 10px; background-color: #2980b9; color: white; text-decoration: none; border-radius: 5px; font-weight: bold;">
                🔍 官方雷達與資料
            </a>
        `;
        container.appendChild(card);
    });
}

fetchWeather();
setInterval(fetchWeather, 5 * 60 * 1000);
