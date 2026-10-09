import asyncio
import sqlite3
import unittest
from unittest.mock import patch

from aiogram import Dispatcher

import test_checkout
from scentory.database.admin import AdminError, STATUSES
from scentory.database.connection import connect
from scentory.database.repository import Repository
from scentory.handlers.admin import create_admin_router
from scentory.handlers.common import create_router
from scentory.handlers.orders import create_orders_router


class AdminDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await test_checkout.CheckoutDatabaseTests.asyncSetUp(self)
        self.repository = Repository(self.path, frozenset({202, 303}))
        await self.repository.add_to_cart(101, self.product_id)
        key = await self.repository.begin_checkout(101)
        await self.repository.prepare_checkout(101, "Учебный покупатель")
        self.order_id = await self.repository.confirm_checkout(101, key)

    async def test_permissions_for_every_database_method(self):
        for user_id in (101, 404, True, "202"):
            with self.subTest(user_id=user_id):
                with self.assertRaises(PermissionError):
                    await self.repository.admin_list_orders(user_id)
                with self.assertRaises(PermissionError):
                    await self.repository.admin_get_order(user_id, self.order_id)
                with self.assertRaises(PermissionError):
                    await self.repository.admin_set_status(user_id, self.order_id, "Выдан", "Новый")
        with self.assertRaises(PermissionError):
            await Repository(self.path).admin_list_orders(202)

    async def test_statuses_customer_visibility_and_persistence(self):
        previous = "Новый"
        for status in STATUSES[1:] + ("Новый",):
            await self.repository.admin_set_status(202, self.order_id, status, previous)
            customer_order = await Repository(self.path).get_order(101, self.order_id)
            self.assertEqual(customer_order["status"], status)
            self.assertEqual(customer_order["total_kopecks"], 189000)
            self.assertEqual(customer_order["items"][0]["price_kopecks"], 189000)
            previous = status

    async def test_new_list_and_all_list(self):
        self.assertEqual(len(await self.repository.admin_list_orders(202)), 1)
        await self.repository.admin_set_status(202, self.order_id, "В обработке", "Новый")
        self.assertEqual(await self.repository.admin_list_orders(202), [])
        self.assertEqual(len(await self.repository.admin_list_orders(202, False)), 1)
        order = await self.repository.admin_get_order(202, self.order_id)
        self.assertEqual(order["recipient_name"], "Учебный покупатель")

    async def test_invalid_missing_and_stale_updates(self):
        for status in ("Оплачено", "unknown"):
            with self.assertRaises(AdminError):
                await self.repository.admin_set_status(202, self.order_id, status, "Новый")
        for order_id in (0, -1, 9999, 10**30):
            self.assertIsNone(await self.repository.admin_get_order(202, order_id))
            with self.assertRaises(AdminError):
                await self.repository.admin_set_status(202, order_id, "Выдан", "Новый")
        await self.repository.admin_set_status(202, self.order_id, "В обработке", "Новый")
        with self.assertRaises(AdminError):
            await self.repository.admin_set_status(202, self.order_id, "Отменён", "Новый")
        self.assertEqual((await self.repository.get_order(101, self.order_id))["status"], "В обработке")

    async def test_two_managers_cannot_overwrite_stale_status(self):
        results = await asyncio.gather(
            self.repository.admin_set_status(202, self.order_id, "В обработке", "Новый"),
            self.repository.admin_set_status(303, self.order_id, "Отменён", "Новый"),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(result, AdminError) for result in results), 1)
        self.assertEqual(sum(result is None for result in results), 1)

    async def test_write_failure_keeps_status(self):
        async with connect(self.path) as db:
            await db.execute("CREATE TRIGGER fail BEFORE UPDATE ON orders BEGIN SELECT RAISE(ABORT, 'test'); END")
            await db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            await self.repository.admin_set_status(202, self.order_id, "Выдан", "Новый")
        self.assertEqual((await self.repository.get_order(101, self.order_id))["status"], "Новый")

    async def test_pagination(self):
        for _ in range(11):
            await self.repository.add_to_cart(101, self.product_id)
            key = await self.repository.begin_checkout(101)
            await self.repository.prepare_checkout(101, "Псевдоним")
            await self.repository.confirm_checkout(101, key)
        first = await self.repository.admin_list_orders(202)
        second = await self.repository.admin_list_orders(202, page=1)
        self.assertEqual(len(first), 11)
        self.assertEqual(len(second), 2)
        self.assertFalse({o["id"] for o in first[:10]} & {o["id"] for o in second})


class AdminRoutingTests(unittest.IsolatedAsyncioTestCase):
    send = test_checkout.CheckoutRoutingTests.send
    asyncTearDown = test_checkout.CheckoutRoutingTests.asyncTearDown

    async def asyncSetUp(self):
        await test_checkout.CheckoutRoutingTests.asyncSetUp(self)
        self.repository = Repository(self.path, frozenset({202}))
        self.dispatcher = Dispatcher(settings=self.dispatcher.workflow_data["settings"], repository=self.repository)
        self.dispatcher.include_router(create_admin_router())
        self.dispatcher.include_router(create_orders_router())
        self.dispatcher.include_router(create_router())
        await self.repository.add_to_cart(101, 1)
        key = await self.repository.begin_checkout(101)
        await self.repository.prepare_checkout(101, "Учебный покупатель")
        self.order_id = await self.repository.confirm_checkout(101, key)

    async def test_manager_flow_and_customer_status(self):
        listing = (await self.send("menu:admin", user_id=202))[-1]
        detail_data = listing.reply_markup.inline_keyboard[0][0].callback_data
        detail = (await self.send(detail_data, user_id=202))[-1]
        self.assertIn("Учебный покупатель", detail.text)
        status_data = detail.reply_markup.inline_keyboard[0][0].callback_data
        changed = await self.send(status_data, user_id=202)
        self.assertIn("Статус изменён", changed[0].text)
        self.assertIn("Статус: В обработке", changed[-1].text)
        self.assertIn("уже изменён", (await self.send(status_data, user_id=202))[-1].text)
        self.assertIn("Статус: В обработке", (await self.send(f"order:{self.order_id}"))[-1].text)
        self.assertIn("В обработке", (await self.send("menu:orders"))[-1].reply_markup.inline_keyboard[0][0].text)
        self.assertIn("заказов нет", (await self.send("menu:admin", user_id=202))[-1].text)
        self.assertIn("№", (await self.send("admin:list:all:0", user_id=202))[-1].reply_markup.inline_keyboard[0][0].text)

    async def test_forged_customer_callbacks_denied_before_db(self):
        with patch.object(self.repository, "admin_set_status") as write:
            for data in ("menu:admin", "admin:list:all:0", f"admin:order:{self.order_id}",
                         f"admin:status:{self.order_id}:0:3", "admin:anything"):
                self.assertIn("только менеджеру", (await self.send(data))[-1].text)
            write.assert_not_called()

    async def test_database_denies_mismatched_settings(self):
        self.dispatcher.workflow_data["repository"] = Repository(self.path)
        self.assertIn("только менеджеру", (await self.send("menu:admin", user_id=202))[-1].text)

    async def test_bad_callbacks_and_database_failure(self):
        for data in ("admin:order:0", "admin:order:" + "9" * 30, "admin:status:1:0:9", "admin:list:new:9999999"):
            self.assertTrue((await self.send(data, user_id=202))[-1].show_alert)
        with patch.object(self.repository, "admin_list_orders", side_effect=sqlite3.OperationalError("test")):
            self.assertIn("Ошибка БД", (await self.send("menu:admin", user_id=202))[-1].text)
