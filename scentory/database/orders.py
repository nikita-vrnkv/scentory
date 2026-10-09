"""Черновики оформления и атомарное создание заказов."""
import json
from uuid import uuid4

from scentory.database.connection import connect


class CheckoutError(ValueError):
    pass


async def cart_rows(db, user_id: int) -> list[dict]:
    async with db.execute(
        "SELECT p.id AS product_id, p.name, p.volume_ml, p.price_kopecks, c.quantity, p.is_available "
        "FROM cart_items c JOIN products p ON p.id = c.product_id WHERE c.user_id = ? ORDER BY p.id",
        (user_id,),
    ) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


def validate_cart(items: list[dict]) -> None:
    if not items:
        raise CheckoutError("Корзина пуста. Сначала добавьте товары.")
    if any(not item["is_available"] for item in items):
        raise CheckoutError("Удалите недоступные товары перед оформлением.")


class OrderRepository:
    """Использует self.path общего репозитория. Права проверяются в SQL."""

    async def begin_checkout(self, telegram_id: int) -> str:
        async with connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
                user = await cursor.fetchone()
            if user is None:
                raise CheckoutError("Сначала отправьте /start.")
            validate_cart(await cart_rows(db, user["id"]))
            key = uuid4().hex
            await db.execute("DELETE FROM checkout_drafts WHERE user_id = ?", (user["id"],))
            await db.execute("INSERT INTO checkout_drafts (checkout_key, user_id) VALUES (?, ?)", (key, user["id"]))
            await db.commit()
            return key

    async def prepare_checkout(self, telegram_id: int, name: str) -> dict:
        name = " ".join(name.split())
        if not 1 <= len(name) <= 60 or not name.isprintable():
            raise CheckoutError("Введите имя или псевдоним от 1 до 60 символов.")
        async with connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute(
                "SELECT d.* FROM checkout_drafts d JOIN users u ON u.id = d.user_id "
                "WHERE u.telegram_id = ? AND d.recipient_name IS NULL", (telegram_id,),
            ) as cursor:
                draft = await cursor.fetchone()
            if draft is None:
                raise CheckoutError("Для оформления откройте корзину и нажмите «Оформить заказ».")
            items = await cart_rows(db, draft["user_id"])
            validate_cart(items)
            await db.execute("UPDATE checkout_drafts SET recipient_name = ?, snapshot = ? WHERE checkout_key = ?",
                             (name, json.dumps(items, ensure_ascii=False), draft["checkout_key"]))
            await db.commit()
            return {"checkout_key": draft["checkout_key"], "recipient_name": name, "items": items,
                    "total_kopecks": sum(i["price_kopecks"] * i["quantity"] for i in items)}

    async def cancel_checkout(self, telegram_id: int, key: str | None = None) -> None:
        async with connect(self.path) as db:
            await db.execute(
                "DELETE FROM checkout_drafts WHERE user_id = (SELECT id FROM users WHERE telegram_id = ?) "
                "AND (? IS NULL OR checkout_key = ?)", (telegram_id, key, key),
            )
            await db.commit()

    async def confirm_checkout(self, telegram_id: int, key: str) -> int:
        async with connect(self.path) as db:
            try:
                await db.execute("BEGIN IMMEDIATE")
                # Проверка повтора предшествует чтению корзины: после первого
                # подтверждения она пуста или уже содержит новую покупку.
                async with db.execute(
                    "SELECT o.id FROM orders o JOIN users u ON u.id = o.user_id "
                    "WHERE o.checkout_key = ? AND u.telegram_id = ?", (key, telegram_id),
                ) as cursor:
                    existing = await cursor.fetchone()
                if existing:
                    await db.commit()
                    return existing["id"]
                async with db.execute(
                    "SELECT d.* FROM checkout_drafts d JOIN users u ON u.id = d.user_id "
                    "WHERE d.checkout_key = ? AND u.telegram_id = ?", (key, telegram_id),
                ) as cursor:
                    draft = await cursor.fetchone()
                if draft is None or draft["recipient_name"] is None:
                    raise CheckoutError("Подтверждение устарело. Начните оформление из корзины заново.")
                items = await cart_rows(db, draft["user_id"])
                validate_cart(items)
                if items != json.loads(draft["snapshot"]):
                    raise CheckoutError("Состав или цены изменились. Начните оформление заново и проверьте итог.")
                total = sum(i["price_kopecks"] * i["quantity"] for i in items)
                async with db.execute(
                    "INSERT INTO orders (user_id, recipient_name, total_kopecks, checkout_key) VALUES (?, ?, ?, ?)",
                    (draft["user_id"], draft["recipient_name"], total, key),
                ) as cursor:
                    order_id = cursor.lastrowid
                await db.executemany(
                    "INSERT INTO order_items (order_id, product_id, product_name, volume_ml, price_kopecks, quantity) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [(order_id, i["product_id"], i["name"], i["volume_ml"], i["price_kopecks"], i["quantity"]) for i in items],
                )
                await db.execute("DELETE FROM cart_items WHERE user_id = ?", (draft["user_id"],))
                await db.execute("DELETE FROM checkout_drafts WHERE checkout_key = ?", (key,))
                await db.commit()
                return order_id
            except BaseException:
                await db.rollback()
                raise

    async def list_orders(self, telegram_id: int, page: int = 0) -> list[dict]:
        if type(page) is not int or not 0 <= page <= 1000000:
            return []
        async with connect(self.path) as db:
            async with db.execute(
                "SELECT o.* FROM orders o JOIN users u ON u.id = o.user_id "
                "WHERE u.telegram_id = ? ORDER BY o.id DESC LIMIT 11 OFFSET ?", (telegram_id, page * 10),
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def get_order(self, telegram_id: int, order_id: int) -> dict | None:
        if type(order_id) is not int or not 0 < order_id <= 9223372036854775807:
            return None
        async with connect(self.path) as db:
            async with db.execute(
                "SELECT o.* FROM orders o JOIN users u ON u.id = o.user_id WHERE o.id = ? AND u.telegram_id = ?",
                (order_id, telegram_id),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                return None
            order = dict(row)
            async with db.execute("SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order_id,)) as cursor:
                order["items"] = [dict(row) for row in await cursor.fetchall()]
            return order
