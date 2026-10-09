import asyncio
import sqlite3
from unittest.mock import patch

import support

from scentory.database.connection import connect, initialize_database
from scentory.database.orders import CheckoutError
from scentory.database.repository import Repository


class CheckoutDatabaseTests(support.CustomerDatabaseTestCase):
    async def prepare(self):
        await self.repository.add_to_cart(101, self.product_id, 2)
        key = await self.repository.begin_checkout(101)
        draft = await self.repository.prepare_checkout(101, "Учебный покупатель")
        self.assertEqual(draft["checkout_key"], key)
        return key

    async def test_success_snapshots_and_restart(self):
        key = await self.prepare()
        order_id = await self.repository.confirm_checkout(101, key)
        self.assertFalse((await self.repository.get_cart(101)).items)
        await initialize_database(self.path)
        order = await Repository(self.path).get_order(101, order_id)
        self.assertEqual(order["status"], "Новый")
        self.assertEqual(order["total_kopecks"], 378000)
        self.assertEqual(order["recipient_name"], "Учебный покупатель")
        self.assertEqual(order["items"][0]["product_name"], "Цитрусовое утро")
        self.assertEqual(order["items"][0]["quantity"], 2)
        self.assertEqual(order["delivery_method"], "pickup")
        self.assertEqual(order["payment_method"], "on_receipt")

    async def test_historical_price_and_name(self):
        order_id = await self.repository.confirm_checkout(101, await self.prepare())
        async with connect(self.path) as db:
            await db.execute(
                "UPDATE products SET price_kopecks = 100, name = 'Изменён' WHERE id = ?",
                (self.product_id,),
            )
            await db.commit()
        order = await self.repository.get_order(101, order_id)
        self.assertEqual(order["items"][0]["price_kopecks"], 189000)
        self.assertEqual(order["items"][0]["product_name"], "Цитрусовое утро")
        self.assertEqual(order["total_kopecks"], 378000)

    async def test_concurrent_and_repeated_confirmation(self):
        key = await self.prepare()
        ids = await asyncio.gather(*(self.repository.confirm_checkout(101, key) for _ in range(6)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(await self.repository.list_orders(101)), 1)
        await self.repository.add_to_cart(101, self.product_id)
        self.assertEqual(await Repository(self.path).confirm_checkout(101, key), ids[0])
        self.assertEqual((await self.repository.get_cart(101)).items[0].quantity, 1)

    async def test_access_to_draft_and_order(self):
        key = await self.prepare()
        with self.assertRaises(CheckoutError):
            await self.repository.confirm_checkout(202, key)
        await self.repository.cancel_checkout(202, key)
        order_id = await self.repository.confirm_checkout(101, key)
        self.assertIsNone(await self.repository.get_order(202, order_id))
        self.assertEqual(await self.repository.list_orders(202), [])
        with self.assertRaises(CheckoutError):
            await self.repository.confirm_checkout(202, key)

    async def test_changed_cart_or_price_requires_new_review(self):
        key = await self.prepare()
        await self.repository.change_cart_quantity(101, self.product_id, 1)
        with self.assertRaisesRegex(CheckoutError, "изменились"):
            await self.repository.confirm_checkout(101, key)
        key = await self.repository.begin_checkout(101)
        await self.repository.prepare_checkout(101, "Псевдоним")
        async with connect(self.path) as db:
            await db.execute(
                "UPDATE products SET price_kopecks = 200000 WHERE id = ?", (self.product_id,)
            )
            await db.commit()
        with self.assertRaisesRegex(CheckoutError, "изменились"):
            await self.repository.confirm_checkout(101, key)
        self.assertEqual(await self.repository.list_orders(101), [])

    async def test_empty_and_unavailable(self):
        with self.assertRaises(CheckoutError):
            await self.repository.begin_checkout(101)
        key = await self.prepare()
        async with connect(self.path) as db:
            await db.execute(
                "UPDATE products SET is_available = 0 WHERE id = ?", (self.product_id,)
            )
            await db.commit()
        with self.assertRaises(CheckoutError):
            await self.repository.confirm_checkout(101, key)
        await self.repository.remove_from_cart(101, self.product_id)
        with self.assertRaises(CheckoutError):
            await self.repository.confirm_checkout(101, key)

    async def test_cancel_replacement_and_unprepared_key(self):
        key = await self.prepare()
        new_key = await self.repository.begin_checkout(101)
        for invalid in (key, new_key, "unknown"):
            with self.assertRaises(CheckoutError):
                await self.repository.confirm_checkout(101, invalid)
        await self.repository.prepare_checkout(101, "Псевдоним")
        await self.repository.cancel_checkout(101, new_key)
        with self.assertRaises(CheckoutError):
            await self.repository.confirm_checkout(101, new_key)

    async def test_name_validation_and_draft_restart(self):
        await self.repository.add_to_cart(101, self.product_id)
        key = await self.repository.begin_checkout(101)
        for name in ("   ", "я" * 61, "имя\x00"):
            with self.subTest(name=name), self.assertRaises(CheckoutError):
                await self.repository.prepare_checkout(101, name)
        draft = await Repository(self.path).prepare_checkout(101, "  Учебный   покупатель  ")
        self.assertEqual(draft["recipient_name"], "Учебный покупатель")
        await initialize_database(self.path)
        self.assertGreater(await Repository(self.path).confirm_checkout(101, key), 0)

    async def test_rollback_at_each_write_boundary(self):
        await self.repository.add_to_cart(101, 2)
        key = await self.prepare()
        for table, operation in (
            ("orders", "INSERT"),
            ("order_items", "INSERT"),
            ("cart_items", "DELETE"),
            ("checkout_drafts", "DELETE"),
        ):
            async with connect(self.path) as db:
                # Для позиций сбой после первой вставки проверяет частичную запись.
                condition = "WHEN NEW.product_id = 2" if table == "order_items" else ""
                await db.execute(
                    f"CREATE TRIGGER fail BEFORE {operation} ON {table} {condition} BEGIN SELECT RAISE(ABORT, 'test'); END"
                )
                await db.commit()
            with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError):
                await self.repository.confirm_checkout(101, key)
            self.assertEqual((await self.repository.get_cart(101)).items[0].quantity, 2)
            async with connect(self.path) as db:
                for saved_table in ("orders", "order_items"):
                    async with db.execute(f"SELECT count(*) FROM {saved_table}") as cursor:
                        self.assertEqual((await cursor.fetchone())[0], 0)
                await db.execute("DROP TRIGGER fail")
                await db.commit()
        self.assertGreater(await self.repository.confirm_checkout(101, key), 0)

    async def test_upgrade_preserves_existing_cart(self):
        await self.repository.add_to_cart(101, self.product_id, 2)
        async with connect(self.path) as db:
            await db.execute("DROP TABLE checkout_drafts")  # Схема этапа 3 в временной БД.
            await db.commit()
        await initialize_database(self.path)
        self.assertEqual((await self.repository.get_cart(101)).items[0].quantity, 2)
        self.assertEqual(len(await self.repository.list_products()), 6)
        self.assertTrue(await self.repository.begin_checkout(101))

    async def test_pagination(self):
        for _ in range(12):
            await self.repository.confirm_checkout(101, await self.prepare())
        first = await self.repository.list_orders(101)
        second = await self.repository.list_orders(101, 1)
        self.assertEqual(len(first), 11)  # Один дополнительный для кнопки «Далее».
        self.assertEqual(len(second), 2)
        self.assertFalse(set(o["id"] for o in first[:10]) & set(o["id"] for o in second))


