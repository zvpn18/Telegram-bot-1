import logging, os, sqlite3, uuid, datetime, asyncio, httpx
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# --- CONFIG ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", "-1002093792613"))
ADMIN_USER_ID = 6930429334
AFFILIATE_TAG = os.getenv("AMAZON_AFFILIATE_TAG", "prodottipe0c9-21")

logging.basicConfig(level=logging.INFO)

# --- DATABASE ---
conn = sqlite3.connect("bot_data.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS licenses (
    key TEXT PRIMARY KEY,
    expiry TEXT,
    used INTEGER DEFAULT 0,
    admin INTEGER DEFAULT 0
)""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS active_users (
    user_id INTEGER PRIMARY KEY,
    license_key TEXT,
    affiliate_tag TEXT
)""")
conn.commit()

# --- CREA ADMIN SE NON ESISTE ---
cursor.execute("SELECT key FROM licenses WHERE admin=1")
row = cursor.fetchone()
if row:
    ADMIN_KEY = row[0]
else:
    ADMIN_KEY = str(uuid.uuid4()).split("-")[0].upper()
    cursor.execute("INSERT INTO licenses (key, expiry, used, admin) VALUES (?, ?, 0, 1)",
                   (ADMIN_KEY, "9999-12-29T23:59:59"))
    conn.commit()
    print(f"Chiave Admin: {ADMIN_KEY}")

# --- LICENZE ---
def create_license(days=30, admin=False):
    key = str(uuid.uuid4()).split("-")[0].upper()
    expiry = "9999-12-29T23:59:59" if admin else (datetime.datetime.now() + datetime.timedelta(days=days)).isoformat()
    cursor.execute("INSERT INTO licenses (key, expiry, used, admin) VALUES (?, ?, 0, ?)", (key, expiry, int(admin)))
    conn.commit()
    return key, expiry

def renew_license(key, months):
    cursor.execute("SELECT expiry FROM licenses WHERE key=?", (key,))
    row = cursor.fetchone()
    if not row:
        return False
    expiry_str = row[0]
    if expiry_str == "9999-12-29T23:59:59":
        return True
    expiry_date = datetime.datetime.fromisoformat(expiry_str)
    new_expiry = expiry_date + datetime.timedelta(days=30*months)
    cursor.execute("UPDATE licenses SET expiry=? WHERE key=?", (new_expiry.isoformat(), key))
    conn.commit()
    return True

def delete_license(key):
    cursor.execute("DELETE FROM licenses WHERE key=?", (key,))
    conn.commit()

async def check_user_license(update: Update):
    user_id = update.message.from_user.id
    if user_id == ADMIN_USER_ID:
        return True
    cursor.execute("SELECT license_key FROM active_users WHERE user_id=?", (user_id,))
    if not cursor.fetchone():
        await update.message.reply_text("❌ Devi inserire una licenza valida per usare il bot.")
        return False
    return True

# --- AMAZON ---
async def expand_url(url):
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.head(url, follow_redirects=True)
            return str(r.url)
        except:
            return url

async def parse_amazon(url):
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(url)
        except:
            return None, None, None
    soup = BeautifulSoup(resp.text, "html.parser")
    title_tag = soup.find("span", {"id": "productTitle"})
    img_tag = soup.find("img", {"id": "landingImage"})
    title = title_tag.get_text(strip=True) if title_tag else None
    img = img_tag.get("src") if img_tag and hasattr(img_tag, "get") else None
    return title, img, url

def add_affiliate_tag(url, user_id=None):
    if user_id:
        cursor.execute("SELECT affiliate_tag FROM active_users WHERE user_id=?", (user_id,))
        row = cursor.fetchone()
        tag = row[0] if row and row[0] else AFFILIATE_TAG
    else:
        tag = AFFILIATE_TAG
    parts = url.split("/")
    if "dp" in parts:
        idx = parts.index("dp")
        if idx + 1 < len(parts):
            asin = parts[idx+1].split("?")[0]
            return f"https://www.amazon.it/dp/{asin}?tag={tag}"
    return url

# --- START ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    keyboard = [["Invia Link Amazon"]]
    if user_id == ADMIN_USER_ID:
        keyboard.insert(0, ["📜 Gestione Licenze"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("🤖Benvenuto in Easy Amz Affiliate❗️", reply_markup=reply_markup)

# --- SET AFFILIATE ---
async def set_affiliate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if len(context.args) != 1:
        await update.message.reply_text("Uso corretto: /setaff <tuo_affiliate_tag>")
        return
    tag = context.args[0].strip()
    cursor.execute("UPDATE active_users SET affiliate_tag=? WHERE user_id=?", (tag, user_id))
    conn.commit()
    await update.message.reply_text(f"✅ Il tuo ID affiliato è stato impostato su: {tag}")

# --- MENU ADMIN LICENZE ---
async def menu_admin_licenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Crea Licenza", callback_data="create_license")],
        [InlineKeyboardButton("Rinnova Licenza", callback_data="renew_license")],
        [InlineKeyboardButton("Elimina Licenza", callback_data="delete_license")],
        [InlineKeyboardButton("Lista Licenze", callback_data="list_license")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🔑 Menu Gestione Licenze:", reply_markup=reply_markup)

# --- GESTIONE LINK AMAZON ---
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_license(update):
        return
    url = update.message.text.strip()
    if not any(x in url for x in ["amazon", "amzn.to", "amzn.eu"]):
        await update.message.reply_text("❌ Per favore manda un link Amazon valido 🔗")
        return
    loading_msg = await update.message.reply_text("📦 Caricamento prodotto...")
    try:
        url_exp = await expand_url(url)
        url_aff = add_affiliate_tag(url_exp, update.message.from_user.id)
        title, img, final_url = await parse_amazon(url_aff)
        if not title:
            await update.message.reply_text("❌ Non sono riuscito a caricare il prodotto. Invia di nuovo il link Amazon.")
            await loading_msg.delete()
            return
    except:
        await update.message.reply_text("❌ Errore caricando il prodotto. Riprova.")
        await loading_msg.delete()
        return

    context.user_data["product"] = {
        "title": title,
        "img": img,
        "url": final_url,
        "price": "Prezzo non inserito",
        "ready": True
    }

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
            await context.bot.edit_message_media(chat_id=loading_msg.chat_id,
                                                 message_id=loading_msg.message_id,
                                                 media=InputMediaPhoto(img, caption=caption),
                                                 reply_markup=reply_markup)
        else:
            await context.bot.edit_message_text(chat_id=loading_msg.chat_id,
                                                message_id=loading_msg.message_id,
                                                text=caption,
                                                reply_markup=reply_markup)
    except Exception as e:
        logging.error(f"Errore aggiornando messaggio: {e}")

# --- CALLBACK BOTTONI AMAZON E LICENZE ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    product = context.user_data.get("product")

    # --- AMAZON ---
    if data == "modify" and product:
        await query.message.reply_text("Scrivi il prezzo manualmente:")
        context.user_data["waiting_price"] = True
    elif data == "edit_title" and product:
        await query.message.reply_text(f"Scrivi il nuovo titolo (originale: {product['title']}):")
        context.user_data["waiting_title"] = True
    elif data == "publish" and product:
        msg = f"📌 <b>{product['title']}</b>\n〰️〰️〰️〰️\n💶 {product['price']}\n〰️〰️〰️〰️\n📲 <a href='{product['url']}'>Acquista su Amazon</a>"
        if product["img"]:
            await context.bot.send_photo(chat_id=GROUP_ID, photo=product["img"], caption=msg, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=GROUP_ID, text=msg, parse_mode="HTML")
        await query.message.reply_text("Prodotto pubblicato nel canale ✅")
