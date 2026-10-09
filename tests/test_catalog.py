import sqlite3
from unittest.mock import patch

import support

from scentory.database.connection import connect

TEST_TOKEN = "123456:" + "x" * 35


class CatalogTests(support.BotTestCase):
    async def test_start_registers_user_once(self):
        await self.send()
        await self.send()
        async with connect(self.path) as db:
            async with db.execute("SELECT telegram_id FROM users") as cursor:
                self.assertEqual([row[0] for row in await cursor.fetchall()], [101])

    async def test_catalog_card_back_and_home(self):
        responses = await self.send("menu:catalog")
        self.assertEqual(responses[0].__class__.__name__, "AnswerCallbackQuery")
        rows = responses[-1].reply_markup.inline_keyboard
        self.assertEqual(len(rows), 7)
        self.assertIn("Цитрусовое утро", rows[0][0].text)
        card = (await self.send(rows[0][0].callback_data))[-1]
        self.assertIn("30 мл", card.text)
        self.assertIn("лимона, бергамота и зелёного чая", card.text)
        self.assertIn("1 890 ₽", card.text)
        self.assertEqual(card.reply_markup.inline_keyboard[0][0].text, "Добавить в корзину")
        back = (await self.send(card.reply_markup.inline_keyboard[-1][0].callback_data))[-1]
        self.assertIn("Каталог Scentory", back.text)
        home = (await self.send(rows[-1][0].callback_data, user_id=202))[-1]
        self.assertEqual(home.reply_markup.inline_keyboard[-1][0].callback_data, "menu:admin")

    async def test_empty_catalog_has_way_back(self):
        async with connect(self.path) as db:
            await db.execute("UPDATE products SET is_available = 0")
            await db.commit()
        response = (await self.send("menu:catalog"))[-1]
        self.assertIn("нет доступных", response.text)
        self.assertEqual(response.reply_markup.inline_keyboard[0][0].callback_data, "menu:home")

    async def test_stale_and_forged_product_buttons(self):
        product = (await self.repository.list_products())[0]
        async with connect(self.path) as db:
            await db.execute("UPDATE products SET is_available = 0 WHERE id = ?", (product.id,))
            await db.commit()
        for data in (
            f"product:{product.id}",
            "product:999999",
            "product:0",
            "product:-1",
            "product:1 OR 1=1",
            "product:",
            "product:" + "9" * 30,
        ):
            with self.subTest(data=data):
                responses = await self.send(data)
                self.assertEqual(len(responses), 1)
                self.assertTrue(responses[0].show_alert)

    async def test_old_add_button_is_stale(self):
        self.assertIn("устарела", (await self.send("cart:planned"))[-1].text)
        async with connect(self.path) as db:
            async with db.execute("SELECT count(*) FROM cart_items") as cursor:
                self.assertEqual((await cursor.fetchone())[0], 0)

    async def test_database_errors_are_explained(self):
        for method, data in (("list_products", "menu:catalog"), ("get_product", "product:1")):
            with patch.object(
                self.repository, method, side_effect=sqlite3.OperationalError("test failure")
            ):
                response = (await self.send(data))[-1]
                self.assertTrue(response.show_alert)
                self.assertIn("временно недоступ", response.text)
        with patch.object(
            self.repository, "register_user", side_effect=sqlite3.OperationalError("test failure")
        ):
            self.assertIn("Попробуйте /start позже", (await self.send())[-1].text)
