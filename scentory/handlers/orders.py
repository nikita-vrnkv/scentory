import sqlite3

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from scentory.database.repository import Repository
from scentory.formatting import format_price


def buttons(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=data) for text, data in row] for row in rows
    ])


def order_summary(order: dict) -> str:
    lines = [f"Получатель: {order['recipient_name']}", ""]
    for item in order["items"]:
        name = item.get("product_name", item.get("name"))
        lines.append(f"{name} · {item['volume_ml']} мл\n"
                     f"{item['quantity']} шт. × {format_price(item['price_kopecks'])} = "
                     f"{format_price(item['price_kopecks'] * item['quantity'])}")
    lines.extend([f"\nИтого: {format_price(order['total_kopecks'])}",
                  "Получение: самовывоз из учебного пункта выдачи Scentory.",
                  "Расчёт: при получении."])
    return "\n".join(lines)


def create_orders_router() -> Router:
    router = Router(name="orders")
    router.callback_query.filter(F.message.chat.type == "private")

    @router.callback_query((F.data == "menu:orders") | F.data.startswith("orders:") | F.data.startswith("order:"))
    async def orders(callback: CallbackQuery, repository: Repository) -> None:
        if not isinstance(callback.message, Message):
            await callback.answer("Сообщение недоступно. Отправьте /start.", show_alert=True)
            return
        data = callback.data or ""
        value = "0" if data == "menu:orders" else data.split(":", 1)[-1]
        if not value.isascii() or not value.isdecimal() or len(value) > 19:
            await callback.answer("Кнопка устарела. Откройте «Мои заказы».", show_alert=True)
            return
        try:
            if data.startswith("order:"):
                order = await repository.get_order(callback.from_user.id, int(value))
                if order is None:
                    await callback.answer("Заказ не найден или недоступен.", show_alert=True)
                    return
                text = f"Заказ №{order['id']}\nСтатус: {order['status']}\nДата (UTC): {order['created_at']}\n\n" + order_summary(order)
                keyboard = buttons([[('Мои заказы', 'menu:orders')], [('Главное меню', 'menu:home')]])
            else:
                page = int(value)
                if page > 1000000:
                    await callback.answer("Кнопка устарела.", show_alert=True)
                    return
                found = await repository.list_orders(callback.from_user.id, page)
                text = f"Мои заказы — страница {page + 1}" if found else "На этой странице заказов нет."
                rows = [[(f"№{o['id']} · {o['status']} · {format_price(o['total_kopecks'])}", f"order:{o['id']}")] for o in found[:10]]
                if page:
                    rows.append([("Назад", f"orders:{page - 1}")])
                if len(found) > 10:
                    rows.append([("Далее", f"orders:{page + 1}")])
                rows.append([("Главное меню", "menu:home")])
                keyboard = buttons(rows)
        except sqlite3.Error:
            await callback.answer("Не удалось прочитать заказы. Попробуйте позже.", show_alert=True)
            return
        await callback.answer()
        await callback.message.answer(text, reply_markup=keyboard)

    return router
