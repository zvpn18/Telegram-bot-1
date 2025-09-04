import logging
import requests
import os
import json
import datetime
import uuid
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask
from threading import Thread

# --- CONFIG ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7817602011:AAHioblDdeZNdhUCuNRSqTKjK5PO-LotivI")
GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", "-1002093792613"))
AFFILIATE_TAG = os.getenv("AMAZON_AFFILIATE_TAG", "prodottipe0c9-21")
ADMIN_USER_ID = 6930429334  # <-- Tuo ID Telegram come Admin

LICENSES_FILE = "licenses.json"
ACTIVE_USERS_FILE = "active_users.json"

logging.basicConfig(level=logging.INFO)

# --- Licenze ---
try:
    with open(LICENSES_FILE, "r") as f:
        LICENSES = json.load(f)
except FileNotFoundError:
    LICENSES = {}

try:
    with open(ACTIVE_USERS_FILE, "r") as f:
        ACTIVE_USERS = json.load(f)
except FileNotFoundError:
    ACTIVE_USERS = {}

def save_licenses():
    with open(LICENSES_FILE, "w") as f:
        json.dump(LICENSES, f, indent=4)

def save_active_users():
    with open(ACTIVE_USERS_FILE, "w") as f:
        json.dump(ACTIVE_USERS, f, indent=4)

def create_license(days_valid=30, admin=False):
    key = str(uuid.uuid4()).split("-")[0].upper()
    expiry = (datetime.datetime.now() + datetime.timedelta(days=days_valid)).isoformat()
    if admin:
        expiry = "9999-12-29T23:59:59"
    LICENSES[key] = {"scadenza": expiry, "usata": False, "admin": admin}
    save_licenses()
    return key, expiry

def check_license(user_key):
    if user_key not in LICENSES:
        return False, False
    license_data = LICENSES[user_key]
    is_admin = license_data.get("admin", False)
    if not is_admin:
        if license_data["usata"]:
            return False, False
        if datetime.datetime.now() > datetime.datetime.fromisoformat(license_data["scadenza"]):
            return False, False
    return True, is_admin

def activate_license(user_id, user_key):
    valid, is_admin = check_license(user_key)
    if not valid:
        return False, is_admin
    ACTIVE_USERS[str(user_id)] = user_key
    if not is_admin:
        LICENSES[user_key]["usata"] = True
        save_licenses()
    save_active_users()
    return True, is_admin

# --- Genera chiave admin se non esiste ---
admin_key = None
for k, v in LICENSES.items():
    if v.get("admin", False):
        admin_key = k
        break
if not admin_key:
    admin_key, _ = create_license(admin=True)
    print(f"Chiave Admin generata: {admin_key} (scade 29/12/9999)")

# --- Espande short link Amazon ---
def expand_url(url):
    try:
        session = requests.Session()
        resp = session.head(url, allow_redirects=True, timeout=10)
        return resp.url
    except:
        return url

# --- Aggiunge tag affiliato ---
def add_affiliate_tag(url, tag):
    asin = None
    parts = url.split("/")
    if "dp" in parts:
        idx = parts.index("dp")
        if idx + 1 < len(parts):
            asin = parts[idx + 1].split("?")[0]
    if not asin:
        return url
    short_url = f"https://www.amazon.it/dp/{asin}?tag={tag}"
    return short_url

