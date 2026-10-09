CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    telegram_id INTEGER NOT NULL UNIQUE CHECK (telegram_id > 0),
    platform TEXT NOT NULL DEFAULT 'telegram' CHECK (platform = 'telegram'),
    display_name TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    seed_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    volume_ml INTEGER NOT NULL CHECK (typeof(volume_ml) = 'integer' AND volume_ml > 0),
    price_kopecks INTEGER NOT NULL CHECK (typeof(price_kopecks) = 'integer' AND price_kopecks > 0),
    is_available INTEGER NOT NULL DEFAULT 1 CHECK (is_available IN (0, 1))
);
CREATE TABLE IF NOT EXISTS cart_items (
    user_id INTEGER NOT NULL REFERENCES users(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (typeof(quantity) = 'integer' AND quantity > 0),
    PRIMARY KEY (user_id, product_id)
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    recipient_name TEXT NOT NULL CHECK (length(trim(recipient_name)) > 0),
    total_kopecks INTEGER NOT NULL CHECK (typeof(total_kopecks) = 'integer' AND total_kopecks > 0),
    delivery_method TEXT NOT NULL DEFAULT 'pickup' CHECK (delivery_method = 'pickup'),
    payment_method TEXT NOT NULL DEFAULT 'on_receipt' CHECK (payment_method = 'on_receipt'),
    status TEXT NOT NULL DEFAULT 'Новый'
        CHECK (status IN ('Новый', 'В обработке', 'Готов к выдаче', 'Выдан', 'Отменён')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    checkout_key TEXT NOT NULL UNIQUE CHECK (length(trim(checkout_key)) > 0)
);
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    product_name TEXT NOT NULL,
    volume_ml INTEGER NOT NULL CHECK (typeof(volume_ml) = 'integer' AND volume_ml > 0),
    price_kopecks INTEGER NOT NULL CHECK (typeof(price_kopecks) = 'integer' AND price_kopecks > 0),
    quantity INTEGER NOT NULL CHECK (typeof(quantity) = 'integer' AND quantity > 0),
    UNIQUE (order_id, product_id)
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status, id);
-- Добавляется без удаления таблиц и данных предыдущих этапов.
CREATE TABLE IF NOT EXISTS checkout_drafts (
    checkout_key TEXT PRIMARY KEY NOT NULL,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
    recipient_name TEXT,
    snapshot TEXT,
    CHECK ((recipient_name IS NULL AND snapshot IS NULL)
        OR (recipient_name IS NOT NULL AND snapshot IS NOT NULL))
);
