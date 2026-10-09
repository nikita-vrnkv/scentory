import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher
from aiogram.types import Update

from scentory.config import ConfigurationError, Settings, load_settings
from scentory.handlers.common import create_router
from scentory.handlers.admin import create_admin_router
from scentory.database.repository import Repository

# Синтетическое значение только для локальных тестов; запросы в Telegram запрещены mock.
TEST_TOKEN = "123456:" + "x" * 35


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "settings.txt"
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_missing_token(self):
        with self.assertRaises(ConfigurationError):
            load_settings(self.path)

    def test_invalid_token_does_not_leak(self):
        os.environ["BOT_TOKEN"] = "synthetic-secret"
        with self.assertRaises(ConfigurationError) as caught:
            load_settings(self.path)
        self.assertNotIn("synthetic-secret", str(caught.exception))

    def test_load_file_and_environment_priority(self):
        self.path.write_text(f"BOT_TOKEN={TEST_TOKEN}\nADMIN_IDS=101, 202,101\n", encoding="utf-8")
        os.environ["ADMIN_IDS"] = "303"
        settings = load_settings(self.path)
        self.assertEqual(settings.admin_ids, frozenset({303}))
        self.assertEqual(settings.bot_token, TEST_TOKEN)
        self.assertNotIn(TEST_TOKEN, repr(settings))
        self.assertTrue(settings.database_path.is_absolute())

    def test_admin_ids_validation(self):
        os.environ["BOT_TOKEN"] = TEST_TOKEN
        for value in ("-1", "0", "name", "101,", "1.5"):
            with self.subTest(value=value):
                os.environ["ADMIN_IDS"] = value
                with self.assertRaises(ConfigurationError):
                    load_settings(self.path)

    def test_no_managers_by_default(self):
        os.environ["BOT_TOKEN"] = TEST_TOKEN
        self.assertEqual(load_settings(self.path).admin_ids, frozenset())


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = Bot(TEST_TOKEN)
        self.bot.session = AsyncMock()
        self.repository = AsyncMock(spec=Repository)
        self.repository.admin_list_orders.return_value = []
        self.dispatcher = Dispatcher(settings=Settings(TEST_TOKEN, frozenset({202}), Path("unused")), repository=self.repository)
        self.dispatcher.include_router(create_admin_router())
        self.dispatcher.include_router(create_router())

    async def asyncTearDown(self):
        await self.bot.session.close()

    async def send(self, text="/start", user_id=101, callback=None):
        user = {"id": user_id, "is_bot": False, "first_name": "Учебный"}
        message = {"message_id": 1, "date": 0, "chat": {"id": user_id, "type": "private"},
                   "from": user, "text": text}
        if text.startswith("/"):
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text)}]
        payload = {"update_id": 1, "message": message}
        if callback is not None:
            payload = {"update_id": 2, "callback_query": {
                "id": "test", "from": user, "chat_instance": "test", "message": message, "data": callback}}
        await self.dispatcher.feed_update(self.bot, Update.model_validate(payload))
        return self.bot.session.call_args.args[1]

    async def test_start_customer(self):
        response = await self.send()
        self.assertIn("Scentory", response.text)
        self.assertEqual([row[0].text for row in response.reply_markup.inline_keyboard],
                         ["Каталог", "Корзина", "Мои заказы"])

    async def test_start_manager(self):
        response = await self.send(user_id=202)
        self.assertEqual(response.reply_markup.inline_keyboard[-1][0].callback_data, "menu:admin")

    async def test_myid(self):
        self.assertEqual((await self.send("/myid")).text, "Ваш Telegram ID: 101")

    async def test_admin_command_denied(self):
        self.assertIn("только менеджеру", (await self.send("/admin")).text)

    async def test_forged_admin_callback_denied(self):
        response = await self.send(callback="menu:admin")
        self.assertIn("только менеджеру", response.text)
        self.assertTrue(response.show_alert)

    async def test_manager_callback(self):
        self.assertIn("Новые заказы", (await self.send(user_id=202, callback="menu:admin")).text)

    async def test_placeholder_and_stale_buttons(self):
        self.assertIn("устарела", (await self.send(callback="old:button")).text)


if __name__ == "__main__":
    unittest.main()
