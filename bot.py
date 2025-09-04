import logging
import os
import sqlite3
import uuid
import datetime
import httpx
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from flask import Flask
from threading import Thread
import asyncio

# --- CONFIG ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "INSERISCI_IL_TUO_TOKEN")
GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", "-1002093792613"))
AFFILIATE_TAG = os.getenv("AMAZON_AFFILIATE_TAG", "prodottipe0c9-21")
ADMIN_USER_ID = 6930429334
DB_FILE = "bot_data.db"
PORT = int(os.environ.get("PORT", 5000))

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
        except Exception as e:
            logging.error(f"Errore expand_url: {e}")
            return url

async def parse_amazon(url):
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(url)
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            logging.error(f"Errore parse_amazon: {e}")
            return "Prodotto Amazon", None, url
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

# --- COMANDI ADMIN ---
async def licenze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# --- START con tastiera ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    keyboard = [["Invia Link Amazon"]]
    if user_id == ADMIN_USER_ID:
        keyboard.insert(0, ["📜 Gestione Licenze"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    await update.message.reply_text("Ciao! Seleziona un'opzione:", reply_markup=reply_markup)

# --- HANDLER TESTO PULSANTI ---
async def handle_button_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "📜 Gestione Licenze":
        if user_id == ADMIN_USER_ID:
            await licenze_command(update, context)
        else:
            await update.message.reply_text("❌ Non hai i permessi.")
    elif "amazon" in text.lower() or "amzn" in text.lower():
        await handle_link(update, context)

# --- HANDLER LINK AMAZON ---
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_license(update):
        return
    url = update.message.text.strip()
    if not any(x in url for x in ["amazon", "amzn.to", "amzn.eu"]):
        await update.message.reply_text("Per favore manda un link Amazon valido 🔗")
        return
    await update.message.reply_text("📦 Caricamento prodotto...")
    url_expanded = await expand_url(url)
    url_affiliate = add_affiliate_tag(url_expanded, AFFILIATE_TAG)
    title, img_url, final_url = await parse_amazon(url_affiliate)
    await update.message.reply_text(f"Prodotto pronto:\n📌 {title}\n💶 Prezzo non inserito\n📲 {final_url}")

# --- FLASK KEEP-ALIVE OPZIONALE ---
app = Flask("")
@app.route("/")
def home(): return "Bot attivo!"
def run_flask(): app.run(host="0.0.0.0", port=PORT)
Thread(target=run_flask).start()

# --- AVVIO BOT CON POLLING ---
bot_app = ApplicationBuilder().token(TOKEN).build()
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("licenze", licenze_command))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_text))

bot_app.run_polling()
