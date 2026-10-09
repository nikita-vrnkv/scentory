"""Проверка сборки приложения без настоящего токена и без polling."""

from unittest.mock import AsyncMock, patch

import support

from scentory.__main__ import main
from scentory.config import Settings


class StartupTests(support.DatabaseTestCase):
    async def test_main_initializes_database_and_closes_session(self):
        settings = Settings(support.TEST_TOKEN, frozenset({202}), self.path)
        bot = AsyncMock()
        with (
            patch("scentory.__main__.load_settings", return_value=settings),
            patch("scentory.__main__.Bot") as bot_class,
            patch("scentory.__main__.Dispatcher.start_polling", new_callable=AsyncMock) as polling,
        ):
            bot_class.return_value.__aenter__.return_value = bot
            bot_class.return_value.__aexit__.return_value = False
            await main()
            bot.get_me.assert_awaited_once()
            polling.assert_awaited_once_with(bot, close_bot_session=False)
            bot_class.return_value.__aexit__.assert_awaited_once()
        self.assertEqual(len(await self.repository.list_products()), 6)
