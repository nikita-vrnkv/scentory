import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scentory.database.connection import connect, initialize_database
from scentory.database.repository import Repository
from scentory.formatting import format_price


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "data" / "test.sqlite3"
        await initialize_database(self.path)
        self.repository = Repository(self.path)

    async def test_exact_catalog(self):
        products = await self.repository.list_products()
        self.assertEqual([(p.name, p.volume_ml, p.price_kopecks) for p in products], [
            ("Цитрусовое утро", 30, 189000), ("Цветочный сад", 30, 219000),
            ("Ванильный вечер", 30, 229000), ("Морской бриз", 50, 259000),
            ("Тёмный лес", 50, 279000), ("Пряная ночь", 50, 299000),
        ])
        self.assertTrue(all(p.description for p in products))

    async def test_reinitialization_preserves_changes_and_ids(self):
        original = await self.repository.list_products()
        async with connect(self.path) as db:
            await db.execute("UPDATE products SET price_kopecks = 123456, is_available = 0 WHERE id = ?", (original[0].id,))
            await db.commit()
        await initialize_database(self.path)
        async with connect(self.path) as db:
            async with db.execute("SELECT id, price_kopecks, is_available FROM products ORDER BY id") as cursor:
                rows = await cursor.fetchall()
        self.assertEqual([r["id"] for r in rows], [p.id for p in original])
        self.assertEqual((rows[0]["price_kopecks"], rows[0]["is_available"]), (123456, 0))

    async def test_concurrent_initialization(self):
        await asyncio.gather(initialize_database(self.path), initialize_database(self.path))
        self.assertEqual(len(await self.repository.list_products()), 6)

    async def test_users_are_unique_and_persistent(self):
        ids = await asyncio.gather(self.repository.register_user(101), self.repository.register_user(101))
        self.assertEqual(ids[0], ids[1])
        other = await self.repository.register_user(202)
        self.assertNotEqual(other, ids[0])
        self.assertEqual(await Repository(self.path).register_user(101), ids[0])
        async with connect(self.path) as db:
            async with db.execute("SELECT * FROM users ORDER BY id") as cursor:
                users = await cursor.fetchall()
        self.assertEqual(len(users), 2)
        self.assertIsNone(users[0]["display_name"])
        self.assertEqual(users[0]["platform"], "telegram")
        self.assertTrue(users[0]["created_at"].endswith("Z"))

    async def test_invalid_user_id(self):
        for value in (0, -1, True, "101", 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                await self.repository.register_user(value)

    async def test_missing_unavailable_and_invalid_product(self):
        product = (await self.repository.list_products())[0]
        self.assertEqual(await self.repository.get_product(product.id), product)
        async with connect(self.path) as db:
            await db.execute("UPDATE products SET is_available = 0 WHERE id = ?", (product.id,))
            await db.commit()
        self.assertIsNone(await self.repository.get_product(product.id))
        self.assertEqual(len(await self.repository.list_products()), 5)
        for value in (999999, -1, 0, True, "1 OR 1=1", 10**30):
            self.assertIsNone(await self.repository.get_product(value))

    async def test_empty_catalog(self):
        async with connect(self.path) as db:
            await db.execute("UPDATE products SET is_available = 0")
            await db.commit()
        self.assertEqual(await self.repository.list_products(), [])

    async def test_schema_constraints_and_foreign_keys(self):
        user_id = await self.repository.register_user(101)
        product_id = (await self.repository.list_products())[0].id
        async with connect(self.path) as db:
            async with db.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cursor:
                tables = {row[0] for row in await cursor.fetchall()}
            self.assertTrue({"users", "products", "cart_items", "orders", "order_items"} <= tables)
            for quantity in (0, -1, 1.5):
                with self.subTest(quantity=quantity), self.assertRaises(sqlite3.IntegrityError):
                    await db.execute("INSERT INTO cart_items VALUES (?, ?, ?)", (user_id, product_id, quantity))
            with self.assertRaises(sqlite3.IntegrityError):
                await db.execute("INSERT INTO cart_items VALUES (?, ?, 1)", (999999, product_id))
            for price in (0, -1, 1.5):
                with self.subTest(price=price), self.assertRaises(sqlite3.IntegrityError):
                    await db.execute("UPDATE products SET price_kopecks = ? WHERE id = ?", (price, product_id))

    def test_money_format(self):
        self.assertEqual(format_price(189000), "1 890 ₽")
        self.assertEqual(format_price(189099), "1 890,99 ₽")
        self.assertEqual(format_price(1), "0,01 ₽")
