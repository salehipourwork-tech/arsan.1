"""
RSP — ingestion/coingecko_client.py

مسئولیت: فقط و فقط گرفتن داده‌ی خام از CoinGecko. هیچ تحلیلی اینجا انجام نمی‌شود.

صداقت درباره‌ی داده (مهم):
CoinGecko رایگان OHLC صرافی واقعی نمی‌دهد مگر از اندپوینت /ohlc که خودش هم
با گرانولاریتی محدود (و برای بازه‌های کوتاه با تاخیر) کار می‌کند. به‌جای قالب
کردن کندل‌های جعلی، از سری قیمت (price ticks) با دو رزولوشن native استفاده
می‌کنیم:

  - days=1   -> رزولوشن ~5 دقیقه‌ای (برای ساخت 15M و 1H)
  - days=90  -> رزولوشن ~ساعتی (برای ساخت 4H و 1D)

سپس در preprocessing این سری‌ها resample می‌شوند تا کندل OHLC بسازند
(open=first, high=max, low=min, close=last, volume=sum). این OHLC واقعی
صرافی نیست؛ یک بازسازی از سری قیمت CoinGecko است — این محدودیت در
data_universe.py به‌صورت صریح ثبت می‌شود (DATA QUALITY: RECONSTRUCTED).

این فایل کاملاً از analyzer/fetch_data.py آرسان اصلی مستقل است (کپی نشده،
وابسته هم نیست) تا هیچ تغییری در آرسان اصلی لازم نباشد.
"""

import time
import requests

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 5


class DataFetchError(Exception):
    pass


def _get_with_retry(url, params=None):
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(BASE_BACKOFF_SECONDS)
            continue
        if response.status_code == 200:
            return response.json()
        if response.status_code == 429:
            wait_time = BASE_BACKOFF_SECONDS * attempt
            print(f"[RSP.ingestion] Rate limited (429). Waiting {wait_time}s "
                  f"(attempt {attempt}/{MAX_RETRIES})...")
            time.sleep(wait_time)
            continue
        # سایر خطاها -> بلافاصله ثبت و شکست، بدون تلاش بی‌پایان
        last_error = RuntimeError(f"HTTP {response.status_code} for {url}: {response.text[:200]}")
        break
    raise DataFetchError(str(last_error) if last_error else f"Failed to fetch {url}")


def fetch_raw_price_series(coin_id: str, days: int):
    """
    خروجی خام از CoinGecko: {"prices": [[ts_ms, price], ...], "volumes": [[ts_ms, vol], ...]}
    هیچ پردازشی روی داده انجام نمی‌شود - این کار preprocessing است.
    """
    url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart"
    params = {"vs_currency": "usd", "days": days}
    try:
        data = _get_with_retry(url, params)
    except DataFetchError as exc:
        return {"prices": [], "volumes": [], "error": str(exc)}
    return {
        "prices": data.get("prices", []),
        "volumes": data.get("total_volumes", []),
        "error": None,
    }


def fetch_fine_and_coarse(coin_id: str, coarse_days: int = 90):
    """
    برای ساخت هر ۴ تایم‌فریم لازم است، دو تماس API انجام می‌شود:
      fine   (days=1)          -> منبع برای 15M و 1H (محدودیت CoinGecko رایگان:
                                    فقط ۱ روز آخر با رزولوشن ۵ دقیقه‌ای در دسترس
                                    است؛ این fallback نمی‌تواند لوک‌بک طولانی‌تر
                                    برای این دو تایم‌فریم بدهد - چون آخرین خط دفاع
                                    است و منابع صرافی واقعی همیشه اولویت دارند،
                                    این محدودیت در عمل به‌ندرت به کاربر می‌رسد)
      coarse (days=coarse_days) -> منبع برای 4H و 1D
    """
    fine = fetch_raw_price_series(coin_id, days=1)
    coarse = fetch_raw_price_series(coin_id, days=coarse_days)
    return {"fine": fine, "coarse": coarse}
