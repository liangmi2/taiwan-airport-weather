def fetch_from_aoaws_api():
    """
    直接打 AOAWS 官方 XHR API。
    不先 GET /Report，避免 GitHub Actions 卡在 /Report timeout。
    """
    log("正在抓取 AOAWS 官方 METAR/SPECI API...")
    log("URL:", AOAWS_API_URL)

    result = {}

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://aoaws.anws.gov.tw",
        "Referer": AOAWS_REFERER,
        "X-Requested-With": "XMLHttpRequest"
    }

    for attempt in range(1, 4):
        try:
            log(f"AOAWS API 第 {attempt} 次嘗試...")

            response = requests.post(
                AOAWS_API_URL,
                headers=headers,
                data=AOAWS_PAYLOAD,
                timeout=(30, 30)
            )

            log("AOAWS HTTP 狀態：", response.status_code)
            log("AOAWS Content-Type：", response.headers.get("content-type", ""))
            log("AOAWS response 長度：", len(response.text))

            for check_icao in ["RCBS", "RCYU", "RCNN"]:
                if check_icao in response.text:
                    log(f"AOAWS response 內有找到 {check_icao}")
                else:
                    log(f"AOAWS response 內沒有找到 {check_icao}")

            response.raise_for_status()

            try:
                payload = response.json()
                report_items = collect_report_items(payload)

                log("AOAWS JSON 解析報文筆數：", len(report_items))

                for item in report_items:
                    icao = item.get("station")
                    raw_report = item.get("content", "")

                    if icao not in AIRPORTS:
                        continue

                    raw_report = normalize_raw_report(raw_report)

                    if not is_valid_report(icao, raw_report):
                        log(f"AOAWS {icao} 報文格式不完整，略過：{raw_report}")
                        continue

                    weather_item = make_weather_item(icao, raw_report)

                    if icao not in result:
                        result[icao] = weather_item
                    else:
                        old_time = int(result[icao].get("obsTime", 0))
                        new_time = int(weather_item.get("obsTime", 0))

                        if new_time >= old_time:
                            result[icao] = weather_item

            except Exception as e:
                log("AOAWS JSON 解析失敗：", e)

            text_result = extract_reports_from_response_text(response.text)

            for icao, item in text_result.items():
                if icao not in result:
                    log(f"AOAWS text 備援抓到 {icao}: {item['rawOb']}")
                    result[icao] = item
                else:
                    old_time = int(result[icao].get("obsTime", 0))
                    new_time = int(item.get("obsTime", 0))

                    if new_time >= old_time:
                        result[icao] = item

            log("AOAWS 整理後機場數：", len(result))

            for icao in AIRPORTS:
                if icao in result:
                    log(f"AOAWS 最新 {icao}: {result[icao]['rawOb']}")
                else:
                    log(f"AOAWS 沒有回傳 {icao}")

            return result

        except Exception as e:
            log(f"AOAWS API 第 {attempt} 次失敗：", e)

            if attempt < 3:
                time.sleep(5)

    log("AOAWS API 三次都失敗，改用 AviationWeather 備援")
    return result
