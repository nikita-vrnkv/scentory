from dataclasses import dataclass
from pathlib import Path

from scentory.database.admin import AdminRepository
from scentory.database.connection import connect
from scentory.database.orders import OrderRepository


@dataclass(frozen=True)
class Product:
    id: int
    name: str
    description: str
    volume_ml: int
    price_kopecks: int


MAX_QUANTITY = 999


class CartError(ValueError):
    """Понятная покупателю ошибка операции с корзиной."""


@dataclass(frozen=True)
class CartItem:
    product_id: int
    name: str
    volume_ml: int
    price_kopecks: int
    quantity: int
    is_available: bool

    @property
    def subtotal(self) -> int:
        return self.price_kopecks * self.quantity


@dataclass(frozen=True)
class Cart:
    items: tuple[CartItem, ...]

    @property
    def total(self) -> int:
        return sum(item.subtotal for item in self.items)

    @property
    def can_checkout(self) -> bool:
        return bool(self.items) and all(item.is_available for item in self.items)


class Repository(OrderRepository, AdminRepository):
    def __init__(self, path: Path, admin_ids: frozenset[int] = frozenset()):
        self.path = path
        self.admin_ids = frozenset(admin_ids)

    async def get_cart(self, telegram_id: int) -> Cart:
        async with connect(self.path) as db:
            async with db.execute(
                "SELECT p.id AS product_id, p.name, p.volume_ml, p.price_kopecks, "
                "c.quantity, p.is_available FROM cart_items c "
                "JOIN users u ON u.id = c.user_id JOIN products p ON p.id = c.product_id "
                "WHERE u.telegram_id = ? ORDER BY p.id",
                (telegram_id,),
            ) as cursor:
                return Cart(tuple(CartItem(**dict(row)) for row in await cursor.fetchall()))

    async def add_to_cart(self, telegram_id: int, product_id: int, quantity: int = 1) -> None:
        if type(quantity) is not int or not 1 <= quantity <= MAX_QUANTITY:
            raise CartError(f"Количество должно быть целым числом от 1 до {MAX_QUANTITY}.")
        await self._mutate_cart(telegram_id, product_id, "add", quantity)

    async def change_cart_quantity(self, telegram_id: int, product_id: int, delta: int) -> None:
        if type(delta) is not int or delta not in (-1, 1):
            raise CartError("Количество можно изменить только на одну единицу.")
        await self._mutate_cart(telegram_id, product_id, "change", delta)

    async def remove_from_cart(self, telegram_id: int, product_id: int) -> None:
        await self._mutate_cart(telegram_id, product_id, "remove")

    async def _mutate_cart(
        self, telegram_id: int, product_id: int, action: str, amount: int = 0
    ) -> None:
        if type(product_id) is not int or not 0 < product_id <= 9223372036854775807:
            raise CartError("Товар не найден. Откройте каталог заново.")
        async with connect(self.path) as db:
            try:
                # Блокировка берётся ДО чтения количества: параллельные нажатия
                # последовательно меняют актуальную строку, не теряя прибавления.
                await db.execute("BEGIN IMMEDIATE")
                async with db.execute(
                    "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
                ) as cursor:
                    user = await cursor.fetchone()
                if user is None:
                    raise CartError("Сначала откройте магазин командой /start.")
                user_id = user["id"]
                async with db.execute(
                    "SELECT quantity FROM cart_items WHERE user_id = ? AND product_id = ?",
                    (user_id, product_id),
                ) as cursor:
                    item = await cursor.fetchone()
                if action != "add" and item is None:
                    raise CartError("Позиции уже нет в вашей корзине. Откройте корзину заново.")
                if action == "remove":
                    await db.execute(
                        "DELETE FROM cart_items WHERE user_id = ? AND product_id = ?",
                        (user_id, product_id),
                    )
                else:
                    async with db.execute(
                        "SELECT is_available FROM products WHERE id = ?", (product_id,)
                    ) as cursor:
                        product = await cursor.fetchone()
                    if product is None or (not product["is_available"] and amount > 0):
                        raise CartError("Товар не найден или сейчас недоступен.")
                    quantity = (item["quantity"] if item else 0) + amount
                    if quantity < 1:
                        raise CartError("Минимум — 1 штука. Чтобы убрать товар, нажмите «Удалить».")
                    if quantity > MAX_QUANTITY:
                        raise CartError(f"Не более {MAX_QUANTITY} штук одного аромата.")
                    await db.execute(
                        "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (?, ?, ?) "
                        "ON CONFLICT(user_id, product_id) DO UPDATE SET quantity = excluded.quantity",
                        (user_id, product_id, quantity),
                    )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def register_user(self, telegram_id: int) -> int:
        if type(telegram_id) is not int or telegram_id <= 0:
            raise ValueError("Нужен положительный числовой Telegram ID.")
        async with connect(self.path) as connection:
            # Не копируем имена и username из профиля. Псевдоним покупатель
            # задаёт сам при оформлении заказа.
            await connection.execute(
                "INSERT INTO users (telegram_id) VALUES (?) ON CONFLICT(telegram_id) DO NOTHING",
                (telegram_id,),
            )
            async with connection.execute(
                "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
            ) as cursor:
                row = await cursor.fetchone()
            await connection.commit()
            return row["id"]

    async def list_products(self) -> list[Product]:
        async with connect(self.path) as connection:
            async with connection.execute(
                "SELECT id, name, description, volume_ml, price_kopecks "
                "FROM products WHERE is_available = 1 ORDER BY id"
            ) as cursor:
                return [Product(**dict(row)) for row in await cursor.fetchall()]

    async def get_product(self, product_id: int) -> Product | None:
        if type(product_id) is not int or not 0 < product_id <= 9223372036854775807:
            return None
        async with connect(self.path) as connection:
            async with connection.execute(
                "SELECT id, name, description, volume_ml, price_kopecks "
                "FROM products WHERE id = ? AND is_available = 1",
                (product_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return Product(**dict(row)) if row else None
