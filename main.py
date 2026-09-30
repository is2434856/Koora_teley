#!/usr/bin/env python3
"""نقل رسائل قناة تلجرام عامة إلى قناتك: القراءة بحسابك الشخصي (Telethon) والنشر عبر البوت."""
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl import types

import config
import filters

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
MAX_STATE_MESSAGES = 500
HASH_TTL_DAYS = 7
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096


def log(msg):
    print(msg, flush=True)


def utf16_len(s):
    return len(s.encode("utf-16-le")) // 2


# ───────────────────────── الحالة (منع التكرار + ربط الردود) ─────────────────────────

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    state.setdefault("messages", {})  # رقم الرسالة في المصدر -> رقم الرسالة في قناتك
    state.setdefault("hashes", {})    # بصمة النص -> وقت النقل
    return state


def save_state(state):
    for old in sorted(state["messages"], key=int)[:-MAX_STATE_MESSAGES]:
        del state["messages"][old]
    cutoff = time.time() - HASH_TTL_DAYS * 86400
    state["hashes"] = {h: t for h, t in state["hashes"].items() if t >= cutoff}
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, STATE_FILE)


# ───────────────────────── الفلترة ─────────────────────────

BLOCKED_ENTITIES = (
    types.MessageEntityUrl,
    types.MessageEntityTextUrl,          # رابط مخفي داخل نص
    types.MessageEntityMention,          # @username
    types.MessageEntityMentionName,
    types.InputMessageEntityMentionName,
    types.MessageEntityEmail,
    types.MessageEntityBotCommand,
)

SIMPLE_ENTITIES = (
    (types.MessageEntityBold, "bold"),
    (types.MessageEntityItalic, "italic"),
    (types.MessageEntityUnderline, "underline"),
    (types.MessageEntityStrike, "strikethrough"),
    (types.MessageEntitySpoiler, "spoiler"),
    (types.MessageEntityCode, "code"),
    (types.MessageEntityHashtag, "hashtag"),
    (types.MessageEntityCashtag, "cashtag"),
)


def reject_reason(msg):
    """سبب رفض الرسالة أو None إذا كانت مقبولة."""
    if getattr(msg, "action", None) is not None:
        return "service_message"
    if msg.fwd_from:
        return "forwarded"
    if msg.reply_markup:
        return "buttons"
    if getattr(msg, "via_bot_id", None):
        return "via_bot"
    media = msg.media
    if isinstance(media, types.MessageMediaEmpty):
        media = None
    if media is not None:
        if not isinstance(media, types.MessageMediaPhoto) or not isinstance(media.photo, types.Photo):
            # فيديو، استفتاء، ملف، معاينة رابط، ... الخ
            return "unsupported_media:" + type(media).__name__
    for e in msg.entities or []:
        if isinstance(e, BLOCKED_ENTITIES):
            return "link_or_handle"
    text = msg.raw_text or ""
    if text:
        if filters.has_link_or_handle(text):
            return "link_or_handle"
        if filters.find_blocked_word(text):
            return "blocked_word"
    return None


def to_bot_entities(entities):
    """تحويل تنسيق تلجرام (عريض، مائل ...) إلى صيغة Bot API. الإزاحات بنفس وحدة UTF-16."""
    result = []
    for e in entities or []:
        item = {"offset": e.offset, "length": e.length}
        if isinstance(e, types.MessageEntityPre):
            item["type"] = "pre"
            if getattr(e, "language", ""):
                item["language"] = e.language
        elif isinstance(e, types.MessageEntityBlockquote):
            item["type"] = "expandable_blockquote" if getattr(e, "collapsed", False) else "blockquote"
        else:
            for cls, name in SIMPLE_ENTITIES:
                if isinstance(e, cls):
                    item["type"] = name
                    break
        if "type" in item:
            result.append(item)
    return result


