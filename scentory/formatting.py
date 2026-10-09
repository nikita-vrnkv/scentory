def format_price(kopecks: int) -> str:
    """Форматируем целые копейки без промежуточного float."""
    rubles, remainder = divmod(kopecks, 100)
    amount = f"{rubles:,}".replace(",", " ")
    return f"{amount},{remainder:02d} ₽" if remainder else f"{amount} ₽"
