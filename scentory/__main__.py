"""Запуск из корня проекта: python -m scentory."""

import asyncio
import logging
import sqlite3

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.types import ErrorEvent

from scentory.config import ConfigurationError, load_settings
from scentory.handlers.common import create_router
from scentory.handlers.catalog import create_catalog_router
from scentory.handlers.cart import create_cart_router
from scentory.handlers.checkout import create_checkout_router
from scentory.handlers.orders import create_orders_router
from scentory.handlers.admin import create_admin_router
from scentory.database.connection import initialize_database
from scentory.database.repository import Repository

logger = logging.getLogger("scentory")


async def safe_error_handler(event: ErrorEvent) -> bool:
    # Не выводим Update, URL запроса или текст исключения: там могут быть секреты.
    logger.error("Ошибка обработки события (%s).", type(event.exception).__name__)
    return True


async def main() -> None:
    settings = load_settings()
    await initialize_database(settings.database_path)
    dispatcher = Dispatcher(settings=settings, repository=Repository(settings.database_path, settings.admin_ids))
    # Специальные обработчики идут раньше общего ответа на устаревшие кнопки.
    dispatcher.include_router(create_catalog_router())
    dispatcher.include_router(create_admin_router())
    dispatcher.include_router(create_checkout_router())
    dispatcher.include_router(create_orders_router())
    dispatcher.include_router(create_cart_router())
    dispatcher.include_router(create_router())
    dispatcher.errors.register(safe_error_handler)
    async with Bot(token=settings.bot_token) as bot:
        # Проверяем доступ до сообщения о старте, не печатая сведения об аккаунте.
        await bot.get_me()
        logger.info("Scentory запущен. Для остановки нажмите Ctrl+C.")
        await dispatcher.start_polling(bot, close_bot_session=False)


def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    # Логи библиотек могут содержать URL с токеном и данные Telegram.
    logging.getLogger("aiogram").disabled = True
    for name in ("aiogram.dispatcher", "aiogram.event", "aiogram.middlewares", "aiohttp"):
        library_logger = logging.getLogger(name)
        library_logger.handlers = [logging.NullHandler()]
        library_logger.propagate = False
    try:
        asyncio.run(main())
    except ConfigurationError as error:
        logger.error("%s", error)
        return 1
    except TelegramUnauthorizedError:
        logger.error("Telegram отклонил BOT_TOKEN. Проверьте его локально.")
        return 1
    except (sqlite3.Error, OSError):
        logger.error("Не удалось открыть базу или файлы проекта. Проверьте DATABASE_PATH и права доступа.")
        return 1
    except TelegramNetworkError:
        logger.error("Нет соединения с Telegram. Проверьте интернет и повторите запуск.")
        return 1
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scentory остановлен.")
    except Exception as error:
        logger.error("Не удалось запустить бота (%s). Проверьте настройки и соединение.", type(error).__name__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