# --- Parsing Amazon ---
def parse_amazon(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        page = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(page.content, "html.parser")
    except:
        return "Prodotto Amazon", None, None

    title_tag = soup.find("span", {"id": "productTitle"})
    title = title_tag.get_text(strip=True) if title_tag else "Prodotto Amazon"

    img_tag = soup.find("img", {"id": "landingImage"})
    img_url = img_tag.get("src") if img_tag and hasattr(img_tag, 'get') else None

    return title, img_url, url

# --- Controlla licenza prima di usare bot ---
async def check_user_license(update: Update):
    user_id = update.message.from_user.id
    if user_id == ADMIN_USER_ID:
        ACTIVE_USERS[str(user_id)] = admin_key
        save_active_users()
        return True
    if str(user_id) in ACTIVE_USERS:
        return True
    await update.message.reply_text("❌ Devi inserire una licenza valida per usare il bot.")
    return False

# --- Gestione link Amazon ---
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_license(update):
        return
    if context.user_data.get('waiting_price'):
        await manual_price(update, context)
        return

    original_msg = update.message
    url = update.message.text.strip()

    if not ("amazon" in url or "amzn.to" in url or "amzn.eu" in url):
        await original_msg.reply_text("Per favore manda un link Amazon valido 🔗")
        return

    loading_msg = await original_msg.reply_text("📦 Caricamento prodotto...")

    import asyncio
    asyncio.create_task(parse_and_update(context.bot, loading_msg.chat_id, loading_msg.message_id, url, context))

async def parse_and_update(bot, chat_id, msg_id, url, context):
    context.user_data['product_ready'] = False
    url = expand_url(url)
    url = add_affiliate_tag(url, AFFILIATE_TAG)
    title, img_url, final_url = parse_amazon(url)

    context.user_data['product'] = {"title": title, "img": img_url, "url": final_url, "price": "Prezzo non inserito"}
    context.user_data['product_ready'] = True

    keyboard = [
        [InlineKeyboardButton("💰 Modifica Prezzo", callback_data="modify")],
        [InlineKeyboardButton("✏️ Modifica Titolo", callback_data="edit_title")],
        [InlineKeyboardButton("⏰ Riprogramma", callback_data="reschedule")],
        [InlineKeyboardButton("✅ Pubblica sul canale", callback_data="publish")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    caption_text = f"📌 {title}\n〰️〰️〰️〰️\n💶 Prezzo non inserito\n〰️〰️〰️〰️\n📲 Acquista su Amazon"

    try:
        if img_url:
            await bot.edit_message_media(
                chat_id=chat_id,
                message_id=msg_id,
                media=InputMediaPhoto(img_url, caption=caption_text),
                reply_markup=reply_markup
            )
        else:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=caption_text, reply_markup=reply_markup)
    except Exception as e:
        logging.error(f"Error updating message: {e}")

# --- Callback bottoni ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id != ADMIN_USER_ID and str(user_id) not in ACTIVE_USERS:
        await query.message.reply_text("❌ Devi avere una licenza attiva per usare i bottoni.")
        return

    product = context.user_data.get('product')
    if not product or not context.user_data.get('product_ready', False):
        await query.message.reply_text("⏳ Sto ancora caricando i dati del prodotto...")
        return

    if query.data == "modify":
        await query.message.reply_text("Scrivi il prezzo manualmente:")
        context.user_data['waiting_price'] = True

    elif query.data == "edit_title":
        await query.message.reply_text(f"Scrivi il nuovo titolo (originale: {product['title']}):")
        context.user_data['waiting_title'] = True

    elif query.data == "publish":
        msg = f"📌 <b>{product['title']}</b>\n〰️〰️〰️〰️\n💶 {product['price']}\n〰️〰️〰️〰️\n📲 <a href='{product['url']}'>Acquista su Amazon</a>"
        if product['img']:
            await context.bot.send_photo(chat_id=GROUP_ID, photo=product['img'], caption=msg, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=GROUP_ID, text=msg, parse_mode="HTML")
        await query.message.reply_text("Prodotto pubblicato nel canale ✅")

# --- Prezzo e titolo manuale ---
async def manual_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_price'):
        price = update.message.text.strip()
        if 'product' in context.user_data:
            context.user_data['product']['price'] = price
            await update.message.reply_text(
                f"Prezzo aggiornato a: {price}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Pubblica sul canale", callback_data="publish")]])
            )
        context.user_data['waiting_price'] = False

async def manual_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_title'):
        new_title = update.message.text.strip()
        if 'product' in context.user_data:
            context.user_data['product']['title'] = new_title
            await update.message.reply_text(f"Titolo aggiornato a:\n{new_title}")
        context.user_data['waiting_title'] = False

# --- Comando /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id == ADMIN_USER_ID:
        ACTIVE_USERS[str(user_id)] = admin_key
        save_active_users()
        await update.message.reply_text("Accesso Admin attivato automaticamente ✅")
        return
    if str(user_id) in ACTIVE_USERS:
        await update.message.reply_text("Benvenuto! Sei già registrato.")
    else:
        await update.message.reply_text("Benvenuto! Inserisci la tua chiave licenza:")

# --- Inserimento licenza ---
async def license_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id == ADMIN_USER_ID:
        return
    if str(user_id) in ACTIVE_USERS:
        await manual_price(update, context)
        await manual_title(update, context)
        return
    user_key = update.message.text.strip().upper()
    valid, _ = activate_license(user_id, user_key)
    if not valid:
        await update.message.reply_text("Chiave non valida o già usata/scaduta ❌")
        return
    await update.message.reply_text(f"Licenza attivata ✅\nChiave: {user_key}")

# --- Flask keep-alive ---
flask_app = Flask('')

@flask_app.route('/')
def home():
    return "Bot attivo 🚀"

def run_flask():
    flask_app.run(host="0.0.0.0", port=5000)

t = Thread(target=run_flask)
t.start()

# --- Avvio bot ---
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, license_entry))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manual_title))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manual_price))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.run_polling()

if __name__ == "__main__":
    main()
