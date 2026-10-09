from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from scentory.database.repository import Cart, Product
from scentory.formatting import format_price


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Каталог", callback_data="menu:catalog")],
        [InlineKeyboardButton(text="Корзина", callback_data="menu:cart")],
        [InlineKeyboardButton(text="Мои заказы", callback_data="menu:orders")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="Управление заказами", callback_data="menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def catalog_menu(products: list[Product]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{product.name} · {product.volume_ml} мл · {format_price(product.price_kopecks)}",
                callback_data=f"product:{product.id}",
            )
        ]
        for product in products
    ]
    rows.append([InlineKeyboardButton(text="Главное меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_menu(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Добавить в корзину", callback_data=f"cart:add:{product_id}"
                )
            ],
            [InlineKeyboardButton(text="Корзина", callback_data="menu:cart")],
            [InlineKeyboardButton(text="Назад", callback_data="menu:catalog")],
        ]
    )


def cart_menu(cart: Cart) -> InlineKeyboardMarkup:
    rows = []
    for index, item in enumerate(cart.items, 1):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"− {index}", callback_data=f"cart:dec:{item.product_id}"
                ),
                InlineKeyboardButton(
                    text=f"+ {index}", callback_data=f"cart:inc:{item.product_id}"
                ),
                InlineKeyboardButton(
                    text=f"Удалить {index}", callback_data=f"cart:remove:{item.product_id}"
                ),
            ]
        )
    if cart.can_checkout:
        rows.append([InlineKeyboardButton(text="Оформить заказ", callback_data="cart:checkout")])
    rows.extend(
        [
            [InlineKeyboardButton(text="Каталог", callback_data="menu:catalog")],
            [InlineKeyboardButton(text="Обновить корзину", callback_data="menu:cart")],
            [InlineKeyboardButton(text="Главное меню", callback_data="menu:home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def buttons(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
            for row in rows
        ]
    )
