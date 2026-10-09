import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from aiogram import Dispatcher

import test_catalog
from scentory.database.connection import connect, initialize_database
from scentory.database.repository import CartError, Repository
from scentory.handlers.cart import create_cart_router
from scentory.handlers.catalog import create_catalog_router
from scentory.handlers.common import create_router
from scentory.handlers.checkout import create_checkout_router


class CartDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "cart.sqlite3"
        await initialize_database(self.path)
        self.repository = Repository(self.path)
        await self.repository.register_user(101)
        await self.repository.register_user(202)
        self.product_id = (await self.repository.list_products())[0].id

    async def test_sum_and_persistence(self):
        products = await self.repository.list_products()
        await self.repository.add_to_cart(101, products[0].id, 2)
        await self.repository.add_to_cart(101, products[1].id, 3)
        cart = await Repository(self.path).get_cart(101)
        self.assertEqual(cart.total, 2 * 189000 + 3 * 219000)
        self.assertTrue(cart.can_checkout)

    async def test_increment_decrement_minimum_and_remove(self):
        await self.repository.add_to_cart(101, self.product_id)
        await self.repository.change_cart_quantity(101, self.product_id, 1)
        self.assertEqual((await self.repository.get_cart(101)).items[0].quantity, 2)
        await self.repository.change_cart_quantity(101, self.product_id, -1)
        with self.assertRaises(CartError):
            await self.repository.change_cart_quantity(101, self.product_id, -1)
        self.assertEqual((await self.repository.get_cart(101)).total, 189000)
        await self.repository.remove_from_cart(101, self.product_id)
        cart = await self.repository.get_cart(101)
        self.assertEqual(cart.items, ())
        self.assertEqual(cart.total, 0)
        self.assertFalse(cart.can_checkout)

    async def test_invalid_quantity(self):
        for quantity in (0, -1, 1.5, True, "2", 1000):
            with self.subTest(quantity=quantity), self.assertRaises(CartError):
                await self.repository.add_to_cart(101, self.product_id, quantity)
        for delta in (0, 2, -2, True, "1"):
            with self.subTest(delta=delta), self.assertRaises(CartError):
                await self.repository.change_cart_quantity(101, self.product_id, delta)
        self.assertEqual((await self.repository.get_cart(101)).items, ())

    async def test_limit_and_rollback(self):
        await self.repository.add_to_cart(101, self.product_id, 999)
        with self.assertRaises(CartError):
            await self.repository.add_to_cart(101, self.product_id)
        self.assertEqual((await self.repository.get_cart(101)).items[0].quantity, 999)

    async def test_user_isolation_and_stale_actions(self):
        await self.repository.add_to_cart(101, self.product_id, 2)
        self.assertEqual((await self.repository.get_cart(202)).items, ())
        with self.assertRaises(CartError):
            await self.repository.remove_from_cart(202, self.product_id)
        with self.assertRaises(CartError):
            await self.repository.change_cart_quantity(202, self.product_id, 1)
        await self.repository.add_to_cart(202, self.product_id)
        await self.repository.remove_from_cart(202, self.product_id)
        self.assertEqual((await self.repository.get_cart(101)).items[0].quantity, 2)

    async def test_current_prices_and_unavailable_items(self):
        await self.repository.add_to_cart(101, self.product_id, 2)
        async with connect(self.path) as db:
            await db.execute("UPDATE products SET price_kopecks = 123456, is_available = 0 WHERE id = ?", (self.product_id,))
            await db.commit()
        cart = await self.repository.get_cart(101)
        self.assertEqual(cart.total, 246912)
        self.assertFalse(cart.can_checkout)
        with self.assertRaises(CartError):
            await self.repository.add_to_cart(101, self.product_id)
        with self.assertRaises(CartError):
            await self.repository.change_cart_quantity(101, self.product_id, 1)
        await self.repository.change_cart_quantity(101, self.product_id, -1)
        await self.repository.remove_from_cart(101, self.product_id)

    async def test_concurrent_additions(self):
        await asyncio.gather(*(self.repository.add_to_cart(101, self.product_id) for _ in range(10)))
        self.assertEqual((await self.repository.get_cart(101)).items[0].quantity, 10)

    async def test_missing_product_and_unregistered_user(self):
        for product_id in (0, -1, 99999, "1 OR 1=1", True, 10**30):
            with self.subTest(product_id=product_id), self.assertRaises(CartError):
                await self.repository.add_to_cart(101, product_id)
        with self.assertRaises(CartError):
            await self.repository.add_to_cart(303, self.product_id)

    async def test_write_failure_preserves_cart(self):
        await self.repository.add_to_cart(101, self.product_id)
        async with connect(self.path) as db:
            await db.execute("CREATE TRIGGER fail_update BEFORE UPDATE ON cart_items BEGIN SELECT RAISE(ABORT, 'test'); END")
            await db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            await self.repository.change_cart_quantity(101, self.product_id, 1)
        self.assertEqual((await self.repository.get_cart(101)).items[0].quantity, 1)


