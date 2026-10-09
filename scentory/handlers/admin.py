import re
import sqlite3

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from scentory.config import Settings
from scentory.database.admin import AdminError, STATUSES
from scentory.database.repository import Repository
from scentory.formatting import format_price
from scentory.handlers.orders import buttons, order_summary


async def list_view(repository: Repository, user_id: int, mode: str = "new", page: int = 0):
    orders = await repository.admin_list_orders(user_id, mode == "new", page)
    title = "Новые заказы" if mode == "new" else "Все заказы"
    text = f"{title} — страница {page + 1}" if orders else f"{title}: на этой странице заказов нет."
    rows = [[(f"№{o['id']} · {o['status']} · {format_price(o['total_kopecks'])}", f"admin:order:{o['id']}")] for o in orders[:10]]
    if page:
        rows.append([("Назад", f"admin:list:{mode}:{page - 1}")])
    if len(orders) > 10:
        rows.append([("Далее", f"admin:list:{mode}:{page + 1}")])
    rows.extend([[('Новые заказы', 'admin:list:new:0'), ('Все заказы', 'admin:list:all:0')],
                 [('Главное меню', 'menu:home')]])
    return text, buttons(rows)


async def detail_view(repository: Repository, user_id: int, order_id: int):
    order = await repository.admin_get_order(user_id, order_id)
    if order is None:
        raise AdminError("Заказ не найден.")
    current = STATUSES.index(order["status"])
    rows = [[(status, f"admin:status:{order_id}:{current}:{index}")]
            for index, status in enumerate(STATUSES) if index != current]
    rows.extend([[('Обновить карточку', f'admin:order:{order_id}')],
                 [('Новые заказы', 'admin:list:new:0'), ('Все заказы', 'admin:list:all:0')]])
    return (f"Заказ №{order_id}\nСтатус: {order['status']}\nДата (UTC): {order['created_at']}\n\n"
            + order_summary(order) + "\n\nВыберите новый статус:", buttons(rows))


def create_admin_router() -> Router:
    router = Router(name="admin")
    router.message.filter(F.chat.type == "private")
    router.callback_query.filter(F.message.chat.type == "private")

    @router.message(Command("admin"))
    async def admin_command(message: Message, settings: Settings, repository: Repository) -> None:
        if message.from_user is None or not settings.is_admin(message.from_user.id):
            await message.answer("Доступ разрешён только менеджеру.")
            return
        try:
            text, keyboard = await list_view(repository, message.from_user.id)
        except (PermissionError, AdminError) as error:
            await message.answer(str(error))
            return
        except sqlite3.Error:
            await message.answer("Не удалось прочитать заказы. Повторите /admin позже.")
            return
        await message.answer(text, reply_markup=keyboard)

    @router.callback_query((F.data == "menu:admin") | F.data.startswith("admin:"))
    async def admin_callback(callback: CallbackQuery, settings: Settings, repository: Repository) -> None:
        if not settings.is_admin(callback.from_user.id):
            await callback.answer("Доступ разрешён только менеджеру.", show_alert=True)
            return
        if not isinstance(callback.message, Message):
            await callback.answer("Сообщение недоступно. Отправьте /admin.", show_alert=True)
            return
        data = callback.data or ""
        notification = None
        try:
            if data == "menu:admin":
                text, keyboard = await list_view(repository, callback.from_user.id)
            elif match := re.fullmatch(r"admin:list:(new|all):([0-9]{1,7})", data):
                text, keyboard = await list_view(repository, callback.from_user.id, match[1], int(match[2]))
            elif match := re.fullmatch(r"admin:order:([0-9]{1,19})", data):
                text, keyboard = await detail_view(repository, callback.from_user.id, int(match[1]))
            elif match := re.fullmatch(r"admin:status:([0-9]{1,19}):([0-4]):([0-4])", data):
                order_id, previous, next_status = map(int, match.groups())
                await repository.admin_set_status(callback.from_user.id, order_id, STATUSES[next_status], STATUSES[previous])
                notification = f"Статус изменён: {STATUSES[next_status]}."
                text, keyboard = await detail_view(repository, callback.from_user.id, order_id)
            else:
                raise AdminError("Кнопка устарела. Откройте /admin заново.")
        except (PermissionError, AdminError) as error:
            await callback.answer(str(error), show_alert=True)
            return
        except sqlite3.Error:
            await callback.answer("Ошибка БД. Откройте карточку заново и проверьте статус.", show_alert=True)
            return
        await callback.answer(notification)
        await callback.message.answer(text, reply_markup=keyboard)

    return router
