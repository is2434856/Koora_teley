"""دوال الفلترة النصية (لا تعتمد على تلجرام)."""
import hashlib
import re
import unicodedata

import config

# تشكيل + تطويل + رموز اتجاه/أحرف غير مرئية
_STRIP = re.compile(
    "[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640"
    "\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]"
)


def normalize(text: str) -> str:
    """توحيد الحروف العربية لمطابقة أدق (أ/إ/آ→ا، ى→ي، ة→ه، حذف التشكيل)."""
    text = unicodedata.normalize("NFKC", text)
    text = _STRIP.sub("", text)
    text = re.sub("[إأآٱ]", "ا", text)
    return text.replace("ى", "ي").replace("ة", "ه").lower()


_PLAIN_PREFIXES = ("", "و", "ف", "ب", "ل", "ك", "وب", "ول", "وك", "فب", "فل", "فك")
_AL_PREFIXES = ("ال", "وال", "فال", "بال", "كال")
_LAM_AL_PREFIXES = ("لل", "ولل", "فلل")


def _variants(word: str) -> set:
    w = normalize(word).strip()
    if not w:
        return set()
    forms = {p + w for p in _PLAIN_PREFIXES}
    if w.startswith("ال"):
        forms |= {p + w[2:] for p in _LAM_AL_PREFIXES}
    else:
        forms |= {p + w for p in _AL_PREFIXES + _LAM_AL_PREFIXES}
    return forms


_BLOCKED = set().union(*(_variants(w) for w in config.BLOCKED_WORDS))
_BLOCKED_RAW = {normalize(w).strip() for w in config.BLOCKED_WORDS if w.strip()}


def find_blocked_word(text: str):
    """يرجع الكلمة الممنوعة الموجودة في النص أو None."""
    n = normalize(text)
    if config.BLOCK_MATCH == "contains":
        return next((w for w in _BLOCKED_RAW if w in n), None)
    tokens = set(re.findall(r"\w+", n))
    hit = tokens & _BLOCKED
    return next(iter(hit), None)


_LINK_RE = re.compile(
    r"(https?://|www\.|tg://"
    r"|(?<!\w)(?:t|telegram)\.(?:me|dog)\b"
    r"|(?<![\w.@-])[a-z0-9][a-z0-9-]*\.(?:com|net|org|info|io|me|tv|co|app|xyz|live|link|site|online|shop|cc|ly|sa|ae|eg|iq|kw)\b)",
    re.I,
)
_HANDLE_RE = re.compile(r"(?<![\w@])@[A-Za-z][A-Za-z0-9_]{2,}")


def has_link_or_handle(text: str) -> bool:
    """روابط ظاهرة في النص أو معرفات @username (حتى لو لم تكن كيانات تلجرام)."""
    t = unicodedata.normalize("NFKC", text)
    return bool(_LINK_RE.search(t) or _HANDLE_RE.search(t))


def word_count(text: str) -> int:
    return len([t for t in text.split() if re.search(r"\w", t)])


def content_hash(text: str) -> str:
    """بصمة للنص لمنع تكرار نفس المحتوى (تتجاهل التنسيق والترقيم)."""
    tokens = re.findall(r"\w+", normalize(text))
    return hashlib.sha1(" ".join(tokens).encode("utf-8")).hexdigest()
