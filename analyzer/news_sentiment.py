"""
آرسان - تحلیل احساسات اخبار کریپتو (نسخه‌ی یکپارچه با ورک‌فلوی اصلی)

برخلاف نسخه‌ی اول (که یه سرویس Flask جدا و همیشه-روشن بود)، این نسخه یه اسکریپت
یک‌باره‌ست: هر بار که main.py توسط ورک‌فلوی گیت‌هاب اکشن اجرا می‌شه (هر ۳۰ دقیقه)،
این ماژول هم یک‌بار اخبار رو می‌گیره، تحلیل می‌کنه، و نتیجه رو برمی‌گردونه — دقیقاً
هماهنگ با همون زمان‌بندی، بدون نیاز به سرور جدا، کش، یا API.

چرا این بهتر از سرور جداست:
- ران‌رهای گیت‌هاب اکشن حدود ۷ گیگابایت RAM دارن (نه ۵۱۲ مگابایت مثل Render رایگان)
  پس FinBERT بدون نگرانی از کمبود حافظه اجرا می‌شه.
- نیازی به دیپلوی/نگهداری یه سرور جدا نیست.
- برای ریپازیتوری‌های عمومی (public) گیت‌هاب، دقیقه‌های اکشن رایگان و نامحدوده.

⚠️ نکته: چون هر اجرای ورک‌فلو یه container تازه‌ست (نه یه سرور همیشه-روشن)، مدل
باید هر بار از Hugging Face دانلود بشه — مگراینکه کش گیت‌هاب اکشن (actions/cache)
فعال باشه (که تو راهنمای نصب توضیح داده شده و به‌شدت توصیه می‌شه، وگرنه هر اجرا
چند دقیقه بیشتر طول می‌کشه).
"""

import re
from datetime import datetime, timedelta, timezone

import feedparser

# ---------------------------------------------------------------------------
# تنظیمات
# ---------------------------------------------------------------------------

# پلن A: FinBERT (دقیق‌تر، مخصوص متن مالی) — پیش‌فرض، چون ران‌رهای گیت‌هاب
# اکشن حافظه‌ی کافی دارن و این دیگه مثل سرور رایگان محدودیت ۵۱۲ مگابایتی نداره.
# پلن B: VADER (سبک، بدون دانلود مدل) — فقط اگه به هر دلیلی خواستی سرعت اجرا
# رو بیشتر کنی یا دانلود مدل تو اکشن مشکل ایجاد کرد، این رو True کن.
USE_LIGHTWEIGHT_FALLBACK = False

TRANSFORMER_MODEL_NAME = "ProsusAI/finbert"

RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://bitcoinmagazine.com/feed",
]

# کلیدواژه‌ها برای هر کوین — دقیقاً با شناسه‌ی CoinGecko (DEFAULT_COINS در fetch_data.py) یکیه
COIN_KEYWORDS = {
    "bitcoin": [r"\bbitcoin\b", r"\bbtc\b"],
    "ethereum": [r"\bethereum\b", r"\beth\b"],
    "binancecoin": [r"\bbnb\b", r"\bbinance coin\b"],
    "ripple": [r"\bripple\b", r"\bxrp\b"],
    "solana": [r"\bsolana\b", r"\bsol\b"],
    "dogecoin": [r"\bdogecoin\b", r"\bdoge\b"],
    "cardano": [r"\bcardano\b", r"\bada\b"],
    "tron": [r"\btron\b", r"\btrx\b"],
}

NEWS_WINDOW_HOURS = 24
MAX_ARTICLES_PER_COIN = 25

# ---------------------------------------------------------------------------
# بارگذاری مدل (فقط یک‌بار، وقتی main.py این ماژول رو import می‌کنه)
# ---------------------------------------------------------------------------

if USE_LIGHTWEIGHT_FALLBACK:
    print("[news_sentiment] در حال بارگذاری VADER (سبک) ...")
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    _vader = SentimentIntensityAnalyzer()

    def _analyze_text(text: str) -> float:
        return _vader.polarity_scores(text)["compound"]

else:
    print(f"[news_sentiment] در حال بارگذاری مدل {TRANSFORMER_MODEL_NAME} ...")
    from transformers import pipeline

    _pipeline = pipeline("sentiment-analysis", model=TRANSFORMER_MODEL_NAME, tokenizer=TRANSFORMER_MODEL_NAME)
    print("[news_sentiment] مدل بارگذاری شد.")

    def _analyze_text(text: str) -> float:
        result = _pipeline(text[:512], truncation=True)[0]
        label = result["label"].lower()
        confidence = result["score"]
        if "positive" in label or label == "pos":
            return confidence
        if "negative" in label or label == "neg":
            return -confidence
        return 0.0


# ---------------------------------------------------------------------------
# دریافت و فیلتر اخبار
# ---------------------------------------------------------------------------

def fetch_all_entries():
    entries = []
    for feed_url in RSS_FEEDS:
        try:
            parsed = feedparser.parse(feed_url)
            entries.extend(parsed.entries)
        except Exception as exc:
            print(f"[news_sentiment] خطا در خوندن فید {feed_url}: {exc}")
    return entries


def _entry_time(entry):
    for field in ("published_parsed", "updated_parsed"):
        t = getattr(entry, field, None)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def _matches_coin(text, patterns):
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _compute_sentiment_for_coin(coin_id, all_entries):
    patterns = COIN_KEYWORDS.get(coin_id)
    if not patterns:
        return {"coin": coin_id, "score": 0.0, "articles_analyzed": 0,
                "note": "این کوین تو COIN_KEYWORDS تعریف نشده.", "sample_headlines": []}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=NEWS_WINDOW_HOURS)
    matched = []
    for entry in all_entries:
        title = getattr(entry, "title", "") or ""
        summary = getattr(entry, "summary", "") or ""
        full_text = f"{title} {summary}"
        if not _matches_coin(full_text, patterns):
            continue
        entry_time = _entry_time(entry)
        if entry_time and entry_time < cutoff:
            continue
        matched.append((title, summary))
        if len(matched) >= MAX_ARTICLES_PER_COIN:
            break

    if not matched:
        return {
            "coin": coin_id, "score": 0.0, "articles_analyzed": 0,
            "note": "خبری در ۲۴ ساعت اخیر پیدا نشد؛ امتیاز خنثی (۰) در نظر گرفته شد.",
            "sample_headlines": [],
        }

    scores, headlines = [], []
    for title, summary in matched:
        try:
            scores.append(_analyze_text(f"{title}. {summary}"))
        except Exception as exc:
            print(f"[news_sentiment] خطا در تحلیل خبر «{title}»: {exc}")
        headlines.append(title)

    avg_score = round(sum(scores) / len(scores), 3) if scores else 0.0
    return {
        "coin": coin_id, "score": avg_score, "articles_analyzed": len(scores),
        "note": None, "sample_headlines": headlines[:5],
    }


def compute_all_sentiments(coin_ids):
    """
    coin_ids: لیست شناسه‌های CoinGecko (همون DEFAULT_COINS در main.py)
    خروجی: {coin_id: {"score": float, "articles_analyzed": int, ...}, ...}
    """
    all_entries = fetch_all_entries()  # یک‌بار همه‌ی فیدها گرفته می‌شه، برای همه‌ی کوین‌ها استفاده می‌شه
    return {coin_id: _compute_sentiment_for_coin(coin_id, all_entries) for coin_id in coin_ids}
