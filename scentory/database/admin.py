"""Менеджерские запросы: каждый метод самостоятельно проверяет права."""

from scentory.database.connection import connect

STATUSES = ("Новый", "В обработке", "Готов к выдаче", "Выдан", "Отменён")


class AdminError(ValueError):
    pass


class AdminRepository:
    def _require_admin(self, telegram_id: int) -> None:
        if type(telegram_id) is not int or telegram_id not in self.admin_ids:
            raise PermissionError("Доступ разрешён только менеджеру.")

    async def admin_list_orders(
        self, telegram_id: int, only_new: bool = True, page: int = 0
    ) -> list[dict]:
        self._require_admin(telegram_id)
        if type(page) is not int or not 0 <= page <= 1000000:
            raise AdminError("Неверная страница. Откройте /admin заново.")
        async with connect(self.path) as db:
            async with db.execute(
                "SELECT id, status, total_kopecks FROM orders WHERE (? = 0 OR status = 'Новый') "
                "ORDER BY id DESC LIMIT 11 OFFSET ?",
                (int(only_new), page * 10),
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def admin_get_order(self, telegram_id: int, order_id: int) -> dict | None:
        self._require_admin(telegram_id)
        if type(order_id) is not int or not 0 < order_id <= 9223372036854775807:
            return None
        async with connect(self.path) as db:
            async with db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)) as cursor:
                row = await cursor.fetchone()
            if row is None:
                return None
            order = dict(row)
            async with db.execute(
                "SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order_id,)
            ) as cursor:
                order["items"] = [dict(row) for row in await cursor.fetchall()]
            return order

    async def admin_set_status(
        self, telegram_id: int, order_id: int, status: str, expected_status: str
    ) -> None:
        self._require_admin(telegram_id)
        if status not in STATUSES or expected_status not in STATUSES:
            raise AdminError("Недопустимый статус.")
        if type(order_id) is not int or not 0 < order_id <= 9223372036854775807:
            raise AdminError("Заказ не найден.")
        async with connect(self.path) as db:
            # Условный UPDATE не затирает изменение другого менеджера,
            # сделанное после открытия этой карточки.
            async with db.execute(
                "UPDATE orders SET status = ? WHERE id = ? AND status = ?",
                (status, order_id, expected_status),
            ) as cursor:
                if cursor.rowcount != 1:
                    raise AdminError(
                        "Заказ не найден или статус уже изменён. Откройте карточку заново."
                    )
            await db.commit()
