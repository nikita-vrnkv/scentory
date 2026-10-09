"""Настройки загружаются только при явном вызове load_settings."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from aiogram.utils.token import TokenValidationError, validate_token
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigurationError(ValueError):
    """Ошибка настройки с безопасным для вывода сообщением."""


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(repr=False)
    admin_ids: frozenset[int]
    database_path: Path

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self.admin_ids


def load_settings(env_file: Path = PROJECT_ROOT / ".env") -> Settings:
    # Явный путь исключает поиск чужих .env в родительских каталогах.
    # Уже заданные переменные окружения имеют приоритет.
    load_dotenv(dotenv_path=env_file, override=False, encoding="utf-8-sig")
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ConfigurationError("Заполните BOT_TOKEN в локальном .env.")
    try:
        validate_token(token)
    except TokenValidationError:
        raise ConfigurationError(
            "BOT_TOKEN имеет неверный формат. Проверьте локальный .env."
        ) from None

    raw_ids = os.getenv("ADMIN_IDS", "").strip()
    admin_ids: set[int] = set()
    if raw_ids:
        for part in raw_ids.split(","):
            value = part.strip()
            if not value.isascii() or not value.isdecimal() or int(value) <= 0:
                raise ConfigurationError(
                    "ADMIN_IDS: нужны положительные числовые ID через запятую."
                )
            admin_ids.add(int(value))

    path = Path(
        os.getenv("DATABASE_PATH", "data/scentory.sqlite3").strip() or "data/scentory.sqlite3"
    )
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return Settings(token, frozenset(admin_ids), path)
