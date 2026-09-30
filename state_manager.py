"""إدارة حالة النقل لمنع التكرار وحفظ خرائط الردود."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

from config import STATE_FILE, STATE_MAX_ENTRIES

DEFAULT_STATE: dict[str, Any] = {
    "version": 1,
    "source_to_target": {},
    "fingerprints": [],
    "updated_at": None,
}


class StateManager:
    def __init__(self, path: str = STATE_FILE) -> None:
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.exists(self.path):
            return json.loads(json.dumps(DEFAULT_STATE))

        try:
            with open(self.path, "r", encoding="utf-8") as file:
                loaded = json.load(file)
            if not isinstance(loaded, dict):
                raise ValueError("state.json must contain an object")
            state = json.loads(json.dumps(DEFAULT_STATE))
            state.update(loaded)
            if not isinstance(state.get("source_to_target"), dict):
                state["source_to_target"] = {}
            if not isinstance(state.get("fingerprints"), list):
                state["fingerprints"] = []
            return state
        except (OSError, json.JSONDecodeError, ValueError):
            # لا نوقف المشروع بسبب ملف حالة تالف؛ سيتم إنشاء ملف جديد.
            return json.loads(json.dumps(DEFAULT_STATE))

    def has_source_message(self, source_message_id: int) -> bool:
        return str(source_message_id) in self.data["source_to_target"]

    def get_target_message_id(self, source_message_id: int) -> int | None:
        value = self.data["source_to_target"].get(str(source_message_id))
        return int(value) if value is not None else None

    def has_fingerprint(self, fingerprint: str) -> bool:
        return fingerprint in self.data["fingerprints"]

    def remember(self, source_message_id: int, target_message_id: int, fingerprint: str) -> None:
        self.data["source_to_target"][str(source_message_id)] = int(target_message_id)

        fingerprints = self.data["fingerprints"]
        if fingerprint in fingerprints:
            fingerprints.remove(fingerprint)
        fingerprints.append(fingerprint)

        # الاحتفاظ بعدد محدود حتى لا يكبر ملف الحالة إلى ما لا نهاية.
        if len(self.data["source_to_target"]) > STATE_MAX_ENTRIES:
            keys = list(self.data["source_to_target"].keys())
            for key in keys[:-STATE_MAX_ENTRIES]:
                del self.data["source_to_target"][key]

        if len(fingerprints) > STATE_MAX_ENTRIES:
            self.data["fingerprints"] = fingerprints[-STATE_MAX_ENTRIES:]

        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        directory = os.path.dirname(self.path) or "."
        fd, temp_path = tempfile.mkstemp(prefix="state_", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(self.data, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, self.path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
