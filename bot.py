import logging
import os
import sqlite3
import uuid
import datetime
import httpx
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# --- CONFIG ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", "-1000000000"))
ADMIN_USER_ID = 6930429334
DEFAULT_AFFILIATE_TAG = "YOUR_DEFAULT_AFFILIATE_TAG"
DB_FILE = "bot_data.db"

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

# --- FUNZIONI LICENZE ---
def create_license(days_valid=30, admin=False):
    key = str(uuid.uuid4()).split("-")[0].upper()
    expiry = "9999-12-29T23:59:59" if admin else (datetime.datetime.now() + datetime.timedelta(days=days_valid)).isoformat()
    cursor.execute("INSERT INTO licenses (key, expiry, used, admin) VALUES (?, ?, ?, ?)",
                   (key, expiry, 0, int(admin)))
    conn.commit()
    return key, expiry

def list_licenses():
    cursor.execute("SELECT key, expiry, used, admin FROM licenses")
    return cursor.fetchall()

def check_license(user_key):
    cursor.execute("SELECT expiry, used, admin FROM licenses WHERE key=?", (user_key,))
    row = cursor.fetchone()
    if not row:
        return False, False
    expiry, used, is_admin = row
    is_admin = bool(is_admin)
    if not is_admin and (used or datetime.datetime.now() > datetime.datetime.fromisoformat(expiry)):
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

# --- CREA CHIAVE ADMIN SE NON ESISTE ---
cursor.execute("SELECT key FROM licenses WHERE admin=1")
admin_row = cursor.fetchone()
if admin_row:
    admin_key = admin_row[0]
else:
    admin_key, _ = create_license(admin=True)
    print(f"Chiave Admin generata: {admin_key} (scade 29/12/9999)")

# --- AMAZON PARSING ---
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
            return None, None, None
    title_tag = soup.find("span", {"id": "productTitle"})
    title = title_tag.get_text(strip=True) if title_tag else None
    img_tag = soup.find("img", {"id": "landingImage"})
    img_url = img_tag.get("src") if img_tag else None
    return title, img_url, url

def add_affiliate_tag(url, tag):
    if "/dp/" not in url:
        return url
    asin = url.split("/dp/")[1].split("/")[0].split("?")[0]
    return f"https://www.amazon.it/dp/{asin}?tag={tag}"

# --- CHECK LICENZA UTENTE ---
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

# --- /START ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖Benvenuto in Easy Amz Affiliate❗️")
    commands = [
        BotCommand("start", "Avvia il bot"),
        BotCommand("licenze", "Gestione licenze (solo admin)"),
        BotCommand("setaff", "Imposta tuo ID affiliato Amazon"),
        BotCommand("licenza", "Attiva la tua licenza")
    ]
    await context.bot.set_my_commands(commands)

# --- INSERIMENTO LICENZA ---
async def inserisci_licenza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usa: /licenza TUO_CODICE")
        return
    key = context.args[0].upper()
    valid, is_admin = activate_license(user_id, key)
    if valid:
        await update.message.reply_text(f"✅ Licenza attivata con successo! {'(Admin)' if is_admin else ''}")
    else:
        await update.message.reply_text("❌ Licenza non valida o già utilizzata.")

# --- SET AFFILIATE ID ---
async def set_affiliate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if len(context.args) != 1:
        await update.message.reply_text("Usa: /setaff TUO_ID")
        return
    aff_id = context.args[0]
    cursor.execute("INSERT OR REPLACE INTO active_users (user_id, license_key, affiliate_id) VALUES (?, ?, ?)",
                   (user_id, admin_key if user_id==ADMIN_USER_ID else "", aff_id))
    conn.commit()
    await update.message.reply_text(f"✅ ID affiliato impostato a {aff_id}")

# --- GESTIONE LINK AMAZON ---
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_license(update):
        return
    url = update.message.text.strip()
    if not any(x in url for x in ["amazon", "amzn.to", "amzn.eu"]):
        await update.message.reply_text("Per favore invia un link Amazon valido 🔗")
        return

    loading_msg = await update.message.reply_text("📦 Caricamento prodotto...")

    # Recupero ID affiliato utente
    cursor.execute("SELECT affiliate_id FROM active_users WHERE user_id=?", (update.message.from_user.id,))
    aff_row = cursor.fetchone()
    aff_tag = aff_row[0] if aff_row and aff_row[0] else DEFAULT_AFFILIATE_TAG

    url_exp = await expand_url(url)
    url_aff = add_affiliate_tag(url_exp, aff_tag)
    title, img, final_url = await parse_amazon(url_aff)

    if not title or not final_url:
        await update.message.reply_text("❌ Errore caricando prodotto, reinvia il link")
        return

    context.user_data["product"] = {"title": title, "img": img, "url": final_url, "price": "Prezzo non inserito", "ready": True}

    keyboard = [
        [InlineKeyboardButton("💰 Modifica Prezzo", callback_data="modify")],
        [InlineKeyboardButton("✏️ Modifica Titolo", callback_data="edit_title")],
        [InlineKeyboardButton("⏰ Riprogramma", callback_data="reschedule")],
        [InlineKeyboardButton("✅ Pubblica sul canale", callback_data="publish")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    caption = f"📌 {title}\n〰️〰️〰️〰️\n💶 Prezzo non inserito\n〰️〰️〰️〰️\n📲 Acquista su Amazon"

    try:
        if img:
            await context.bot.edit_message_media(chat_id=loading_msg.chat_id, message_id=loading_msg.message_id,
                                                 media=InputMediaPhoto(img, caption=caption), reply_markup=reply_markup)
        else:
            await context.bot.edit_message_text(chat_id=loading_msg.chat_id, message_id=loading_msg.message_id,
                                                text=caption, reply_markup=reply_markup)
    except:
        await update.message.reply_text("Errore aggiornando il prodotto")

# --- CALLBACK BOTTONI AMAZON ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    product = context.user_data.get("product")

    if not product or not product.get("ready"):
        await query.message.reply_text("⏳ Sto ancora caricando i dati del prodotto...")
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

# --- HANDLER PREZZO/TITOLO ---
async def manual_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_price"):
        price = update.message.text.strip()
        context.user_data["product"]["price"] = price
        context.user_data["waiting_price"] = False
        await update.message.reply_text("PREZZO AGGIORNATO ✅\nPuoi ora premere Pubblica ✅")

async def manual_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_title"):
        new_title = update.message.text.strip()
        context.user_data["product"]["title"] = new_title
        context.user_data["waiting_title"] = False
        await update.message.reply_text("TITOLO AGGIORNATO ✅\nPuoi ora premere Pubblica ✅")

# --- AVVIO BOT ---
app = ApplicationBuilder().token(TOKEN).build()

# Comandi
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("setaff", set_affiliate))
app.add_handler(CommandHandler("licenza", inserisci_licenza))

# Messaggi
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

# Callback
app.add_handler(CallbackQueryHandler(button_callback))

# Prezzo/Titolo
app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^\d+.*'), manual_price))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manual_title))

print("Bot avviato...")
app.run_polling()
