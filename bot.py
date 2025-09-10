import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CallbackQueryHandler, CommandHandler,
    ConversationHandler, filters, ContextTypes
)

# --- Dati del bot ---
TOKEN = "7817602011:AAHioblDdeZNdhUCuNRSqTKjK5PO-LotivI"
CHANNEL_ID = "-1003074106173"
AFFILIATE_TAG = "prodottipe0c9-21"

WAITING_PRICE = 1

# --- Regex per link Amazon (.com, .it, .eu, .to) ---
AMAZON_REGEX = r"(https?:\/\/(www\.)?amazon\.(com|it|eu|to)\/[^\s]+)"

# --- Escape MarkdownV2 ---
def escape_markdown(text):
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

# --- Funzione simulata per ottenere info prodotto ---
def get_product_info(url):
    # In futuro sostituire con Amazon PA-API
    return {
        "title": "Esempio prodotto Amazon con descrizione breve",
        "price": "11,99 €",
        "image": "https://m.media-amazon.com/images/I/71x...jpg",
        "affiliate_link": url + f"?tag={AFFILIATE_TAG}"
    }

# --- Comando /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Benvenuto ragazzo 👋\nInvia un link Amazon (.com, .it, .eu, .to) per generare il messaggio."
    )

# --- Gestione link Amazon ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    match = re.search(AMAZON_REGEX, text)
    if match:
        url = match.group(0)
        await handle_link_with_url(update, context, url)

async def handle_link_with_url(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    product = get_product_info(url)
    title_escaped = escape_markdown(product['title'])
    price_escaped = escape_markdown(product['price'])
    link_escaped = escape_markdown(product['affiliate_link'])

    caption = (
        f"📌 {title_escaped}\n\n"
        f"〰️〰️〰️\n\n"
        f"💰 Prezzo: __**{price_escaped}**__\n\n"
        f"〰️〰️〰️\n\n"
        f"📲 [Acquista su Amazon]({link_escaped})"
    )

    keyboard = [
        [InlineKeyboardButton("✏️ Cambia prezzo", callback_data="change_price")],
        [InlineKeyboardButton("✅ Pubblica sul canale", callback_data="publish")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    sent_msg = await update.message.reply_photo(
        photo=product["image"],
        caption=caption,
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )

    context.user_data["edit_msg"] = sent_msg

# --- Gestione bottoni ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "change_price":
        await query.message.reply_text("✏️ Inserisci il prezzo corretto")
        return WAITING_PRICE
    elif query.data == "publish":
        msg = query.message
        await context.bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=msg.photo[-1].file_id,
            caption=msg.caption,
            parse_mode="MarkdownV2"
        )
        await query.message.reply_text("✅ Pubblicato sul canale")
    return ConversationHandler.END

# --- Gestione nuovo prezzo ---
async def new_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_price = update.message.text
    msg = context.user_data.get("edit_msg")
    if not msg:
        await update.message.reply_text("❌ Nessun messaggio da modificare.")
        return ConversationHandler.END

    lines = msg.caption.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("💰 Prezzo"):
            lines[i] = f"💰 Prezzo: __**{escape_markdown(new_price)}**__"
    new_caption = "\n".join(lines)

    keyboard = [[InlineKeyboardButton("✅ Pubblica sul canale", callback_data="publish")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await msg.edit_caption(
        caption=new_caption,
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )
    await update.message.reply_text("✅ Prezzo aggiornato!")
    return ConversationHandler.END

# --- Avvio bot ---
def main():
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        states={
            WAITING_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_price)]
        },
        fallbacks=[]
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("✅ Bot avviato...")
    app.run_polling()

if __name__ == "__main__":
    main()
