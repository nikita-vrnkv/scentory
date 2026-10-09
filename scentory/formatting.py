def format_price(kopecks: int) -> str:
    """Форматируем целые копейки без промежуточного float."""
    rubles, remainder = divmod(kopecks, 100)
    amount = f"{rubles:,}".replace(",", " ")
    return f"{amount},{remainder:02d} ₽" if remainder else f"{amount} ₽"


def order_summary(order: dict) -> str:
    lines = [f"Получатель: {order['recipient_name']}", ""]
    for item in order["items"]:
        name = item.get("product_name", item.get("name"))
        lines.append(
            f"{name} · {item['volume_ml']} мл\n"
            f"{item['quantity']} шт. × {format_price(item['price_kopecks'])} = "
            f"{format_price(item['price_kopecks'] * item['quantity'])}"
        )
    lines.extend(
        [
            f"\nИтого: {format_price(order['total_kopecks'])}",
            "Получение: самовывоз из учебного пункта выдачи Scentory.",
            "Расчёт: при получении.",
        ]
    )
    return "\n".join(lines)
