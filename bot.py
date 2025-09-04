import logging, os, sqlite3, uuid, datetime, asyncio, httpx
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from flask import Flask
from threading import Thread

# --- CONFIG ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", "-1002093792613"))
ADMIN_USER_ID = 6930429334
AFFILIATE_TAG = os.getenv("AMAZON_AFFILIATE_TAG", "prodottipe0c9-21")
PORT = int(os.environ.get("PORT", 5000))

logging.basicConfig(level=logging.INFO)

# --- DATABASE ---
conn = sqlite3.connect("bot_data.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""CREATE TABLE IF NOT EXISTS licenses (
    key TEXT PRIMARY KEY,
    expiry TEXT,
    used INTEGER DEFAULT 0,
    admin INTEGER DEFAULT 0
)""")
cursor.execute("""CREATE TABLE IF NOT EXISTS active_users (user_id INTEGER PRIMARY KEY, license_key TEXT)""")
conn.commit()

# --- CREA ADMIN SE NON ESISTE ---
cursor.execute("SELECT key FROM licenses WHERE admin=1")
row = cursor.fetchone()
if row:
    ADMIN_KEY = row[0]
else:
    ADMIN_KEY, _ = str(uuid.uuid4()).split("-")[0].upper(), "9999-12-29T23:59:59"
    cursor.execute("INSERT INTO licenses (key, expiry, used, admin) VALUES (?, ?, 0, 1)", (ADMIN_KEY, "9999-12-29T23:59:59"))
    conn.commit()
    print(f"Chiave Admin: {ADMIN_KEY}")

# --- LICENZE ---
def create_license(days=30, admin=False):
    key = str(uuid.uuid4()).split("-")[0].upper()
    expiry = "9999-12-29T23:59:59" if admin else (datetime.datetime.now() + datetime.timedelta(days=days)).isoformat()
    cursor.execute("INSERT INTO licenses (key, expiry, used, admin) VALUES (?, ?, 0, ?)", (key, expiry, int(admin)))
    conn.commit()
    return key, expiry

def activate_license(user_id, key):
    cursor.execute("SELECT expiry, used, admin FROM licenses WHERE key=?", (key,))
    row = cursor.fetchone()
    if not row: return False
    expiry, used, admin = row
    if not admin and (used or datetime.datetime.now() > datetime.datetime.fromisoformat(expiry)): return False
    cursor.execute("INSERT OR REPLACE INTO active_users (user_id, license_key) VALUES (?, ?)", (user_id, key))
    if not admin: cursor.execute("UPDATE licenses SET used=1 WHERE key=?", (key,))
    conn.commit()
    return True

async def check_user_license(update: Update):
    user_id = update.message.from_user.id
    if user_id == ADMIN_USER_ID: return True
    cursor.execute("SELECT license_key FROM active_users WHERE user_id=?", (user_id,))
    if not cursor.fetchone():
        await update.message.reply_text("❌ Devi inserire una licenza valida")
        return False
    return True

# --- AMAZON ---
async def expand_url(url):
    async with httpx.AsyncClient(timeout=10) as client:
        try: r = await client.head(url, follow_redirects=True); return str(r.url)
        except: return url

async def parse_amazon(url):
    async with httpx.AsyncClient(timeout=10) as client:
        try: resp = await client.get(url)
        except: return "Prodotto Amazon", None, url
    soup = BeautifulSoup(resp.text, "html.parser")
    title_tag = soup.find("span", {"id": "productTitle"})
    img_tag = soup.find("img", {"id": "landingImage"})
    title = title_tag.get_text(strip=True) if title_tag else "Prodotto Amazon"
    img = img_tag.get("src") if img_tag and hasattr(img_tag, "get") else None
    return title, img, url

def add_affiliate_tag(url):
    parts = url.split("/")
    if "dp" in parts:
        idx = parts.index("dp")
        if idx+1 < len(parts):
            asin = parts[idx+1].split("?")[0]
            return f"https://www.amazon.it/dp/{asin}?tag={AFFILIATE_TAG}"
    return url

# --- START ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    keyboard = [["Invia Link Amazon"]]
    if user_id == ADMIN_USER_ID: keyboard.insert(0, ["📜 Gestione Licenze"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Ciao! Seleziona un'opzione:", reply_markup=reply_markup)

# --- HANDLER TESTO PULSANTI ---
async def handle_button_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "📜 Gestione Licenze" and user_id == ADMIN_USER_ID:
        await menu_admin_licenses(update, context)
    elif any(x in text.lower() for x in ["amazon", "amzn"]):
        await handle_link(update, context)

# --- LINK AMAZON ---
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_license(update): return
    url = update.message.text.strip()
    if not any(x in url for x in ["amazon", "amzn.to", "amzn.eu"]):
        await update.message.reply_text("Per favore manda un link Amazon valido 🔗")
        return

    loading_msg = await update.message.reply_text("📦 Caricamento prodotto...")
    url_exp = await expand_url(url)
    url_aff = add_affiliate_tag(url_exp)
    title, img, final_url = await parse_amazon(url_aff)
    context.user_data["product"] = {"title": title, "img": img, "url": final_url, "price": "Prezzo non inserito", "ready": True}

    keyboard = [
        [InlineKeyboardButton("💰 Modifica Prezzo", callback_data="modify")],
        [InlineKeyboardButton("✏️ Modifica Titolo", callback_data="edit_title")],
        [InlineKeyboardButton("⏰ Riprogramma", callback_data="reschedule")],
        [InlineKeyboardButton("✅ Pubblica sul canale", callback_data="publish")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    caption = f"📌 {title}\n💶 Prezzo non inserito\n📲 Acquista su Amazon"
    try:
        if img: await context.bot.edit_message_media(chat_id=loading_msg.chat_id, message_id=loading_msg.message_id, media=InputMediaPhoto(img, caption=caption), reply_markup=reply_markup)
        else: await context.bot.edit_message_text(chat_id=loading_msg.chat_id, message_id=loading_msg.message_id, text=caption, reply_markup=reply_markup)
    except: pass

# --- CALLBACK BOTTONI ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    product = context.user_data.get("product")
    user_id = query.from_user.id

    # Modifica prezzo/titolo/pubblica/riprogramma
    if data == "modify": await query.message.reply_text("Scrivi il prezzo manualmente:"); context.user_data["waiting_price"]=True
    elif data == "edit_title": await query.message.reply_text(f"Scrivi il nuovo titolo (originale: {product['title']}):"); context.user_data["waiting_title"]=True
    elif data == "publish": 
        await send_post(product, context); await query.message.reply_text("Prodotto pubblicato ✅")
    elif data == "reschedule": await query.message.reply_text("Scrivi in minuti dopo quanto pubblicare il post"); context.user_data["waiting_schedule"]=True

    # --- ADMIN LICENZE ---
    elif data.startswith("admin_"):
        action, key = data.split("_")[1], "_".join(data.split("_")[2:])
        if action == "renew":
            cursor.execute("UPDATE licenses SET expiry=? WHERE key=?", ((datetime.datetime.now()+datetime.timedelta(days=30)).isoformat(), key))
            conn.commit(); await query.message.reply_text(f"Licenza {key} rinnovata ✅")
        elif action == "delete":
            cursor.execute("DELETE FROM licenses WHERE key=?", (key,)); conn.commit(); await query.message.reply_text(f"Licenza {key} eliminata ❌")
        elif action == "create":
            k,_ = create_license(); await query.message.reply_text(f"Nuova licenza: {k}")

# --- MANUAL PRICE/TITLE/SCHEDULE ---
async def manual_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_price"):
        price = update.message.text.strip()
        context.user_data["product"]["price"] = price
        context.user_data["waiting_price"] = False
        await update.message.reply_text(f"Prezzo aggiornato: {price}")

async def manual_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_title"):
        title = update.message.text.strip()
        context.user_data["product"]["title"] = title
        context.user_data["waiting_title"] = False
        await update.message.reply_text(f"Titolo aggiornato: {title}")

async def manual_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_schedule"):
        try:
            minutes = int(update.message.text.strip())
            product = context.user_data["product"]
            await update.message.reply_text(f"Post programmato tra {minutes} minuti")
            asyncio.create_task(schedule_post(product, context, minutes))
        except: await update.message.reply_text("Inserisci un numero valido")
        context.user_data["waiting_schedule"] = False

async def schedule_post(product, context, minutes):
    await asyncio.sleep(minutes*60)
    await send_post(product, context)

async def send_post(product, context):
    msg = f"📌 <b>{product['title']}</b>\n💶 {product['price']}\n📲 <a href='{product['url']}'>Acquista su Amazon</a>"
    if product["img"]: await context.bot.send_photo(chat_id=GROUP_ID, photo=product["img"], caption=msg, parse_mode="HTML")
    else: await context.bot.send_message(chat_id=GROUP_ID, text=msg, parse_mode="HTML")

# --- MENU ADMIN ---
async def menu_admin_licenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Crea Licenza", callback_data="admin_create")],
        [InlineKeyboardButton("Rinnova Licenza", callback_data="admin_renew_menu")],
        [InlineKeyboardButton("Elimina Licenza", callback_data="admin_delete_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📜 Menu Licenze Admin:", reply_markup=reply_markup)

# --- CALLBACK ADMIN MENU ---
async def admin_callback_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data in ["admin_renew_menu","admin_delete_menu"]:
        cursor.execute("SELECT key FROM licenses")
        keys = cursor.fetchall()
        keyboard = []
        for k in keys:
            k = k[0]; action = "renew" if data=="admin_renew_menu" else "delete"
            keyboard.append([InlineKeyboardButton(f"{k} [{action.upper()}]", callback_data=f"admin_{action}_{k}")])
        await query.message.reply_text("Seleziona licenza:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- BOT SETUP ---
bot_app = ApplicationBuilder().token(TOKEN).build()
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_text))
bot_app.add_handler(CallbackQueryHandler(button_callback))
bot_app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^\d+$'), manual_price))
bot_app.add_handler(MessageHandler(filters.TEXT & filters.TEXT, manual_title))
bot_app.add_handler(MessageHandler(filters.TEXT & filters.TEXT, manual_schedule))

# --- FLASK KEEP ALIVE ---
app = Flask("")
@app.route("/")
def home(): return "Bot attivo"
Thread(target=lambda: app.run(host="0.0.0.0", port=PORT)).start()

# --- RUN ---
bot_app.run_polling()
