import logging
import requests
import os
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask
from threading import Thread
import asyncio

# CONFIGURAZIONE BOT
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7817602011:AAHioblDdeZNdhUCuNRSqTKjK5PO-LotivI")
GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", "-1002093792613"))
AFFILIATE_TAG = os.getenv("AMAZON_AFFILIATE_TAG", "prodottipe0c9-21")

logging.basicConfig(level=logging.INFO)

# 🔹 Espande short link
def expand_url(url):
    try:
        session = requests.Session()
        resp = session.head(url, allow_redirects=True, timeout=10)
        return resp.url
    except:
        return url

# 🔹 Genera link breve con ASIN + tag affiliato
def add_affiliate_tag(url, tag):
    asin = None
    parts = url.split("/")
    if "dp" in parts:
        idx = parts.index("dp")
        if idx + 1 < len(parts):
            asin = parts[idx + 1].split("?")[0]
    if not asin:
        return url
    return f"https://www.amazon.it/dp/{asin}?tag={tag}"

# 🔹 Estrazione info prodotto Amazon
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

# 🔹 Gestione link Amazon
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_price') or context.user_data.get('waiting_title') or context.user_data.get('waiting_schedule'):
        await manual_input(update, context)
        return

    original_msg = update.message
    url = update.message.text.strip()

    if not ("amazon" in url or "amzn.to" in url or "amzn.eu" in url):
        await original_msg.reply_text("Per favore manda un link Amazon valido 🔗")
        return

    loading_msg = await original_msg.reply_text("📦 Caricamento prodotto...")
    asyncio.create_task(parse_and_update(context.bot, loading_msg.chat_id, loading_msg.message_id, url, context))

# 🔹 Parsing + Preview
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
        [InlineKeyboardButton("⏰ Riprogramma", callback_data="schedule")],
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

# 🔹 Callback bottoni
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not context.user_data.get('product_ready', False):
        await query.message.reply_text("⏳ Attendi, sto ancora caricando i dati del prodotto...")
        return

    product = context.user_data.get('product')

    if query.data == "modify":
        await query.message.reply_text("Scrivi il prezzo manualmente:")
        context.user_data['waiting_price'] = True

    elif query.data == "edit_title":
        current_title = product['title']
        await query.message.reply_text(
            f"Scrivi il nuovo titolo del prodotto (puoi modificare il seguente):\n\n{current_title}"
        )
        context.user_data['waiting_title'] = True

    elif query.data == "schedule":
        keyboard = [
            [InlineKeyboardButton("5 min", callback_data="schedule_5")],
            [InlineKeyboardButton("10 min", callback_data="schedule_10")],
            [InlineKeyboardButton("15 min", callback_data="schedule_15")],
            [InlineKeyboardButton("20 min", callback_data="schedule_20")]
        ]
        await query.message.reply_text("Scegli dopo quanti minuti pubblicare il prodotto:", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data['waiting_schedule'] = True

    elif query.data.startswith("schedule_"):
        minutes = int(query.data.split("_")[1])
        await query.message.reply_text(f"Il messaggio sarà pubblicato tra {minutes} minuti ⏰")
        asyncio.create_task(schedule_publish(context.bot, product, minutes))
        context.user_data['waiting_schedule'] = False

    elif query.data == "publish":
        await publish_product(context.bot, product)
        await query.message.reply_text("Prodotto pubblicato nel canale ✅")

# 🔹 Gestione input manuale (prezzo o titolo)
async def manual_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_price'):
        price = update.message.text.strip()
        context.user_data['product']['price'] = price
        await update.message.reply_text(
            f"Prezzo aggiornato a: {price}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Pubblica sul canale", callback_data="publish")]])
        )
        context.user_data['waiting_price'] = False

    elif context.user_data.get('waiting_title'):
        title = update.message.text.strip()
        context.user_data['product']['title'] = title
        await update.message.reply_text(
            f"Titolo aggiornato a: {title}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Pubblica sul canale", callback_data="publish")]])
        )
        context.user_data['waiting_title'] = False

# 🔹 Pubblicazione programmata
async def schedule_publish(bot, product, minutes):
    await asyncio.sleep(minutes * 60)
    await publish_product(bot, product)

# 🔹 Funzione pubblicazione
async def publish_product(bot, product):
    msg = f"📌 <b>{product['title']}</b>\n〰️〰️〰️〰️\n💶 {product['price']}\n〰️〰️〰️〰️\n📲 <a href='{product['url']}'>Acquista su Amazon</a>"
    if product['img']:
        await bot.send_photo(chat_id=GROUP_ID, photo=product['img'], caption=msg, parse_mode="HTML")
    else:
        await bot.send_message(chat_id=GROUP_ID, text=msg, parse_mode="HTML")

# 🔹 Comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ciao! Inviami un link Amazon e potrai modificare prezzo, titolo e programmare la pubblicazione 🚀"
    )

# 🔹 Server Flask per keep-alive Render
flask_app = Flask('')

@flask_app.route('/')
def home():
    return "Bot attivo 🚀"

def run_flask():
    flask_app.run(host="0.0.0.0", port=5000)

Thread(target=run_flask).start()

# 🔹 Avvio bot
def main():
    telegram_app = Application.builder().token(TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    telegram_app.add_handler(CallbackQueryHandler(button_callback))
    telegram_app.run_polling()

if __name__ == "__main__":
    main()
