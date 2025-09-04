import logging
import os
import sqlite3
import uuid
import datetime
import httpx
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from flask import Flask
from threading import Thread
import asyncio

# --- CONFIG ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7817602011:AAHioblDdeZNdhUCuNRSqTKjK5PO-LotivI")
GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", "-1002093792613"))
AFFILIATE_TAG = os.getenv("AMAZON_AFFILIATE_TAG", "prodottipe0c9-21")
ADMIN_USER_ID = 6930429334
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
    license_key TEXT
)
""")
conn.commit()

# --- FUNZIONI LICENZE ---
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

# --- CREA CHIAVE ADMIN SE NON ESISTE ---
cursor.execute("SELECT key FROM licenses WHERE admin=1")
admin_row = cursor.fetchone()
if admin_row:
    admin_key = admin_row[0]
else:
    admin_key, _ = create_license(admin=True)
    print(f"Chiave Admin generata: {admin_key} (scade 29/12/9999)")

# --- FUNZIONI AMAZON ---
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

# --- /LICENZE ---
async def licenze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ Non hai i permessi per gestire le licenze.")
        return
    cursor.execute("SELECT key, expiry, used, admin FROM licenses")
    rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("Nessuna licenza trovata.")
        return
    msg = "🔑 Licenze attuali:\n\n"
    for key, expiry, used, admin_flag in rows:
        status = "Usata" if used else "Disponibile"
        admin_str = " (Admin)" if admin_flag else ""
        msg += f"{key} - Scadenza: {expiry} - {status}{admin_str}\n"
    await update.message.reply_text(msg)

# --- GESTIONE LINK AMAZON ---
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_license(update):
        return
    if context.user_data.get("waiting_price"):
        await manual_price(update, context)
        return
    if context.user_data.get("waiting_title"):
        await manual_title(update, context)
        return

    url = update.message.text.strip()
    if not any(x in url for x in ["amazon", "amzn.to", "amzn.eu"]):
        await update.message.reply_text("Per favore manda un link Amazon valido 🔗")
        return

    # Manda subito il messaggio di caricamento
    loading_msg = await update.message.reply_text("📦 Caricamento prodotto...")

    # Parsing asincrono
    try:
        url_expanded = await expand_url(url)
        url_affiliate = add_affiliate_tag(url_expanded, AFFILIATE_TAG)
        title, img_url, final_url = await parse_amazon(url_affiliate)
    except Exception as e:
        logging.error(f"Errore parsing: {e}")
        await update.message.reply_text("❌ Errore caricando prodotto")
        return

    context.user_data["product"] = {"title": title, "img": img_url, "url": final_url, "price": "Prezzo non inserito"}
    context.user_data["product_ready"] = True

    keyboard = [
        [InlineKeyboardButton("💰 Modifica Prezzo", callback_data="modify")],
        [InlineKeyboardButton("✏️ Modifica Titolo", callback_data="edit_title")],
        [InlineKeyboardButton("⏰ Riprogramma", callback_data="reschedule")],
        [InlineKeyboardButton("✅ Pubblica sul canale", callback_data="publish")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    caption = f"📌 {title}\n〰️〰️〰️〰️\n💶 Prezzo non inserito\n〰️〰️〰️〰️\n📲 Acquista su Amazon"

    try:
        if img_url:
            await context.bot.edit_message_media(chat_id=loading_msg.chat_id, message_id=loading_msg.message_id, media=InputMediaPhoto(img_url, caption=caption), reply_markup=reply_markup)
        else:
            await context.bot.edit_message_text(chat_id=loading_msg.chat_id, message_id=loading_msg.message_id, text=caption, reply_markup=reply_markup)
    except Exception as e:
        logging.error(f"Errore aggiornando messaggio: {e}")

# --- CALLBACK BOTTONI ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id != ADMIN_USER_ID:
        cursor.execute("SELECT license_key FROM active_users WHERE user_id=?", (user_id,))
        if not cursor.fetchone():
            await query.message.reply_text("❌ Devi avere una licenza attiva per usare i bottoni.")
            return

    product = context.user_data.get("product")
    if not product or not context.user_data.get("product_ready", False):
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
    elif query.data == "reschedule":
        await query.message.reply_text("⚠️ Funzione Riprogramma da implementare secondo minuti scelti.")

# --- HANDLER MANUALI ---
async def manual_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_price"):
        price = update.message.text.strip()
        context.user_data["product"]["price"] = price
        await update.message.reply_text(f"Prezzo aggiornato a: {price}")
        context.user_data["waiting_price"] = False

async def manual_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_title"):
        new_title = update.message.text.strip()
        context.user_data["product"]["title"] = new_title
        await update.message.reply_text(f"Titolo aggiornato a: {new_title}")
        context.user_data["waiting_title"] = False

# --- /START ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ciao! Inviami un link Amazon e potrai modificare il prezzo prima di pubblicarlo 🚀")

# --- SERVER FLASK KEEP-
