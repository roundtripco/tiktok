"""محاكي لخوادم تيليجرام: نجرّب البوت كامل بدون إنترنت وبدون توكن حقيقي."""

from __future__ import annotations

import itertools
import json
import time
from dataclasses import dataclass, field

from telegram import Update
from telegram.ext import Application
from telegram.request import BaseRequest

BOT_USER = {"id": 777, "is_bot": True, "first_name": "AqarBot", "username": "AqarTestBot"}
TRUE_METHODS = {"setMyCommands", "answerCallbackQuery", "deleteMessage", "sendChatAction"}


@dataclass
class Call:
    method: str
    params: dict
    files: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.params.get("text") or self.params.get("caption") or ""

    @property
    def markup(self) -> dict:
        raw = self.params.get("reply_markup")
        if isinstance(raw, str):
            raw = json.loads(raw)
        return raw or {}

    def buttons(self) -> list[dict]:
        return [b for row in self.markup.get("inline_keyboard", []) for b in row]

    def callback_data(self) -> list[str]:
        return [b["callback_data"] for b in self.buttons() if "callback_data" in b]

    def urls(self) -> list[str]:
        return [b["url"] for b in self.buttons() if "url" in b]


class FakeTelegram(BaseRequest):
    def __init__(self):
        self.calls: list[Call] = []
        self.files: dict[str, bytes] = {}
        self._ids = itertools.count(1000)

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    @property
    def read_timeout(self):
        return 10

    async def do_request(self, url, method, request_data=None, **_):
        if "/file/bot" in url:
            return 200, self.files[url.rsplit("/", 1)[1]]
        api = url.rsplit("/", 1)[1]
        params = dict(request_data.parameters) if request_data else {}
        files = {}
        if request_data is not None and request_data.contains_files:
            for name, value in request_data.multipart_data.items():
                files[name] = (value[0], value[1])
        self.calls.append(Call(api, params, files))
        return 200, json.dumps({"ok": True, "result": self._result(api, params)}).encode()

    def _result(self, api: str, params: dict):
        if api == "getMe":
            return BOT_USER
        if api in TRUE_METHODS:
            return True
        if api == "getFile":
            fid = params["file_id"]
            return {"file_id": fid, "file_unique_id": "u" + fid, "file_size": len(self.files[fid]), "file_path": fid}
        return {
            "message_id": next(self._ids), "date": int(time.time()),
            "chat": {"id": int(params.get("chat_id", 0)), "type": "private"},
            "from": BOT_USER, "text": params.get("text", ""),
        }


class Client:
    """مستخدم وهمي يكلم البوت."""

    _update_ids = itertools.count(1)

    def __init__(self, app: Application, tg: FakeTelegram, user_id: int, first_name: str, last_name: str = ""):
        self.app, self.tg = app, tg
        self.user = {"id": user_id, "is_bot": False, "first_name": first_name, "last_name": last_name}

    @property
    def chat(self) -> dict:
        return {"id": self.user["id"], "type": "private"}

    async def _process(self, payload: dict) -> list[Call]:
        before = len(self.tg.calls)
        payload["update_id"] = next(self._update_ids)
        await self.app.process_update(Update.de_json(payload, self.app.bot))
        return self.tg.calls[before:]

    def _message(self, **extra) -> dict:
        return {"message_id": next(self.tg._ids), "date": int(time.time()), "chat": self.chat,
                "from": self.user, **extra}

    async def send(self, text: str) -> list[Call]:
        extra = {"text": text}
        if text.startswith("/"):
            extra["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        return await self._process({"message": self._message(**extra)})

    async def photo(self, content: bytes) -> list[Call]:
        fid = f"photo{len(self.tg.files)}"
        self.tg.files[fid] = content
        sizes = [{"file_id": fid, "file_unique_id": "u" + fid, "width": 1280, "height": 960}]
        return await self._process({"message": self._message(photo=sizes)})

    async def document(self, content: bytes, mime: str, name: str) -> list[Call]:
        fid = f"doc{len(self.tg.files)}"
        self.tg.files[fid] = content
        doc = {"file_id": fid, "file_unique_id": "u" + fid, "file_name": name, "mime_type": mime}
        return await self._process({"message": self._message(document=doc)})

    def _visible_buttons(self) -> set[str]:
        mine = [c for c in self.tg.calls if str(c.params.get("chat_id")) == str(self.user["id"])]
        return {d for c in mine for d in c.callback_data()}

    async def press(self, data: str) -> list[Call]:
        assert data in self._visible_buttons(), f"الزر {data} مو موجود عند المستخدم"
        query = {
            "id": str(next(self._update_ids)), "from": self.user, "chat_instance": "ci", "data": data,
            "message": self._message(text="...") | {"from": BOT_USER},
        }
        return await self._process({"callback_query": query})


def texts(calls: list[Call]) -> str:
    return "\n---\n".join(c.text for c in calls if c.text)