class CheckoutRoutingTests(support.BotTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.send()

    async def name(self, value="Учебный покупатель"):
        return (await self.send(text=value))[-1]

    async def test_complete_flow_repeat_and_details(self):
        await self.send("cart:add:1")
        await self.send("cart:checkout")
        review = await self.name()
        self.assertIn("1 890 ₽", review.text)
        self.assertIn("самовывоз", review.text)
        self.assertIn("при получении", review.text)
        confirm = review.reply_markup.inline_keyboard[0][0].callback_data
        success = (await self.send(confirm))[-1]
        self.assertEqual((await self.send(confirm))[-1].text, success.text)
        detail_data = success.reply_markup.inline_keyboard[0][0].callback_data
        details = (await self.send(detail_data))[-1]
        self.assertIn("Статус: Новый", details.text)
        self.assertIn("Учебный покупатель", details.text)
        self.assertIn(
            "№1", (await self.send("menu:orders"))[-1].reply_markup.inline_keyboard[0][0].text
        )
        self.assertIn("недоступен", (await self.send(detail_data, user_id=202))[-1].text)
        self.assertIn("устарело", (await self.send(confirm, user_id=202))[-1].text)

    async def test_back_and_start_invalidate_confirmation(self):
        await self.send("cart:add:1")
        await self.send("cart:checkout")
        review = await self.name()
        confirm = review.reply_markup.inline_keyboard[0][0].callback_data
        await self.send(review.reply_markup.inline_keyboard[1][0].callback_data)
        self.assertIn("устарело", (await self.send(confirm))[-1].text)
        await self.send("cart:checkout")
        review = await self.name()
        await self.send()  # /start отменяет незавершённый черновик.
        self.assertIn(
            "устарело",
            (await self.send(review.reply_markup.inline_keyboard[0][0].callback_data))[-1].text,
        )

    async def test_failed_confirmation_can_retry(self):
        await self.send("cart:add:1")
        await self.send("cart:checkout")
        review = await self.name()
        confirm = review.reply_markup.inline_keyboard[0][0].callback_data
        with patch.object(
            self.repository, "confirm_checkout", side_effect=sqlite3.OperationalError("test")
        ):
            self.assertIn("Ошибка БД", (await self.send(confirm))[-1].text)
        self.assertIn("сохранён", (await self.send(confirm))[-1].text)

    async def test_invalid_buttons_and_name(self):
        for data in ("checkout:confirm:no", "order:-1", "order:" + "9" * 30, "orders:abc"):
            self.assertTrue((await self.send(data))[-1].show_alert)
        await self.send("cart:add:1")
        await self.send("cart:checkout")
        self.assertIn("1 до 60", (await self.name(" ")).text)
