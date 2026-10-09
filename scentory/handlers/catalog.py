import logging
import sqlite3

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from scentory.database.repository import Repository
from scentory.formatting import format_price
from scentory.keyboards import catalog_menu, product_menu

logger = logging.getLogger("scentory")


def create_catalog_router() -> Router:
    router = Router(name="catalog")
    router.callback_query.filter(F.message.chat.type == "private")

    @router.callback_query(F.data == "menu:catalog")
    async def catalog(callback: CallbackQuery, repository: Repository) -> None:
        if not isinstance(callback.message, Message):
            await callback.answer("Сообщение недоступно. Отправьте /start.", show_alert=True)
            return
        try:
            products = await repository.list_products()
        except sqlite3.Error:
            logger.error("Не удалось прочитать каталог из БД.")
            await callback.answer("Каталог временно недоступен. Попробуйте позже.", show_alert=True)
            return
        await callback.answer()
        await callback.message.answer(
            "Каталог Scentory\nВыберите аромат:"
            if products
            else "В каталоге пока нет доступных ароматов.",
            reply_markup=catalog_menu(products),
        )

    @router.callback_query(F.data.startswith("product:"))
    async def product_card(callback: CallbackQuery, repository: Repository) -> None:
        if not isinstance(callback.message, Message):
            await callback.answer("Сообщение недоступно. Отправьте /start.", show_alert=True)
            return
        value = (callback.data or "").removeprefix("product:")
        if not value.isascii() or not value.isdecimal() or len(value) > 19:
            await callback.answer("Кнопка устарела. Откройте каталог заново.", show_alert=True)
            return
        try:
            product = await repository.get_product(int(value))
        except sqlite3.Error:
            logger.error("Не удалось прочитать товар из БД.")
            await callback.answer(
                "Карточка временно недоступна. Попробуйте позже.", show_alert=True
            )
            return
        if product is None:
            await callback.answer(
                "Товар не найден или сейчас недоступен. Откройте каталог заново.", show_alert=True
            )
            return
        await callback.answer()
        await callback.message.answer(
            f"{product.name}\nОбъём: {product.volume_ml} мл\n\n"
            f"{product.description}\n\nЦена: {format_price(product.price_kopecks)}",
            reply_markup=product_menu(product.id),
        )

    return router
