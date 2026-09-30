"""شغّله مرة واحدة على جهازك لاستخراج SESSION_STRING الخاص بحسابك الشخصي.

    pip install telethon
    python generate_session.py
"""
from telethon.sessions import StringSession
from telethon.sync import TelegramClient

api_id = int(input("API_ID: ").strip())
api_hash = input("API_HASH: ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as client:  # سيطلب رقم الهاتف ثم الكود
    print("\n=== انسخ السطر التالي بالكامل وضعه في GitHub Secret باسم SESSION_STRING ===\n")
    print(client.session.save())
