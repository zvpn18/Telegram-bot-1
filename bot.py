import logging
import requests
import os
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask
from threading import Thread

# CONFIGURAZIONE BOT
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7817602011:AAHAuov03EDtJe9kQ-kzu5RPQuScOJW_G-U")
GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", "-1003074106173"))
AFFILIATE_TAG = os.getenv("AMAZON_AFFILIATE_TAG", "prodottipe0c9-21")

logging.basicConfig(level=logging.INFO)

# 🔹 Espande short link
def expand_url(url):
    try:
        session = requests.Session()
        resp = session.head(url, allow_redirects=True, timeout=10)
        logging.info(f"URL espanso: {resp.url}")
        return resp.url
    except Exception as e:
        logging.error(f"Errore espansione URL: {e}")
        return url

# 🔹 Genera link con ASIN + tag affiliato
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
    except Exception as e:
        logging.error(f"Errore parsing Amazon: {e}")
        return "Prodotto Amazon", None

    title_tag = soup.find("span", {"id": "productTitle"})
    title = title_tag.get_text(strip=True) if title_tag else "Prodotto Amazon"

    img_tag = soup.find("img", {"id": "landingImage"})
    img_url = img_tag.get("src") if img_tag and hasattr(img_tag, 'get') else None

    return title, img_url

# 🔹 Gestione link Amazon
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    original_msg = update.message
    url = original_msg.text.strip()

    await original_msg.reply_text("📦 Caricamento prodotto...")

    # Espande link e aggiunge tag affiliato
    url = expand_url(url)
    url = add_affiliate_tag(url, AFFILIATE_TAG)
    title, img_url = parse_amazon(url)

    # Salva info prodotto
    context.user_data['product'] = {
        "title": title,
        "img": img_url,
        "url": url,
        "price": "<b><u>Prezzo non inserito</u></b>"
    }
    context.user_data['waiting_price'] = False
    context.user_data['product_ready'] = True

    caption_text = (
        f"📌 {title}\n\n"
        f"➖➖➖\n\n"
        f"💶 {context.user_data['product']['price']}\n\n"
        f"➖➖➖\n\n"
        f"🛒 Acquista su Amazon"
    )
    keyboard = [
        [InlineKeyboardButton("✏️ Modifica prezzo", callback_data="modify")],
        [InlineKeyboardButton("✅ Pubblica sul canale", callback_data="publish")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if img_url:
        await original_msg.reply_photo(photo=img_url, caption=caption_text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await original_msg.reply_text(caption_text, reply_markup=reply_markup, parse_mode="HTML")

    logging.info(f"Prodotto caricato: {title}")

# 🔹 Callback bottoni
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not context.user_data.get('product_ready', False):
        await query.message.reply_text("⏳ Attendi, sto ancora caricando i dati del prodotto...")
        return

    product = context.user_data.get('product')

    if query.data == "modify":
        await query.message.reply_text("Scrivi il prezzo (es. 10,99) ⬇️")
        context.user_data['waiting_price'] = True

    elif query.data == "publish":
        caption_text = (
            f"📌 {product['title']}\n\n"
            f"➖➖➖\n\n"
            f"💶 {product['price']}\n\n"
            f"➖➖➖\n\n"
            f"🛒 <a href='{product['url']}'>Acquista su Amazon</a>"
        )
        if product.get('img'):
            await context.bot.send_photo(chat_id=GROUP_ID, photo=product['img'], caption=caption_text, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=GROUP_ID, text=caption_text, parse_mode="HTML")

        await query.message.reply_text("Prodotto pubblicato nel canale ✅")
        logging.info(f"Prodotto pubblicato: {product['title']} - {product['price']}")

# 🔹 Gestione messaggi testo (link o prezzo)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Se l'utente sta inserendo il prezzo
    if context.user_data.get('waiting_price') and 'product' in context.user_data:
        price = text.replace(",", ".")
        if not price.endswith("€"):
            price = f"{price}€"

        # 🔥 Formattiamo sempre grassetto + sottolineato
        context.user_data['product']['price'] = f"<b><u>{price}</u></b>"
        context.user_data['waiting_price'] = False

        product = context.user_data['product']
        caption_text = (
            f"📌 {product['title']}\n\n"
            f"➖➖➖\n\n"
            f"💶 {product['price']}\n\n"
            f"➖➖➖\n\n"
            f"🛒 <a href='{product['url']}'>Acquista su Amazon</a>"
        )
        keyboard = [
            [InlineKeyboardButton("✏️ Modifica prezzo", callback_data="modify")],
            [InlineKeyboardButton("✅ Pubblica sul canale", callback_data="publish")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if product.get('img'):
            await update.message.reply_photo(photo=product['img'], caption=caption_text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await update.message.reply_text(text=caption_text, parse_mode="HTML", reply_markup=reply_markup)

        logging.info(f"Prezzo aggiornato: {product['title']} - {product['price']}")
        return

    # Altrimenti interpreta come link Amazon
    if "amazon" in text or "amzn.to" in text or "amzn.eu" in text:
        await handle_link(update, context)
    else:
        await update.message.reply_text("Per favore manda un link Amazon valido 🔗")

# 🔹 Comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ciao! Inviami un link Amazon e potrai modificare il prezzo 🚀")
    logging.info("Bot attivo 🚀")

# 🔹 Server Flask keep-alive
flask_app = Flask('')
@flask_app.route('/')
def home():
    return "Bot attivo 🚀"
Thread(target=lambda: flask_app.run(host="0.0.0.0", port=5000)).start()

# 🔹 Avvio bot
def main():
    telegram_app = Application.builder().token(TOKEN).build()

    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CallbackQueryHandler(button_callback))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logging.info("Bot avviato e in ascolto dei messaggi 🚀")
    telegram_app.run_polling()

if __name__ == "__main__":
    main()
