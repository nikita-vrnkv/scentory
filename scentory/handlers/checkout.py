import re
import sqlite3

from aiogram import F, Router
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import CallbackQuery, Message

from scentory.database.orders import CheckoutError, NoPendingCheckout
from scentory.database.repository import Repository
from scentory.formatting import order_summary
from scentory.handlers.cart import cart_text
from scentory.keyboards import buttons, cart_menu


def create_checkout_router() -> Router:
    router = Router(name="checkout")
    router.message.filter(F.chat.type == "private")
    router.callback_query.filter(F.message.chat.type == "private")

    @router.callback_query((F.data == "cart:checkout") | F.data.startswith("checkout:"))
    async def checkout(callback: CallbackQuery, repository: Repository) -> None:
        if not isinstance(callback.message, Message):
            await callback.answer("Сообщение недоступно. Отправьте /start.", show_alert=True)
            return
        data = callback.data or ""
        try:
            if data == "cart:checkout":
                key = await repository.begin_checkout(callback.from_user.id)
                text = "Введите имя или вымышленный псевдоним получателя (1–60 символов). Телефон и адрес не нужны."
                keyboard = buttons([[("Назад в корзину", f"checkout:cancel:{key}")]])
            else:
                match = re.fullmatch(r"checkout:(confirm|cancel):([0-9a-f]{32})", data)
                if not match:
                    raise CheckoutError("Кнопка устарела. Начните оформление из корзины.")
                action, key = match.groups()
                if action == "cancel":
                    await repository.cancel_checkout(callback.from_user.id, key)
                    cart = await repository.get_cart(callback.from_user.id)
                    text, keyboard = cart_text(cart), cart_menu(cart)
                else:
                    order_id = await repository.confirm_checkout(callback.from_user.id, key)
                    text = f"Заказ №{order_id} сохранён. Текущий статус доступен в деталях заказа.\nРасчёт — при получении."
                    keyboard = buttons(
                        [
                            [("Посмотреть заказ", f"order:{order_id}")],
                            [("Мои заказы", "menu:orders")],
                        ]
                    )
        except CheckoutError as error:
            await callback.answer(str(error), show_alert=True)
            return
        except sqlite3.Error:
            await callback.answer(
                "Ошибка БД. Проверьте «Мои заказы» и повторите подтверждение той же кнопкой.",
                show_alert=True,
            )
            return
        await callback.answer()
        await callback.message.answer(text, reply_markup=keyboard)

    @router.message(~F.text.startswith("/"))
    async def recipient_name(message: Message, repository: Repository):
        if message.from_user is None:
            return
        if message.text is None:
            await message.answer("Введите имя текстом. Главное меню: /start.")
            return
        try:
            draft = await repository.prepare_checkout(message.from_user.id, message.text)
        except NoPendingCheckout:
            return UNHANDLED
        except CheckoutError as error:
            await message.answer(str(error))
            return
        except sqlite3.Error:
            await message.answer(
                "Не удалось подготовить заказ. Повторите ввод имени или откройте /start."
            )
            return
        key = draft["checkout_key"]
        await message.answer(
            "Проверьте заказ перед подтверждением:\n\n" + order_summary(draft),
            reply_markup=buttons(
                [
                    [("Подтвердить заказ", f"checkout:confirm:{key}")],
                    [("Назад в корзину", f"checkout:cancel:{key}")],
                ]
            ),
        )

    return router