class CartRoutingTests(unittest.IsolatedAsyncioTestCase):
    # Общий тестовый транспорт использует AsyncMock, а БД — временный файл.
    send = test_catalog.CatalogTests.send
    asyncTearDown = test_catalog.CatalogTests.asyncTearDown

    async def asyncSetUp(self):
        await test_catalog.CatalogTests.asyncSetUp(self)
        self.dispatcher = Dispatcher(**self.dispatcher.workflow_data)
        self.dispatcher.include_router(create_catalog_router())
        self.dispatcher.include_router(create_checkout_router())
        self.dispatcher.include_router(create_cart_router())
        self.dispatcher.include_router(create_router())
        await self.send()

    async def test_full_cart_navigation(self):
        catalog = (await self.send("menu:catalog"))[-1]
        card = (await self.send(catalog.reply_markup.inline_keyboard[0][0].callback_data))[-1]
        cart = (await self.send(card.reply_markup.inline_keyboard[0][0].callback_data))[-1]
        self.assertIn("1 шт. × 1 890 ₽ = 1 890 ₽", cart.text)
        controls = cart.reply_markup.inline_keyboard[0]
        self.assertIn("3 780 ₽", (await self.send(controls[1].callback_data))[-1].text)
        await self.send(controls[0].callback_data)
        self.assertIn("Минимум", (await self.send(controls[0].callback_data))[-1].text)
        self.assertIn("Введите имя", (await self.send("cart:checkout"))[-1].text)
        self.assertIn("пуста", (await self.send(controls[2].callback_data))[-1].text)
        self.assertIn("Корзина пуста", (await self.send("cart:checkout"))[-1].text)

    async def test_forged_and_old_callbacks(self):
        for data in ("cart:planned", "cart:inc:-1", "cart:add:1:202", "cart:remove:abc", "cart:add:" + "9" * 30):
            with self.subTest(data=data):
                self.assertTrue((await self.send(data))[-1].show_alert)
        await self.send("cart:add:1")
        self.assertIn("Сначала", (await self.send("cart:inc:1", user_id=202))[-1].text)
        await self.send(user_id=202)
        self.assertIn("Позиции уже нет", (await self.send("cart:remove:1", user_id=202))[-1].text)
        self.assertEqual((await self.repository.get_cart(101)).items[0].quantity, 1)

    async def test_unavailable_blocks_checkout(self):
        await self.send("cart:add:1")
        async with connect(self.path) as db:
            await db.execute("UPDATE products SET is_available = 0 WHERE id = 1")
            await db.commit()
        response = (await self.send("menu:cart"))[-1]
        self.assertIn("недоступен", response.text)
        self.assertNotIn("cart:checkout", [b.callback_data for row in response.reply_markup.inline_keyboard for b in row])
        self.assertIn("недоступные", (await self.send("cart:checkout"))[-1].text)

    async def test_database_error(self):
        with patch.object(self.repository, "add_to_cart", side_effect=sqlite3.OperationalError("test")):
            self.assertIn("проверьте состав", (await self.send("cart:add:1"))[-1].text)
