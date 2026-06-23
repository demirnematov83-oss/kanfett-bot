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

# Conversation states
PRODUCT, QTY, COST_PRICE, CARGO, SELL_PRICE = range(5)
DEBT_NAME, DEBT_PRODUCT, DEBT_QTY, DEBT_PRICE, DEBT_DATE = range(5, 10)
DEBT_PAY_SELECT, DEBT_PAY_AMOUNT = range(10, 12)

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["➕ Kirim", "➖ Chiqim"],
        ["📊 Qoldiq", "📜 Tarix"],
        ["💰 Foyda hisobi", "🤝 Qarzlar"],
    ],
    resize_keyboard=True,
)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        product TEXT NOT NULL,
        qty REAL NOT NULL,
        cost_price REAL DEFAULT 0,
        cargo REAL DEFAULT 0,
        sell_price REAL DEFAULT 0,
        user_name TEXT,
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS debts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_name TEXT NOT NULL,
        product TEXT NOT NULL,
        qty REAL NOT NULL,
        sell_price REAL NOT NULL,
        total REAL NOT NULL,
        paid REAL DEFAULT 0,
        due_date TEXT,
        status TEXT DEFAULT 'active',
        user_name TEXT,
        created_at TEXT NOT NULL
    )""")
    for col in ["cost_price", "cargo", "sell_price"]:
        try:
            conn.execute(f"ALTER TABLE transactions ADD COLUMN {col} REAL DEFAULT 0")
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
        await update.message.reply_text(f"Ruxsat yo'q. ID: {update.effective_user.id}")
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


# ── /start ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    await update.message.reply_text(
        "Salom! Kanfet biznes hisob botiman.\n\n"
        "➕ Kirim — tovar kelganda\n"
        "➖ Chiqim — naqt sotilganda\n"
        "📊 Qoldiq — joriy zaxira\n"
        "📜 Tarix — oxirgi amallar\n"
        "💰 Foyda hisobi — daromad va xarajat\n"
        "🤝 Qarzlar — qarzga berilgan tovarlar\n\n"
        "Bekor qilish: /bekor",
        reply_markup=MAIN_KEYBOARD,
    )


# ── Qoldiq ──────────────────────────────────────────────
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


# ── Tarix ────────────────────────────────────────────────
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


# ── Foyda ────────────────────────────────────────────────
async def show_profit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    conn = db()
    kirim = conn.execute("SELECT SUM((cost_price + cargo) * qty) FROM transactions WHERE type='kirim'").fetchone()[0] or 0
    chiqim = conn.execute("SELECT SUM(sell_price * qty) FROM transactions WHERE type='chiqim'").fetchone()[0] or 0
    qarz_tushum = conn.execute("SELECT SUM(paid) FROM debts").fetchone()[0] or 0
    products = conn.execute("SELECT DISTINCT product FROM transactions").fetchall()

    lines = ["💰 Foyda hisobi:\n"]
    lines.append(f"📦 Jami xarajat (tannarx+kargo): {fmt(kirim)} so'm")
    lines.append(f"💵 Naqt savdo: {fmt(chiqim)} so'm")
    lines.append(f"🤝 Qarzdan tushgan: {fmt(qarz_tushum)} so'm")
    foyda = chiqim + qarz_tushum - kirim
    emoji = "✅" if foyda >= 0 else "❌"
    lines.append(f"{emoji} Sof foyda: {fmt(foyda)} so'm\n")
    lines.append("📋 Mahsulot bo'yicha:")
    for (product,) in products:
        k = conn.execute("SELECT SUM((cost_price + cargo) * qty) FROM transactions WHERE type='kirim' AND product=?", (product,)).fetchone()[0] or 0
        s = conn.execute("SELECT SUM(sell_price * qty) FROM transactions WHERE type='chiqim' AND product=?", (product,)).fetchone()[0] or 0
        p = s - k
        e = "✅" if p >= 0 else "❌"
        lines.append(f"{e} {product}: {fmt(p)} so'm")
    conn.close()
    await update.message.reply_text("\n".join(lines))


# ── Qarzlar menyusi ──────────────────────────────────────
async def show_debts_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Qarzga berish", callback_data="debt:new")],
        [InlineKeyboardButton("✅ Qarz qabul qilish", callback_data="debt:pay")],
        [InlineKeyboardButton("📋 Barcha qarzlar", callback_data="debt:list")],
    ])
    await update.message.reply_text("🤝 Qarz bo'limi:", reply_markup=keyboard)


async def debt_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split("debt:")[1]

    if action == "list":
        conn = db()
        rows = conn.execute(
            "SELECT id, client_name, product, qty, total, paid, due_date, status FROM debts ORDER BY id DESC"
        ).fetchall()
        conn.close()
        if not rows:
            await query.edit_message_text("Hali qarz yo'q.")
            return
        lines = ["📋 Qarzlar ro'yxati:\n"]
        for id, name, product, qty, total, paid, due_date, status in rows:
            qoldiq = total - paid
            if status == "closed":
                lines.append(f"✅ {name} — {product} ({fmt(qty)} dona)\n   To'liq to'landi: {fmt(total)} so'm")
            else:
                date_str = f", muddat: {due_date}" if due_date else ""
                lines.append(f"🔴 {name} — {product} ({fmt(qty)} dona)\n   Jami: {fmt(total)} so'm | To'landi: {fmt(paid)} so'm | Qoldiq: {fmt(qoldiq)} so'm{date_str}")
        await query.edit_message_text("\n".join(lines))

    elif action == "new":
        await query.edit_message_text("Mijozning ismi va familiyasini yozing:")
        context.user_data["debt_action"] = "new"
        return

    elif action == "pay":
        conn = db()
        rows = conn.execute(
            "SELECT id, client_name, total, paid FROM debts WHERE status='active' ORDER BY id DESC"
        ).fetchall()
        conn.close()
        if not rows:
            await query.edit_message_text("Faol qarz yo'q.")
            return
        buttons = [
            [InlineKeyboardButton(
                f"{name} — qoldiq: {fmt(total - paid)} so'm",
                callback_data=f"pay:{id}"
            )]
            for id, name, total, paid in rows
        ]
        await query.edit_message_text("Qaysi qarzni to'ladi?", reply_markup=InlineKeyboardMarkup(buttons))


async def pay_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    debt_id = query.data.split("pay:")[1]
    context.user_data["paying_debt_id"] = debt_id
    conn = db()
    row = conn.execute("SELECT client_name, total, paid FROM debts WHERE id=?", (debt_id,)).fetchone()
    conn.close()
    name, total, paid = row
    qoldiq = total - paid
    await query.edit_message_text(
        f"👤 {name}\nQoldiq qarz: {fmt(qoldiq)} so'm\n\nQancha to'ladi? (to'liq to'lasa {fmt(qoldiq)} yozing)"
    )
    context.user_data["debt_action"] = "paying"


async def debt_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.get("debt_action")

    if action == "paying":
        text = update.message.text.strip().replace(",", "").replace(" ", "")
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("Son yuboring.")
            return
        debt_id = context.user_data.get("paying_debt_id")
        conn = db()
        row = conn.execute("SELECT client_name, total, paid FROM debts WHERE id=?", (debt_id,)).fetchone()
        name, total, paid = row
        new_paid = paid + amount
        if new_paid >= total:
            conn.execute("UPDATE debts SET paid=?, status='closed' WHERE id=?", (total, debt_id))
            msg = f"✅ {name} ning qarzi to'liq yopildi!\nJami: {fmt(total)} so'm"
        else:
            conn.execute("UPDATE debts SET paid=? WHERE id=?", (new_paid, debt_id))
            msg = f"✅ {fmt(amount)} so'm qabul qilindi.\n{name} ning qolgan qarzi: {fmt(total - new_paid)} so'm"
        conn.commit()
        conn.close()
        context.user_data.clear()
        await update.message.reply_text(msg, reply_markup=MAIN_KEYBOARD)
        return

    if action == "new":
        context.user_data["debt_client"] = update.message.text.strip()
        conn = db()
        rows = get_products(conn)
        conn.close()
        buttons = [
            [InlineKeyboardButton(f"{p} ({fmt(s)} dona)", callback_data=f"dprod:{p}")]
            for p, s in rows[:8]
        ]
        buttons.append([InlineKeyboardButton("✏️ Yangi mahsulot", callback_data="dprod:__new__")])
        await update.message.reply_text(
            f"👤 {context.user_data['debt_client']}\n\nQaysi mahsulot?",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        context.user_data["debt_action"] = "product"
        return

    if action == "dproduct_new":
        context.user_data["debt_product"] = update.message.text.strip()
        await update.message.reply_text("Necha dona?")
        context.user_data["debt_action"] = "qty"
        return

    if action == "qty":
        try:
            qty = float(update.message.text.strip())
            if qty <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("Musbat son yuboring.")
            return
        context.user_data["debt_qty"] = qty
        await update.message.reply_text("Sotish narxi (so'm/dona)?")
        context.user_data["debt_action"] = "price"
        return

    if action == "price":
        try:
            price = float(update.message.text.strip().replace(",", "").replace(" ", ""))
            if price <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("Son yuboring.")
            return
        context.user_data["debt_price"] = price
        total = price * context.user_data["debt_qty"]
        context.user_data["debt_total"] = total
        await update.message.reply_text(
            f"Jami summa: {fmt(total)} so'm\n\nQaytarish sanasini yozing (masalan: 2026-07-15)\nYoki /skip bosing"
        )
        context.user_data["debt_action"] = "date"
        return

    if action == "date":
        date_text = update.message.text.strip()
        context.user_data["debt_date"] = date_text
        await save_debt(update, context)
        return


async def debt_product_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    value = query.data.split("dprod:")[1]
    if value == "__new__":
        await query.edit_message_text("Mahsulot nomini yozing:")
        context.user_data["debt_action"] = "dproduct_new"
        return
    context.user_data["debt_product"] = value
    await query.edit_message_text(f"✅ {value}\n\nNecha dona?")
    context.user_data["debt_action"] = "qty"


async def skip_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["debt_date"] = None
    await save_debt(update, context)


async def save_debt(update, context):
    ud = context.user_data
    conn = db()
    conn.execute(
        "INSERT INTO debts (client_name, product, qty, sell_price, total, paid, due_date, status, user_name, created_at) VALUES (?,?,?,?,?,0,?,?,?,?)",
        (
            ud["debt_client"], ud["debt_product"], ud["debt_qty"],
            ud["debt_price"], ud["debt_total"],
            ud.get("debt_date"), "active",
            update.effective_user.full_name,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.execute(
        "INSERT INTO transactions (type, product, qty, cost_price, cargo, sell_price, user_name, created_at) VALUES (?,?,?,0,0,?,?,?)",
        ("chiqim", ud["debt_product"], ud["debt_qty"], ud["debt_price"],
         update.effective_user.full_name, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()
    date_str = f"\nMuddat: {ud.get('debt_date')}" if ud.get("debt_date") else ""
    await update.message.reply_text(
        f"✅ Qarz kiritildi!\n"
        f"👤 Mijoz: {ud['debt_client']}\n"
        f"📦 Mahsulot: {ud['debt_product']} — {fmt(ud['debt_qty'])} dona\n"
        f"💰 Jami: {fmt(ud['debt_total'])} so'm{date_str}",
        reply_markup=MAIN_KEYBOARD,
    )
    context.user_data.clear()


# ── Kirim ────────────────────────────────────────────────
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
        await update.message.reply_text("Musbat son yuboring.")
        return QTY
    context.user_data["qty"] = qty
    if context.user_data["tx_type"] == "chiqim":
        await update.message.reply_text("Sotish narxi (so'm/dona)?")
        return SELL_PRICE
    else:
        await update.message.reply_text("Kelish narxi (so'm/dona)?")
        return COST_PRICE


async def cost_price_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cost_price = float(update.message.text.strip().replace(",", "."))
        if cost_price < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Son yuboring.")
        return COST_PRICE
    context.user_data["cost_price"] = cost_price
    await update.message.reply_text("Kargo narxi (so'm/dona)? Yo'q bo'lsa 0 yuboring.")
    return CARGO


async def cargo_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cargo = float(update.message.text.strip().replace(",", "."))
        if cargo < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Son yuboring.")
        return CARGO
    ud = context.user_data
    tannarx = (ud["cost_price"] + cargo) * ud["qty"]
    conn = db()
    conn.execute(
        "INSERT INTO transactions (type, product, qty, cost_price, cargo, sell_price, user_name, created_at) VALUES (?,?,?,?,?,0,?,?)",
        ("kirim", ud["product"], ud["qty"], ud["cost_price"], cargo,
         update.effective_user.full_name, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT SUM(CASE WHEN type='kirim' THEN qty ELSE -qty END) FROM transactions WHERE product=?",
        (ud["product"],),
    ).fetchone()
    conn.close()
    await update.message.reply_text(
        f"✅ Kirim saqlandi!\n"
        f"📦 {ud['product']}: {fmt(ud['qty'])} dona\n"
        f"Kelish: {fmt(ud['cost_price'])} + Kargo: {fmt(cargo)} = {fmt(ud['cost_price'] + cargo)} so'm/dona\n"
        f"Tannarx jami: {fmt(tannarx)} so'm\n"
        f"Yangi qoldiq: {fmt(row[0] or 0)} dona",
        reply_markup=MAIN_KEYBOARD,
    )
    context.user_data.clear()
    return ConversationHandler.END


async def sell_price_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sell_price = float(update.message.text.strip().replace(",", "."))
        if sell_price < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Son yuboring.")
        return SELL_PRICE
    ud = context.user_data
    conn = db()
    conn.execute(
        "INSERT INTO transactions (type, product, qty, cost_price, cargo, sell_price, user_name, created_at) VALUES (?,?,?,0,0,?,?,?)",
        ("chiqim", ud["product"], ud["qty"], sell_price,
         update.effective_user.full_name, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT SUM(CASE WHEN type='kirim' THEN qty ELSE -qty END) FROM transactions WHERE product=?",
        (ud["product"],),
    ).fetchone()
    conn.close()
    await update.message.reply_text(
        f"✅ Chiqim saqlandi!\n"
        f"📦 {ud['product']}: {fmt(ud['qty'])} dona\n"
        f"Sotish: {fmt(sell_price)} so'm/dona\n"
        f"Jami tushum: {fmt(sell_price * ud['qty'])} so'm\n"
        f"Yangi qoldiq: {fmt(row[0] or 0)} dona",
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
    app.add_handler(CommandHandler("skip", skip_date))
    app.add_handler(CommandHandler("bekor", cancel))
    app.add_handler(kirim_conv)
    app.add_handler(chiqim_conv)
    app.add_handler(MessageHandler(filters.Regex("^📊 Qoldiq$"), show_stock))
    app.add_handler(MessageHandler(filters.Regex("^📜 Tarix$"), show_history))
    app.add_handler(MessageHandler(filters.Regex("^💰 Foyda hisobi$"), show_profit))
    app.add_handler(MessageHandler(filters.Regex("^🤝 Qarzlar$"), show_debts_menu))
    app.add_handler(CallbackQueryHandler(debt_menu_handler, pattern="^debt:"))
    app.add_handler(CallbackQueryHandler(pay_selected, pattern="^pay:"))
    app.add_handler(CallbackQueryHandler(debt_product_handler, pattern="^dprod:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, debt_text_handler))

    log.info("Bot ishga tushdi")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