def evaluate_unit(unit):
    """unit = رسالة واحدة أو ألبوم. يرجع (payload, None) أو (None, سبب_الرفض)."""
    for m in unit:
        reason = reject_reason(m)
        if reason:
            return None, reason

    has_media = [m for m in unit if m.media is not None and not isinstance(m.media, types.MessageMediaEmpty)]
    captioned = [m for m in unit if (m.raw_text or "").strip()]

    if has_media:
        if len(has_media) != len(unit):
            return None, "mixed_album"
        if not captioned:
            return None, "photo_without_caption"
        cap, kind = captioned[0], "photo"
    else:
        if len(unit) != 1 or not captioned:
            return None, "empty"
        cap, kind = unit[0], "text"
        if filters.word_count(cap.raw_text) < config.MIN_TEXT_WORDS:
            return None, "short_text"

    text = cap.raw_text
    if utf16_len(text) > MESSAGE_LIMIT:
        return None, "too_long"

    reply_source = None
    header = next((m.reply_to for m in unit if m.reply_to), None)
    if header is not None and getattr(header, "reply_to_msg_id", None) and not getattr(header, "reply_to_peer_id", None):
        reply_source = header.reply_to_msg_id

    return {
        "kind": kind,
        "text": text,
        "entities": to_bot_entities(cap.entities),
        "caption_above": bool(getattr(cap, "invert_media", False)),
        "reply_source": reply_source,
    }, None


def build_units(msgs):
    """ترتيب من الأقدم للأحدث، وتجميع صور الألبوم الواحد معًا."""
    unique = {m.id: m for m in msgs if m is not None and getattr(m, "id", None)}
    units, albums = [], {}
    for m in sorted(unique.values(), key=lambda x: x.id):
        if m.grouped_id:
            if m.grouped_id not in albums:
                albums[m.grouped_id] = []
                units.append(albums[m.grouped_id])
            albums[m.grouped_id].append(m)
        else:
            units.append([m])
    return units


# ───────────────────────── النشر عبر البوت ─────────────────────────

class BotAPIError(Exception):
    pass


def bot_call(method, data=None, files=None):
    token = os.environ["BOT_TOKEN"]
    url = f"https://api.telegram.org/bot{token}/{method}"
    for attempt in range(1, 6):
        try:
            resp = requests.post(url, data=data, files=files, timeout=120)
        except requests.RequestException as exc:
            if attempt == 5:
                raise BotAPIError(str(exc).replace(token, "***"))
            time.sleep(3 * attempt)
            continue
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if payload.get("ok"):
            return payload["result"]
        if resp.status_code == 429:
            time.sleep(payload.get("parameters", {}).get("retry_after", 5) + 1)
            continue
        raise BotAPIError(f"{method}: {payload.get('description', resp.text[:200])}")
    raise BotAPIError(f"{method}: too many retries")


def _reply(reply_to):
    if not reply_to:
        return {}
    return {"reply_parameters": json.dumps({"message_id": reply_to, "allow_sending_without_reply": True})}


def _j(obj):
    return json.dumps(obj, ensure_ascii=False)


def send_text(text, entities, reply_to):
    data = {
        "chat_id": config.TARGET_CHANNEL,
        "text": text,
        "link_preview_options": _j({"is_disabled": True}),
        **_reply(reply_to),
    }
    if entities:
        data["entities"] = _j(entities)
    return bot_call("sendMessage", data)["message_id"]


def _send_photos(photos, caption, entities, caption_above, reply_to):
    """photos = [(bytes, spoiler_bool), ...]. يرجع رقم أول رسالة منشورة."""
    if len(photos) == 1:
        blob, spoiler = photos[0]
        data = {"chat_id": config.TARGET_CHANNEL, **_reply(reply_to)}
        if spoiler:
            data["has_spoiler"] = "true"
        if caption:
            data["caption"] = caption
            if entities:
                data["caption_entities"] = _j(entities)
            if caption_above:
                data["show_caption_above_media"] = "true"
        return bot_call("sendPhoto", data, files={"photo": ("photo.jpg", blob)})["message_id"]

    media, files = [], {}
    for i, (blob, spoiler) in enumerate(photos):
        item = {"type": "photo", "media": f"attach://p{i}"}
        if spoiler:
            item["has_spoiler"] = True
        if i == 0 and caption:
            item["caption"] = caption
            if entities:
                item["caption_entities"] = entities
            if caption_above:
                item["show_caption_above_media"] = True
        media.append(item)
        files[f"p{i}"] = (f"p{i}.jpg", blob)
    data = {"chat_id": config.TARGET_CHANNEL, "media": _j(media), **_reply(reply_to)}
    return bot_call("sendMediaGroup", data, files=files)[0]["message_id"]


