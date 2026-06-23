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

PRODUCT, QTY, COST_PRICE, CARGO, SELL_PRICE = range(5)

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["➕ Kirim", "➖ Chiqim"], ["📊 Qoldiq", "📜 Tarix"], ["💰 Foyda hisobi"]],
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
            cost_price REAL DEFAULT 0,
            cargo REAL DEFAULT 0,
            sell_price REAL DEFAULT 0,
            user_name TEXT,
            created_at TEXT NOT NULL
        )"""
    )
    # Eski jadvalga yangi ustunlar qo'shish
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN cost_price REAL DEFAULT 0")
    except:
        pass
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN cargo REAL DEFAULT 0")
    except:
        pass
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN sell_price REAL DEFAULT 0")
    except:
        pass
    conn.commit()
    return conn


def is_allowed(update: Update) -> bool:
    if ALLOWED_IDS is None:
        return True
    return update.effective_user.id in ALLOWED_IDS


async def guard(update: Update) -> bool:
    if not is_allowed(update):
        await update.message.reply_text(
            f"Sizda ruxsat yo'q. ID: {update.effective_user.id}"
        )
        return False
    return True


def get_products(conn):
    return conn.execute(
        "SELECT product, SUM(CASE WHEN type='kirim' THEN qty ELSE -qty END) AS stock "
        "FROM transactions GROUP BY product ORDER BY stock DESC"
    ).fetchall()


def fmt(n):
    n = round(float(n or 0), 0)
    return f"{int(n):,}".replace(",", " ")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    await update.message.reply_text(
        "Salom! Kanfet biznes hisob botiman.\n\n"
        "➕ Kirim — tovar kelganda\n"
        "➖ Chiqim — sotilganda\n"
        "📊 Qoldiq — joriy zaxira\n"
        "📜 Tarix — oxirgi amallar\n"
        "💰 Foyda hisobi — daromad va xarajat\n\n"
        "Bekor qilish: /bekor",
        reply_markup=MAIN_KEYBOARD,
    )


async def show_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    conn = db()
    rows = get_products(conn)
    conn.close()
    if not rows:
        await update.message.reply_text("Hali mahsulot yo'q.")
        return
    lines = ["📊 Joriy qoldiq:\n"]
    for product, stock in rows:
        flag = " ⚠️" if stock <= 5 else ""
        lines.append(f"• {product}: {fmt(stock)} dona{flag}")
    await update.message.reply_text("\n".join(lines))


async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    conn = db()
    rows = conn.execute(
        "SELECT type, product, qty, cost_price, cargo, sell_price, user_name, created_at "
        "FROM transactions ORDER BY id DESC LIMIT 15"
    ).fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Hali tranzaksiya yo'q.")
        return
    lines = ["📜 Oxirgi amallar:\n"]
    for t, product, qty, cost_price, cargo, sell_price, user_name, created_at in rows:
        icon = "🟢" if t == "kirim" else "🟠"
        date = created_at[:10]
        if t == "kirim":
            tannarx = (cost_price + cargo) * qty
            detail = f"kelish: {fmt(cost_price)} + kargo: {fmt(cargo)} = {fmt(tannarx)} so'm"
        else:
            detail = f"sotish: {fmt(sell_price)} so'm/dona, jami: {fmt(sell_price * qty)} so'm"
        lines.append(f"{icon} {date} — {product}: {fmt(qty)} dona\n   {detail} ({user_name})")
    await update.message.reply_text("\n".join(lines))


async def show_profit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    conn = db()
    
    # Umumiy xarajat (kirim)
    kirim = conn.execute(
        "SELECT SUM((cost_price + cargo) * qty) FROM transactions WHERE type='kirim'"
    ).fetchone()[0] or 0
    
    # Umumiy daromad (chiqim)
    chiqim = conn.execute(
        "SELECT SUM(sell_price * qty) FROM transactions WHERE type='chiqim'"
    ).fetchone()[0] or 0
    
    # Mahsulot bo'yicha foyda
    products = conn.execute(
        "SELECT DISTINCT product FROM transactions"
    ).fetchall()
    
    lines = ["💰 Foyda hisobi:\n"]
    lines.append(f"📦 Jami xarajat (tannarx+kargo): {fmt(kirim)} so'm")
    lines.append(f"💵 Jami savdo: {fmt(chiqim)} so'm")
    foyda = chiqim - kirim
    emoji = "✅" if foyda >= 0 else "❌"
    lines.append(f"{emoji} Sof foyda: {fmt(foyda)} so'm\n")
    
    lines.append("📋 Mahsulot bo'yicha:")
    for (product,) in products:
        k = conn.execute(
            "SELECT SUM((cost_price + cargo) * qty) FROM transactions WHERE type='kirim' AND product=?",
            (product,)
        ).fetchone()[0] or 0
        s = conn.execute(
            "SELECT SUM(sell_price * qty) FROM transactions WHERE type='chiqim' AND product=?",
            (product,)
        ).fetchone()[0] or 0
        p = s - k
        e = "✅" if p >= 0 else "❌"
        lines.append(f"{e} {product}: {fmt(p)} so'm")
    
    conn.close()
    await update.message.reply_text("\n".join(lines))


# ---------- Kirim ----------
async def begin_kirim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    context.user_data["tx_type"] = "kirim"
    conn = db()
    rows = get_products(conn)
    conn.close()
    buttons = [
        [InlineKeyboardButton(f"{p} ({fmt(s)} dona)", callback_data=f"prod:{p}")]
        for p, s in rows[:8]
    ]
    buttons.append([InlineKeyboardButton("✏️ Yangi mahsulot", callback_data="prod:__new__")])
    await update.message.reply_text("Qaysi mahsulot kirdi?", reply_markup=InlineKeyboardMarkup(buttons))
    return PRODUCT


# ---------- Chiqim ----------
async def begin_chiqim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    context.user_data["tx_type"] = "chiqim"
    conn = db()
    rows = get_products(conn)
    conn.close()
    buttons = [
        [InlineKeyboardButton(f"{p} ({fmt(s)} dona)", callback_data=f"prod:{p}")]
        for p, s in rows[:8]
    ]
    buttons.append([InlineKeyboardButton("✏️ Yangi mahsulot", callback_data="prod:__new__")])
    await update.message.reply_text("Qaysi mahsulot sotildi?", reply_markup=InlineKeyboardMarkup(buttons))
    return PRODUCT


async def product_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    value = query.data.split("prod:", 1)[1]
    if value == "__new__":
        await query.edit_message_text("Mahsulot nomini yozing:")
        return PRODUCT
    context.user_data["product"] = value
    await query.edit_message_text(f"✅ {value}\n\nNecha dona?")
    return QTY


async def product_typed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["product"] = update.message.text.strip()
    await update.message.reply_text(f"✅ {context.user_data['product']}\n\nNecha dona?")
    return QTY


async def qty_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    try:
        qty = float(text)
        if qty <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Musbat son yuboring. Masalan: 50")
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
            await update.message.reply_text(f"⚠️ Qoldiq: {fmt(current)} dona, siz {fmt(qty)} kiritdingiz.")

        await update.message.reply_text("Sotish narxi (so'm/dona)?")
        return SELL_PRICE
    else:
        await update.message.reply_text("Kelish narxi (so'm/dona)? — tovarning o'z narxi")
        return COST_PRICE


async def cost_price_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    try:
        cost_price = float(text)
        if cost_price < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Son yuboring. Masalan: 5000")
        return COST_PRICE
    context.user_data["cost_price"] = cost_price
    await update.message.reply_text("Kargo narxi (so'm/dona)? — yo'l xarajati. Yo'q bo'lsa 0 yuboring.")
    return CARGO


async def cargo_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    try:
        cargo = float(text)
        if cargo < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Son yuboring. Masalan: 500 yoki 0")
        return CARGO
    context.user_data["cargo"] = cargo

    ud = context.user_data
    tannarx = (ud["cost_price"] + cargo) * ud["qty"]
    conn = db()
    conn.execute(
        "INSERT INTO transactions (type, product, qty, cost_price, cargo, sell_price, user_name, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            "kirim", ud["product"], ud["qty"],
            ud["cost_price"], cargo, 0,
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

    await update.message.reply_text(
        f"✅ Kirim saqlandi!\n"
        f"Mahsulot: {ud['product']}\n"
        f"Miqdor: {fmt(ud['qty'])} dona\n"
        f"Kelish narxi: {fmt(ud['cost_price'])} so'm/dona\n"
        f"Kargo: {fmt(cargo)} so'm/dona\n"
        f"Tannarx jami: {fmt(tannarx)} so'm\n"
        f"Yangi qoldiq: {fmt(new_stock)} dona",
        reply_markup=MAIN_KEYBOARD,
    )
    context.user_data.clear()
    return ConversationHandler.END


async def sell_price_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    try:
        sell_price = float(text)
        if sell_price < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Son yuboring. Masalan: 8000")
        return SELL_PRICE

    ud = context.user_data
    jami = sell_price * ud["qty"]
    conn = db()
    conn.execute(
        "INSERT INTO transactions (type, product, qty, cost_price, cargo, sell_price, user_name, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            "chiqim", ud["product"], ud["qty"],
            0, 0, sell_price,
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

    await update.message.reply_text(
        f"✅ Chiqim saqlandi!\n"
        f"Mahsulot: {ud['product']}\n"
        f"Miqdor: {fmt(ud['qty'])} dona\n"
        f"Sotish narxi: {fmt(sell_price)} so'm/dona\n"
        f"Jami tushum: {fmt(jami)} so'm\n"
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
        raise SystemExit("BOT_TOKEN o'rnatilmagan.")
    db().close()
    app = Application.builder().token(BOT_TOKEN).build()

    kirim_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Kirim$"), begin_kirim)],
        states={
            PRODUCT: [
                CallbackQueryHandler(product_chosen, pattern="^prod:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, product_typed),
            ],
            QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, qty_entered)],
            COST_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, cost_price_entered)],
            CARGO: [MessageHandler(filters.TEXT & ~filters.COMMAND, cargo_entered)],
        },
        fallbacks=[CommandHandler("bekor", cancel)],
    )

    chiqim_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➖ Chiqim$"), begin_chiqim)],
        states={
            PRODUCT: [
                CallbackQueryHandler(product_chosen, pattern="^prod:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, product_typed),
            ],
            QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, qty_entered)],
            SELL_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_price_entered)],
        },
        fallbacks=[CommandHandler("bekor", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(kirim_conv)
    app.add_handler(chiqim_conv)
    app.add_handler(MessageHandler(filters.Regex("^📊 Qoldiq$"), show_stock))
    app.add_handler(MessageHandler(filters.Regex("^📜 Tarix$"), show_history))
    app.add_handler(MessageHandler(filters.Regex("^💰 Foyda hisobi$"), show_profit))

    log.info("Bot ishga tushdi")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
