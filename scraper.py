def fetch_from_aviationweather():
    """
    第一來源：AviationWeather API。
    只保留每個機場最新一筆，避免 hours=24 回傳太多筆造成 Actions 看起來卡住。
    """
    ids = ",".join(AIRPORTS)

    url = (
        "https://aviationweather.gov/api/data/metar"
        f"?ids={ids}&format=json&taf=false&hours=6"
    )

    headers = {
        "User-Agent": "taiwan-airport-weather/1.0"
    }

    print("正在抓取 AviationWeather METAR API...")
    print("URL:", url)

    result = {}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()

        print("AviationWeather API 回傳筆數：", len(data))

        for item in data:
            icao = item.get("icaoId")

            if icao not in AIRPORTS:
                continue

            raw_report = item.get("rawOb", "").strip()

            if not raw_report:
                continue

            raw_report = normalize_raw_report(raw_report)
            obs_time = parse_metar_obs_time(raw_report)

            visib = item.get("visib")

            if visib is None or visib == "":
                visibility = parse_visibility_from_raw(raw_report)
            else:
                visibility = str(visib).replace("+", "")

            new_item = {
                "icaoId": icao,
                "obsTime": obs_time,
                "rawOb": raw_report,
                "visib": visibility
            }

            # 同一機場只保留最新一筆
            if icao not in result:
                result[icao] = new_item
            else:
                old_time = int(result[icao].get("obsTime", 0))
                if obs_time > old_time:
                    result[icao] = new_item

        print("AviationWeather 整理後機場數：", len(result))

        for icao in AIRPORTS:
            if icao in result:
                print(f"AviationWeather 最新 {icao}: {result[icao]['rawOb']}")
            else:
                print(f"AviationWeather 沒有回傳 {icao}")

    except Exception as e:
        print("AviationWeather 抓取失敗：", e)

    return result
