"""إنشاء String Session لحساب Telegram الشخصي مرة واحدة."""

from __future__ import annotations

from getpass import getpass

from telethon.sync import TelegramClient
from telethon.sessions import StringSession


def main() -> None:
    print("Telegram String Session generator")
    api_id = int(input("API ID: ").strip())
    api_hash = input("API HASH: ").strip()
    phone = input("Phone number (e.g. +9665XXXXXXXX): ").strip()

    with TelegramClient(StringSession(), api_id, api_hash) as client:
        client.start(phone=phone)
        session = client.session.save()
        me = client.get_me()
        print("\nLogin successful:")
        print(f"Account ID: {getattr(me, 'id', 'unknown')}")
        print(f"Username: @{getattr(me, 'username', None)}" if getattr(me, 'username', None) else "Username: none")
        print("\nTELEGRAM_SESSION_STRING:")
        print(session)
        print("\nIMPORTANT: Keep this string secret. Do not commit it to GitHub.")


if __name__ == "__main__":
    main()
