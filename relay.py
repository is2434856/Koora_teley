"""جلب الرسائل، تطبيق الفلاتر، والنشر بواسطة البوت."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from io import BytesIO
from datetime import datetime, timedelta, timezone
from typing import Any

from telethon import TelegramClient

from config import LOOKBACK_MINUTES, MAX_MESSAGES, SOURCE_CHANNEL, TARGET_CHANNEL
from filters import evaluate
from state_manager import StateManager

logger = logging.getLogger(__name__)


def message_fingerprint(message: Any) -> str:
    text = (message.raw_text or "").strip()
    parts = [text]

    if message.photo is not None:
        # photo.id ثابت لنفس صورة Telegram غالباً، مع إبقاء النص كاملاً لتقليل التصادم.
        parts.append(f"photo:{message.photo.id}")
    elif getattr(message, "media", None) is not None:
        parts.append(type(message.media).__name__)

    raw = "\x1f".join(parts).encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()


def formatting_entities(message: Any) -> list[Any] | None:
    # لا نعدل النص؛ نعيد كيانات Telegram نفسها حتى يبقى التنسيق.
    if not message.entities:
        return None
    return list(message.entities)


def get_reply_source_id(message: Any) -> int | None:
    reply_id = getattr(message, "reply_to_msg_id", None)
    if not reply_id:
        return None

    # إذا كان الرد موجهاً إلى دردشة مرتبطة أخرى فلا يمكننا استخدام message_id
    # من قناة المصدر كـ reply داخل قناة الهدف.
    reply_to_chat = getattr(message, "reply_to_chat", None)
    if reply_to_chat is not None:
        return None

    return int(reply_id)


async def send_allowed_message(
    user_client: TelegramClient,
    bot_client: TelegramClient,
    target_entity: Any,
    message: Any,
    reply_to_target_id: int | None,
) -> Any:
    entities = formatting_entities(message)

    if message.photo is not None:
        # الحساب الشخصي يقرأ من القناة المصدر، لذلك ننزّل الصورة أولاً ثم
        # يعيد البوت رفعها من جلسته هو. هذا يتجنب الاعتماد على صلاحية كائن
        # الوسائط بين جلستين مختلفتين.
        buffer = BytesIO()

        downloaded = await user_client.download_media(
            message,
            file=buffer,
        )

        if downloaded is None:
            raise RuntimeError("Failed to download source photo")

        buffer = downloaded if isinstance(downloaded, BytesIO) else buffer
        buffer.seek(0)
        buffer.name = f"telegram_photo_{message.id}.jpg"

        return await bot_client.send_file(
            target_entity,
            buffer,
            caption=message.raw_text or "",
            formatting_entities=entities,
            link_preview=False,
            reply_to=reply_to_target_id,
            silent=False,
            force_document=False,
        )

    return await bot_client.send_message(
        target_entity,
        message.raw_text or "",
        formatting_entities=entities,
        link_preview=False,
        reply_to=reply_to_target_id,
        silent=False,
    )


async def run_once(
    user_client: TelegramClient,
    bot_client: TelegramClient,
    state: StateManager,
) -> dict[str, int]:

    source_entity = await user_client.get_entity(SOURCE_CHANNEL)
    target_entity = await bot_client.get_entity(TARGET_CHANNEL)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=LOOKBACK_MINUTES)

    # get_messages يعيد الأحدث أولاً عادةً.
    # نرتب لاحقاً من الأقدم إلى الأحدث حتى يتم النشر بالترتيب الصحيح.
    messages = await user_client.get_messages(
        source_entity,
        limit=MAX_MESSAGES,
    )

    candidates = [
        m
        for m in messages
        if m and m.date and m.date >= cutoff
    ]

    candidates.sort(key=lambda m: m.date)

    stats: dict[str, int] = {
        "checked": len(candidates),
        "sent": 0,
        "skipped": 0,
        "duplicates": 0,
        "errors": 0,
    }

    for message in candidates:

        # منع تكرار نفس رسالة المصدر.
        if state.has_source_message(message.id):
            stats["duplicates"] += 1
            continue

        # منع تكرار نفس المحتوى حتى لو كان رقم الرسالة مختلفاً.
        fingerprint = message_fingerprint(message)

        if state.has_fingerprint(fingerprint):
            state.remember(
                message.id,
                0,
                fingerprint,
            )
            state.save()

            stats["duplicates"] += 1
            continue

        # تطبيق جميع شروط الفلترة.
        result = evaluate(message)

        if not result.allowed:
            stats["skipped"] += 1

            logger.info(
                "SKIP source=%s reason=%s",
                message.id,
                result.reason,
            )

            continue

        # معرفة الرسالة الأصلية التي يرد عليها الخبر.
        reply_source_id = get_reply_source_id(message)

        reply_target_id = (
            state.get_target_message_id(reply_source_id)
            if reply_source_id
            else None
        )

        # 0 يستخدم داخل الحالة للفهرسة فقط،
        # ولا يمكن استخدامه كـ reply.
        if reply_target_id == 0:
            reply_target_id = None

        try:
            # نشر الرسالة بواسطة البوت.
            sent = await send_allowed_message(
                user_client,
                bot_client,
                target_entity,
                message,
                reply_to_target_id=reply_target_id,
            )

            # حفظ الرسالة مباشرة بعد نجاح النشر.
            state.remember(
                message.id,
                sent.id,
                fingerprint,
            )
            state.save()

            stats["sent"] += 1

            logger.info(
                "SENT source=%s target=%s reply_to=%s",
                message.id,
                sent.id,
                reply_target_id,
            )

            # ========================================================
            # فاصل ثانيتين بين نشر كل رسالة والتي تليها.
            # لا يتم الانتظار عند الرسائل المرفوضة أو المكررة.
            # ========================================================
            await asyncio.sleep(2)

        except Exception:
            stats["errors"] += 1

            logger.exception(
                "SEND ERROR source=%s",
                message.id,
            )

    state.save()

    return stats
