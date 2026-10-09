from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from scentory.database.seed import PRODUCTS


@asynccontextmanager
async def connect(path: Path):
    # Отдельное соединение на операцию: транзакции обработчиков
    # не должны случайно смешиваться на одном общем соединении.
    async with aiosqlite.connect(path, timeout=5) as connection:
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA foreign_keys = ON")
        await connection.execute("PRAGMA busy_timeout = 5000")
        yield connection


async def initialize_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    async with connect(path) as connection:
        try:
            # executescript сам завершает предыдущую транзакцию, поэтому BEGIN
            # находится внутри скрипта. Схема и наполнение сохраняются вместе.
            await connection.executescript("BEGIN IMMEDIATE;\n" + schema)
            await connection.executemany(
                "INSERT INTO products (seed_key, name, description, volume_ml, price_kopecks) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(seed_key) DO NOTHING",
                PRODUCTS,
            )
            await connection.commit()
        except BaseException:
            await connection.rollback()
            raise
