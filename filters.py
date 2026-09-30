"""قواعد قبول/رفض رسائل Telegram."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from telethon.tl import types

from config import FORBIDDEN_TERMS, MIN_TEXT_WORDS


URL_PATTERN = re.compile(
    r"(?:https?://|http://|www\.|t\.me/|telegram\.me/|tg://|(?:^|\s)@)[^\s]+",
    re.IGNORECASE,
)

# MessageEntity التي تعني رابطاً/معرفاً داخل Telegram.
FORBIDDEN_ENTITY_NAMES = {
    "MessageEntityUrl",
    "MessageEntityTextUrl",
    "MessageEntityMention",
    "MessageEntityMentionName",
}


def normalize_arabic(text: str) -> str:
    """تطبيع بسيط للعربية حتى تعمل الكلمات الممنوعة مع بعض اختلافات Unicode."""
    text = unicodedata.normalize("NFKC", text or "")
    # إزالة التشكيل.
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    # توحيد أشكال الألف.
    for old, new in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا")):
        text = text.replace(old, new)
    return text.casefold()


def contains_forbidden_term(text: str) -> str | None:
    normalized = normalize_arabic(text)
    for term in FORBIDDEN_TERMS:
        normalized_term = normalize_arabic(term)
        # نبحث عن كلمة/عبارة مستقلة حتى لا تمنع كلمة أطول بالمصادفة.
        pattern = r"(?<!\w)" + re.escape(normalized_term).replace(r"\ ", r"\s+") + r"(?!\w)"
        if re.search(pattern, normalized, flags=re.UNICODE):
            return term
    return None


def contains_link_or_username(message: Any) -> bool:
    raw_text = message.raw_text or ""

    if URL_PATTERN.search(raw_text):
        return True

    for entity in message.entities or []:
        if type(entity).__name__ in FORBIDDEN_ENTITY_NAMES:
            return True
        # دفاع إضافي ضد كيانات روابط جديدة قد تظهر في Telethon لاحقاً.
        name = type(entity).__name__.lower()
        if "url" in name or name.endswith("mentionname"):
            return True

    # بعض الروابط/المعرفات قد لا تظهر كـ entity إذا كانت الرسالة غير مكتملة التحليل.
    lowered = raw_text.casefold()
    suspicious_fragments = ("https://", "http://", "www.", "t.me/", "telegram.me/", "tg://")
    return any(fragment in lowered for fragment in suspicious_fragments)


def has_buttons_or_markup(message: Any) -> bool:
    try:
        return bool(message.buttons)
    except Exception:
        return message.reply_markup is not None


def is_poll(message: Any) -> bool:
    if getattr(message, "poll", None) is not None:
        return True
    media = getattr(message, "media", None)
    return isinstance(media, types.MessageMediaPoll)


def is_todo_or_list_media(message: Any) -> bool:
    media = getattr(message, "media", None)
    if media is None:
        return False
    media_name = type(media).__name__.lower()
    return "todo" in media_name or "checklist" in media_name


def is_forwarded(message: Any) -> bool:
    return bool(getattr(message, "forward", None) or getattr(message, "fwd_from", None))


def is_sponsored_or_ad(message: Any) -> bool:
    """فحص دفاعي للأنواع/الحقول التي قد تستخدمها Telegram للإعلانات الممولة."""
    class_name = type(message).__name__.lower()
    if "sponsored" in class_name or class_name.startswith("ad"):
        return True

    for attr in ("sponsored", "is_sponsored", "sponsor", "ad", "is_ad"):
        try:
            if getattr(message, attr, None):
                return True
        except Exception:
            pass
    return False


def is_service_message(message: Any) -> bool:
    if getattr(message, "action", None) is not None:
        # منشورات الخدمة لا نريد نقلها كرسائل عادية.
        return True
    return False


def count_words(text: str) -> int:
    # تقسيم عملي للعربية واللغات الأخرى؛ علامات الترقيم لا تضيف كلمات.
    return len(re.findall(r"[^\W_]+(?:['’\-][^\W_]+)*", text or "", flags=re.UNICODE))


@dataclass(frozen=True)
class FilterResult:
    allowed: bool
    reason: str


def evaluate(message: Any) -> FilterResult:
    text = message.raw_text or ""

    if not text.strip() and not message.photo:
        return FilterResult(False, "بدون نص أو صورة مناسبة")

    if is_service_message(message):
        return FilterResult(False, "رسالة خدمة")

    if is_sponsored_or_ad(message):
        return FilterResult(False, "إعلان/رسالة ممولة")

    if is_forwarded(message):
        return FilterResult(False, "رسالة محولة")

    if has_buttons_or_markup(message):
        return FilterResult(False, "تحتوي على أزرار أو Reply Markup")

    if is_poll(message):
        return FilterResult(False, "استفتاء")

    if is_todo_or_list_media(message):
        return FilterResult(False, "قائمة/Checklist")

    if contains_link_or_username(message):
        return FilterResult(False, "رابط أو معرف Telegram")

    banned = contains_forbidden_term(text)
    if banned:
        return FilterResult(False, f"كلمة ممنوعة: {banned}")

    # الصور: يجب أن تحتوي على وصف، من دون اشتراط 8 كلمات.
    if message.photo is not None:
        if not text.strip():
            return FilterResult(False, "صورة بدون وصف")
        return FilterResult(True, "صورة مع وصف")

    # لا ننقل الفيديو أو أي وسائط أخرى.
    if getattr(message, "media", None) is not None:
        return FilterResult(False, "وسائط غير مسموح بها")

    if count_words(text) < MIN_TEXT_WORDS:
        return FilterResult(False, f"أقل من {MIN_TEXT_WORDS} كلمات")

    return FilterResult(True, "رسالة نصية مؤهلة")
