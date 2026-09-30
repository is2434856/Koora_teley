"""إعدادات المشروع. القيم الحساسة تُقرأ من متغيرات البيئة فقط."""

import os

# التشغيل
LOOKBACK_MINUTES = int(os.getenv("LOOKBACK_MINUTES", "60"))
MAX_MESSAGES = int(os.getenv("MAX_MESSAGES", "30"))
MIN_TEXT_WORDS = int(os.getenv("MIN_TEXT_WORDS", "8"))
STATE_MAX_ENTRIES = int(os.getenv("STATE_MAX_ENTRIES", "5000"))

# Telegram
API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION_STRING = os.environ["TELEGRAM_SESSION_STRING"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
SOURCE_CHANNEL = os.environ["SOURCE_CHANNEL"]
TARGET_CHANNEL = os.environ["TARGET_CHANNEL"]

# الكلمات/العبارات التي تمنع نقل الرسالة بالكامل.
FORBIDDEN_TERMS = [
    "فعالية",
    "التوقعات",
    "الفائز",
    "تابع",
    "شارك",
    "تفاعلا",
    "تفاعلآ",
    "الاعضاء",
    "مسابقة",
    "مسابقه",
    "الحسين",
    "حسين",
    "العباس",
    "كربلاء",
    "قناتنا",
    "قنواتنا",
    "قناة المصدر",
]

STATE_FILE = os.path.join(os.path.dirname(__file__), "data", "state.json")
