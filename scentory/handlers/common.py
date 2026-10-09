import logging
import sqlite3

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from scentory.config import Settings
from scentory.database.repository import Repository
from scentory.keyboards import main_menu


def create_router() -> Router:
    router = Router(name="common")
    router.message.filter(F.chat.type == "private")
    router.callback_query.filter(F.message.chat.type == "private")

    @router.message(CommandStart())
    async def start(message: Message, settings: Settings, repository: Repository) -> None:
        if message.from_user is None:
            return
        try:
            await repository.register_user(message.from_user.id)
            await repository.cancel_checkout(message.from_user.id)
        except sqlite3.Error:
            logging.getLogger("scentory").error("Не удалось сохранить пользователя в БД.")
            await message.answer("Не удалось открыть магазин. Попробуйте /start позже.")
            return
        await message.answer(
            "Добро пожаловать в Scentory!\n"
            "Учебный магазин парфюмерии. Выберите раздел в меню.\n"
            "Самовывоз из учебного пункта выдачи Scentory, расчёт при получении.",
            reply_markup=main_menu(settings.is_admin(message.from_user.id)),
        )

    @router.message(Command("myid"))
    async def myid(message: Message) -> None:
        if message.from_user is not None:
            await message.answer(f"Ваш Telegram ID: {message.from_user.id}")

    @router.callback_query(F.data == "menu:home")
    async def home(callback: CallbackQuery, settings: Settings) -> None:
        await callback.answer()
        if isinstance(callback.message, Message):
            await callback.message.answer("Scentory — главное меню", reply_markup=main_menu(settings.is_admin(callback.from_user.id)))

    @router.callback_query()
    async def outdated_button(callback: CallbackQuery) -> None:
        await callback.answer("Кнопка устарела. Откройте меню командой /start.", show_alert=True)

    @router.message()
    async def unknown_message(message: Message) -> None:
        await message.answer("Откройте главное меню: /start. Узнать свой Telegram ID: /myid.")

    return router
