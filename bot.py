import os
import sqlite3
import logging
from datetime import datetime, timezone

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
DB_PATH = os.environ.get("DB_PATH", "kanfet.db")
ALLOWED_IDS_RAW = os.environ.get("ALLOWED_USER_IDS", "").strip()
ALLOWED_IDS = (
    {int(x) for x in ALLOWED_IDS_RAW.split(",") if x.strip().isdigit()}
    if ALLOWED_IDS_RAW
    else None
)

PRODUCT, QTY, PRICE = range(3)

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["➕ Kirim", "➖ Chiqim"], ["📊 Qoldiq", "📜 Tarix"]],
    resize_keyboard=True,
)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            product TEXT NOT NULL,
            qty REAL NOT NULL,
            price REAL DEFAULT 0,
            user_name TEXT,
            created_at TEXT NOT NULL
        )"""
    )
    return conn


def is_allowed(update: Update) -> bool:
    if ALLOWED_IDS is None:
        return True
    return update.effective_user.id in ALLOWED_IDS


async def guard(update: Update) -> bool:
    if not is_allowed(update):
        await update.message.reply_text(
            "Sizda bu botdan foydalanishga ruxsat yo'q. Egasi bilan bog'laning.\n"
            f"Sizning ID: {update.effective_user.id}"
        )
        return False
    return True


def get_products(conn):
    return conn.execute(
        "SELECT product, SUM(CASE WHEN type='kirim' THEN qty ELSE -qty END) AS stock "
        "FROM transactions GROUP BY product ORDER BY stock DESC"
    ).fetchall()


def fmt(n):
    n = round(float(n), 2)
    if n == int(n):
        n = int(n)
    return f"{n:,}".replace(",", " ")


# ---------- /start ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    await update.message.reply_text(
        "Salom! Men kanfet biznesingiz uchun hisob botiman.\n\n"
        "➕ Kirim — tovar kelganda\n"
        "➖ Chiqim — sotilganda\n"
        "📊 Qoldiq — joriy zaxira\n"
        "📜 Tarix — oxirgi amallar\n\n"
        "Bekor qilish uchun /bekor yuboring.",
        reply_markup=MAIN_KEYBOARD,
    )


# ---------- Qoldiq ----------
async def show_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    conn = db()
    rows = get_products(conn)
    conn.close()
    if not rows:
        await update.message.reply_text("Hali mahsulot yo'q. Avval kirim qiling.")
        return
    lines = ["📊 Joriy qoldiq:\n"]
    for product, stock in rows:
        flag = " ⚠️" if stock <= 5 else ""
        lines.append(f"• {product}: {fmt(stock)} dona{flag}")
    await update.message.reply_text("\n".join(lines))


# ---------- Tarix ----------
async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    conn = db()
    rows = conn.execute(
        "SELECT type, product, qty, price, user_name, created_at FROM transactions "
        "ORDER BY id DESC LIMIT 15"
    ).fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Hali birorta tranzaksiya yo'q.")
        return
    lines = ["📜 Oxirgi amallar:\n"]
    for t, product, qty, price, user_name, created_at in rows:
        icon = "🟢" if t == "kirim" else "🟠"
        date = created_at[:10]
        price_part = f" · {fmt(qty * price)} so'm" if price else ""
        lines.append(f"{icon} {date} — {product}: {fmt(qty)} dona{price_part} ({user_name})")
    await update.message.reply_text("\n".join(lines))


# ---------- Kirim / Chiqim suhbati ----------
async def begin_tx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    tx_type = "kirim" if "Kirim" in update.message.text else "chiqim"
    context.user_data["tx_type"] = tx_type

    conn = db()
    rows = get_products(conn)
    conn.close()

    buttons = [
        [InlineKeyboardButton(f"{p} ({fmt(s)} dona)", callback_data=f"prod:{p}")]
        for p, s in rows[:8]
    ]
    buttons.append([InlineKeyboardButton("✏️ Yangi mahsulot", callback_data="prod:__new__")])

    label = "Kirim" if tx_type == "kirim" else "Chiqim"
    await update.message.reply_text(
        f"{label} — qaysi mahsulot?",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return PRODUCT


async def product_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    value = query.data.split("prod:", 1)[1]
    if value == "__new__":
        await query.edit_message_text("Mahsulot nomini yozing:")
        return PRODUCT
    context.user_data["product"] = value
    await query.edit_message_text(f"Mahsulot: {value}\n\nNecha dona?")
    return QTY


async def product_typed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["product"] = update.message.text.strip()
    await update.message.reply_text(f"Mahsulot: {context.user_data['product']}\n\nNecha dona?")
    return QTY


async def qty_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    try:
        qty = float(text)
        if qty <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Iltimos, musbat son yuboring. Masalan: 50")
        return QTY

    context.user_data["qty"] = qty

    if context.user_data["tx_type"] == "chiqim":
        conn = db()
        row = conn.execute(
            "SELECT SUM(CASE WHEN type='kirim' THEN qty ELSE -qty END) FROM transactions WHERE product=?",
            (context.user_data["product"],),
        ).fetchone()
        conn.close()
        current = row[0] or 0
        if qty > current:
            await update.message.reply_text(
                f"⚠️ Diqqat: qoldiq atigi {fmt(current)} dona, siz {fmt(qty)} dona chiqim qilyapsiz."
            )

    price_label = "Tan narxi" if context.user_data["tx_type"] == "kirim" else "Sotish narxi"
    await update.message.reply_text(f"{price_label} (so'm/dona)? Bilmasangiz 0 yuboring.")
    return PRICE


async def price_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    try:
        price = float(text)
        if price < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Iltimos, son yuboring. Masalan: 1500 yoki 0")
        return PRICE

    ud = context.user_data
    conn = db()
    conn.execute(
        "INSERT INTO transactions (type, product, qty, price, user_name, created_at) VALUES (?,?,?,?,?,?)",
        (
            ud["tx_type"],
            ud["product"],
            ud["qty"],
            price,
            update.effective_user.full_name,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT SUM(CASE WHEN type='kirim' THEN qty ELSE -qty END) FROM transactions WHERE product=?",
        (ud["product"],),
    ).fetchone()
    conn.close()
    new_stock = row[0] or 0

    label = "Kirim" if ud["tx_type"] == "kirim" else "Chiqim"
    await update.message.reply_text(
        f"✅ {label} saqlandi: {ud['product']} — {fmt(ud['qty'])} dona\n"
        f"Yangi qoldiq: {fmt(new_stock)} dona",
        reply_markup=MAIN_KEYBOARD,
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Bekor qilindi.", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END


def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN environment variable o'rnatilmagan.")

    db().close()  # jadval mavjudligini ta'minlash

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(➕ Kirim|➖ Chiqim)$"), begin_tx)],
        states={
            PRODUCT: [
                CallbackQueryHandler(product_chosen, pattern="^prod:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, product_typed),
            ],
            QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, qty_entered)],
            PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, price_entered)],
        },
        fallbacks=[CommandHandler("bekor", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.Regex("^📊 Qoldiq$"), show_stock))
    app.add_handler(MessageHandler(filters.Regex("^📜 Tarix$"), show_history))

    log.info("Bot ishga tushdi")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