def send_photo_unit(photos, text, entities, caption_above, reply_to):
    fits = utf16_len(text) <= CAPTION_LIMIT
    first_id = _send_photos(
        photos,
        text if fits else "",
        entities if fits else [],
        caption_above and fits,
        reply_to,
    )
    if not fits:  # الوصف أطول من حد تلجرام للصور: يُرسل نصًا مستقلًا بعد الصورة
        send_text(text, entities, first_id)
    return first_id


# ───────────────────────── التشغيل ─────────────────────────

async def run():
    env = {k: os.environ.get(k, "") for k in ("API_ID", "API_HASH", "SESSION_STRING", "BOT_TOKEN")}
    missing = [k for k, v in env.items() if not v]
    if missing:
        log("Missing secrets: " + ", ".join(missing))
        return 1

    state = load_state()
    client = TelegramClient(StringSession(env["SESSION_STRING"]), int(env["API_ID"]), env["API_HASH"])
    await client.connect()
    sent = skipped = failed = 0

    try:
        if not await client.is_user_authorized():
            log("SESSION_STRING is invalid or expired. Generate a new one with generate_session.py")
            return 1

        msgs = list(await client.get_messages(config.SOURCE_CHANNEL, limit=config.FETCH_LIMIT))
        # إن كان ألبوم مقطوعًا عند حد الفحص نكمل بقية صوره
        if msgs and msgs[-1].grouped_id:
            extra = await client.get_messages(config.SOURCE_CHANNEL, limit=10, offset_id=msgs[-1].id)
            msgs += [m for m in extra if m.grouped_id == msgs[-1].grouped_id]

        cutoff = None
        if config.MAX_AGE_HOURS:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=config.MAX_AGE_HOURS)

        units = build_units(msgs)
        log(f"Fetched {len(msgs)} messages -> {len(units)} items")

        for unit in units:
            ids = [m.id for m in unit]
            label = f"#{ids[0]}" + (f" (album x{len(ids)})" if len(ids) > 1 else "")

            if any(str(i) in state["messages"] for i in ids):
                continue  # نُقلت سابقًا
            if cutoff and unit[-1].date < cutoff:
                skipped += 1
                log(f"skip {label}: too_old")
                continue

            payload, reason = evaluate_unit(unit)
            if payload is None:
                skipped += 1
                log(f"skip {label}: {reason}")
                continue

            digest = filters.content_hash(payload["text"])
            if digest in state["hashes"]:
                skipped += 1
                log(f"skip {label}: duplicate_content")
                continue

            try:
                reply_to = None
                if payload["reply_source"]:
                    reply_to = state["messages"].get(str(payload["reply_source"]))
                if payload["kind"] == "text":
                    target_id = send_text(payload["text"], payload["entities"], reply_to)
                else:
                    photos = []
                    for m in unit:
                        blob = await client.download_media(m, file=bytes)
                        if not blob:
                            raise RuntimeError("photo download failed")
                        photos.append((blob, bool(getattr(m.media, "spoiler", False))))
                    target_id = send_photo_unit(
                        photos, payload["text"], payload["entities"], payload["caption_above"], reply_to
                    )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                log(f"FAILED {label}: {exc}")
                continue

            for i in ids:
                state["messages"][str(i)] = target_id
            state["hashes"][digest] = time.time()
            save_state(state)
            sent += 1
            log(f"sent {label} -> {target_id}" + (" (reply)" if reply_to else ""))
            time.sleep(config.SEND_DELAY_SECONDS)
    finally:
        await client.disconnect()

    log(f"Done: sent={sent} skipped={skipped} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
