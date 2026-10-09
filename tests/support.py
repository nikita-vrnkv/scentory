"""Общие фикстуры: временная БД и подмена сетевого транспорта Telegram."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from aiogram import Bot
from aiogram.types import Update

from scentory.__main__ import create_dispatcher
from scentory.config import Settings
from scentory.database.connection import initialize_database
from scentory.database.repository import Repository

TEST_TOKEN = "123456:" + "x" * 35


class DatabaseTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "data" / "test.sqlite3"
        await initialize_database(self.path)
        self.repository = Repository(self.path)


class CustomerDatabaseTestCase(DatabaseTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.repository.register_user(101)
        await self.repository.register_user(202)
        self.product_id = (await self.repository.list_products())[0].id


class BotTestCase(DatabaseTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        settings = Settings(TEST_TOKEN, frozenset({202}), self.path)
        self.repository = Repository(self.path, settings.admin_ids)
        self.bot = Bot(TEST_TOKEN, session=AsyncMock())
        self.dispatcher = create_dispatcher(settings, self.repository)

    async def asyncTearDown(self):
        await self.bot.session.close()

    async def send(self, data=None, user_id=101, text="/start"):
        self.bot.session.reset_mock()
        user = {"id": user_id, "is_bot": False, "first_name": "Учебный"}
        message = {
            "message_id": 1,
            "date": 1,
            "chat": {"id": user_id, "type": "private"},
            "from": user,
            "text": text,
        }
        if text.startswith("/"):
            message["entities"] = [
                {"type": "bot_command", "offset": 0, "length": len(text.split()[0])}
            ]
        payload = {"update_id": 1, "message": message}
        if data is not None:
            payload = {
                "update_id": 2,
                "callback_query": {
                    "id": "test",
                    "from": user,
                    "chat_instance": "test",
                    "message": message,
                    "data": data,
                },
            }
        await self.dispatcher.feed_update(self.bot, Update.model_validate(payload))
        return [call.args[1] for call in self.bot.session.call_args_list]
