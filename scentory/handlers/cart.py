import logging
import sqlite3

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from scentory.database.repository import Cart, CartError, Repository
from scentory.formatting import format_price
from scentory.keyboards import cart_menu


def cart_text(cart: Cart) -> str:
    if not cart.items:
        return "Ваша корзина пуста. Выберите аромат в каталоге."
    lines = ["Ваша корзина", "Кнопки с номером изменяют соответствующую позицию.", ""]
    for index, item in enumerate(cart.items, 1):
        lines.append(f"{index}. {item.name} · {item.volume_ml} мл"
                     + (" — недоступен" if not item.is_available else ""))
        lines.append(f"{item.quantity} шт. × {format_price(item.price_kopecks)} = {format_price(item.subtotal)}")
    lines.append(f"\nИтого: {format_price(cart.total)}")
    if not cart.can_checkout:
        lines.append("В сумму включены недоступные товары. Удалите их перед оформлением.")
    return "\n".join(lines)


def create_cart_router() -> Router:
    router = Router(name="cart")
    router.callback_query.filter(F.message.chat.type == "private")

    @router.callback_query((F.data == "menu:cart") | (F.data.startswith("cart:") & (F.data != "cart:checkout")))
    async def cart_action(callback: CallbackQuery, repository: Repository) -> None:
        if not isinstance(callback.message, Message):
            await callback.answer("Сообщение недоступно. Отправьте /start.", show_alert=True)
            return
        data = callback.data or ""
        notification = None
        try:
            if data != "menu:cart":
                parts = data.split(":")
                if (len(parts) != 3 or parts[1] not in {"add", "inc", "dec", "remove"}
                        or not parts[2].isascii() or not parts[2].isdecimal() or len(parts[2]) > 19):
                    raise CartError("Кнопка устарела. Откройте каталог или корзину заново.")
                product_id = int(parts[2])
                # Владелец берётся только из Telegram, никогда из callback_data.
                if parts[1] == "add":
                    await repository.add_to_cart(callback.from_user.id, product_id)
                    notification = "Товар добавлен в корзину."
                elif parts[1] == "remove":
                    await repository.remove_from_cart(callback.from_user.id, product_id)
                    notification = "Позиция удалена."
                else:
                    await repository.change_cart_quantity(callback.from_user.id, product_id, 1 if parts[1] == "inc" else -1)
            cart = await repository.get_cart(callback.from_user.id)
        except CartError as error:
            await callback.answer(str(error), show_alert=True)
            return
        except sqlite3.Error:
            logging.getLogger("scentory").error("Ошибка операции с корзиной в БД.")
            await callback.answer("Не удалось обновить корзину. Откройте её заново и проверьте состав.", show_alert=True)
            return
        await callback.answer(notification)
        await callback.message.answer(cart_text(cart), reply_markup=cart_menu(cart))

    return router
