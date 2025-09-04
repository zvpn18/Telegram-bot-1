import os
import sqlite3
import uuid
import datetime
import logging
import httpx
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from aiohttp import web

# --- CONFIG ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7817602011:AAHioblDdeZNdhUCuNRSqTKjK5PO-LotivI")
GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", "-1002093792613"))
ADMIN_USER_ID = 6930429334
DB_FILE = "bot_data.db"
PORT = int(os.getenv("PORT", 8080))

logging.basicConfig(level=logging.INFO)

# --- DATABASE ---
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS licenses (
    key TEXT PRIMARY KEY,
    expiry TEXT,
    used INTEGER DEFAULT 0,
    admin INTEGER DEFAULT 0
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS active_users (
    user_id INTEGER PRIMARY KEY,
    license_key TEXT,
    affiliate_id TEXT
)
""")
conn.commit()

# --- LICENZE ---
def create_license(days_valid=30, admin=False):
    key = str(uuid.uuid4()).split("-")[0].upper()
    expiry = "9999-12-29T23:59:59" if admin else (datetime.datetime.now() + datetime.timedelta(days=days_valid)).isoformat()
    cursor.execute("INSERT INTO licenses (key, expiry, used, admin) VALUES (?, ?, ?, ?)", (key, expiry, 0, int(admin)))
    conn.commit()
    return key, expiry

def check_license(user_key):
    cursor.execute("SELECT expiry, used, admin FROM licenses WHERE key=?", (user_key,))
    row = cursor.fetchone()
    if not row:
        return False, False
    expiry, used, is_admin = row
    is_admin = bool(is_admin)
    if not is_admin:
        if used or datetime.datetime.now() > datetime.datetime.fromisoformat(expiry):
            return False, False
    return True, is_admin

def activate_license(user_id, user_key):
    valid, is_admin = check_license(user_key)
    if not valid:
        return False, is_admin
    cursor.execute("INSERT OR REPLACE INTO active_users (user_id, license_key) VALUES (?, ?)", (user_id, user_key))
    if not is_admin:
        cursor.execute("UPDATE licenses SET used=1 WHERE key=?", (user_key,))
    conn.commit()
    return True, is_admin

# --- ADMIN KEY ---
cursor.execute("SELECT key FROM licenses WHERE admin=1")
admin_row = cursor.fetchone()
if admin_row:
    admin_key = admin_row[0]
else:
    admin_key, _ = create_license(admin=True)
    print(f"Chiave Admin generata: {admin_key} (scade 29/12/9999)")

# --- AMAZON ---
async def expand_url(url):
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.head(url, follow_redirects=True)
            return str(resp.url)
        except:
            return url

async def parse_amazon(url):
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(url)
            soup = BeautifulSoup(resp.text, "html.parser")
        except:
            return "Prodotto Amazon", None, None
    title_tag = soup.find("span", {"id": "productTitle"})
    title = title_tag.get_text(strip=True) if title_tag else "Prodotto Amazon"
    img_tag = soup.find("img", {"id": "landingImage"})
    img_url = img_tag.get("src") if img_tag and hasattr(img_tag, 'get') else None
    return title, img_url, url

def add_affiliate_tag(url, tag):
    parts = url.split("/")
    asin = None
    if "dp" in parts:
        idx = parts.index("dp")
        if idx + 1 < len(parts):
            asin = parts[idx+1].split("?")[0]
    if not asin:
        return url
    return f"https://www.amazon.it/dp/{asin}?tag={tag}"

# --- CHECK LICENZA ---
async def check_user_license(update: Update):
    user_id = update.message.from_user.id
    if user_id == ADMIN_USER_ID:
        activate_license(user_id, admin_key)
        return True
    cursor.execute("SELECT license_key FROM active_users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    if not row:
        await update.message.reply_text("❌ Devi inserire una licenza valida per usare il bot.")
        return False
    return True

# --- START ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Gestione Licenze", callback_data="admin_menu")],
        [InlineKeyboardButton("Imposta ID Affiliato", callback_data="set_affiliate")]
    ]
    await update.message.reply_text("🤖Benvenuto in Easy Amz Affiliate❗️", reply_markup=InlineKeyboardMarkup(keyboard))

# --- LINK AMAZON ---
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_license(update):
        return
    url = update.message.text.strip()
    if not any(x in url for x in ["amazon", "amzn.to", "amzn.eu"]):
        await update.message.reply_text("Per favore manda un link Amazon valido 🔗")
        return
    loading_msg = await update.message.reply_text("📦 Caricamento prodotto...")
    try:
        url_expanded = await expand_url(url)
        cursor.execute("SELECT affiliate_id FROM active_users WHERE user_id=?", (update.message.from_user.id,))
        aff_row = cursor.fetchone()
        tag = aff_row[0] if aff_row and aff_row[0] else "prodottipe0c9-21"
        url_affiliate = add_affiliate_tag(url_expanded, tag)
        title, img_url, final_url = await parse_amazon(url_affiliate)
    except:
        await update.message.reply_text("❌ Errore caricando prodotto. Reinvia il link.")
        return

    context.user_data["product"] = {"title": title, "img": img_url, "url": final_url, "price": "Prezzo non inserito"}
    context.user_data["product_ready"] = True

    keyboard = [
        [InlineKeyboardButton("💰 Modifica Prezzo", callback_data="modify")],
        [InlineKeyboardButton("✏️ Modifica Titolo", callback_data="edit_title")],
        [InlineKeyboardButton("⏰ Riprogramma", callback_data="reschedule")],
        [InlineKeyboardButton("✅ Pubblica sul canale", callback_data="publish")]
    ]
    caption = f"📌 {title}\n〰️〰️〰️〰️\n💶 Prezzo non inserito\n〰️〰️〰️〰️\n📲 Acquista su Amazon"
    try:
        if img_url:
            await context.bot.edit_message_media(chat_id=loading_msg.chat_id, message_id=loading_msg.message_id, media=InputMediaPhoto(img_url, caption=caption), reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await context.bot.edit_message_text(chat_id=loading_msg.chat_id, message_id=loading_msg.message_id, text=caption, reply_markup=InlineKeyboardMarkup(keyboard))
    except:
        await update.message.reply_text("Errore nel caricamento del prodotto. Reinvia il link.")

# --- CALLBACK ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    product = context.user_data.get("product")

    if query.data == "admin_menu" and user_id == ADMIN_USER_ID:
        keyboard = [
            [InlineKeyboardButton("Crea Licenza", callback_data="create_license")],
            [InlineKeyboardButton("Rinnova Licenza", callback_data="renew_license")],
            [InlineKeyboardButton("Elimina Licenza", callback_data="delete_license")],
            [InlineKeyboardButton("Lista Licenze", callback_data="list_license")]
        ]
        await query.message.reply_text("📂 Menu Gestione Licenze:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if query.data == "set_affiliate":
        await query.message.reply_text("Inserisci il tuo ID affiliato Amazon:")
        context.user_data["waiting_affiliate"] = True
        return

    if not product:
        await query.message.reply_text("⏳ Nessun prodotto caricato")
        return

    if query.data == "modify":
        await query.message.reply_text("Scrivi il prezzo manualmente:")
        context.user_data["waiting_price"] = True
    elif query.data == "edit_title":
        await query.message.reply_text(f"Scrivi il nuovo titolo (originale: {product['title']}):")
        context.user_data["waiting_title"] = True
    elif query.data == "publish":
        msg = f"📌 <b>{product['title']}</b>\n〰️〰️〰️〰️\n💶 {product['price']}\n〰️〰️〰️〰️\n📲 <a href='{product['url']}'>Acquista su Amazon</a>"
        if product["img"]:
            await context.bot.send_photo(chat_id=GROUP_ID, photo=product["img"], caption=msg, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=GROUP_ID, text=msg, parse_mode="HTML")
        await query.message.reply_text("Prodotto pubblicato nel canale ✅")
    elif query.data == "reschedule":
        await query.message.reply_text("⚠️ Funzione Riprogramma da implementare")

# --- MANUAL ---
async def manual_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_price"):
        price = update.message.text.strip()
        context.user_data["product"]["price"] = price
        keyboard = [[InlineKeyboardButton("✅ Pubblica sul canale", callback_data="publish")]]
        await update.message.reply_text("PREZZO AGGIORNATO ✅", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["waiting_price"] = False

async def manual_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_title"):
        new_title = update.message.text.strip()
        context.user_data["product"]["title"] = new_title
        await update.message.reply_text("TITOLO AGGIORNATO ✅")
        context.user_data["waiting_title"] = False

async def manual_affiliate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_affiliate"):
        aff_id = update.message.text.strip()
        cursor.execute("UPDATE active_users SET affiliate_id=? WHERE user_id=?", (aff_id, update.message.from_user.id))
        conn.commit()
        await update.message.reply_text(f"ID affiliato impostato a: {aff_id}")
        context.user_data["waiting_affiliate"] = False

# --- MAIN ---
app = Application.builder().token(TOKEN).build()
app.bot.set_my_commands([BotCommand("start", "Avvia il bot")])
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_link))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manual_price))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manual_title))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manual_affiliate))
app.add_handler(CallbackQueryHandler(button_callback))

# --- RUN WEBHOOK PER RENDER ---
async def handle(request):
    body = await request.text()
    update = Update.de_json(body, app.bot)
    await app.update_queue.put(update)
    return web.Response(text="OK")

web_app = web.Application()
web_app.router.add_post(f"/{TOKEN}", handle)

async def start_webhook():
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Bot in esecuzione su port {PORT}")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(start_webhook())
