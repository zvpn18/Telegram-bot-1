import os

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)


# Token preso dalle variabili ambiente di TeleBotHost
TOKEN = os.environ.get("BOT_TOKEN")

# Account Telegram che riceverà le richieste utenti
ADMIN_USERNAME = "@peppe_mazzini"


# MENU PRINCIPALE
main_menu = [
    ["📺 Problemi visione"],
    ["📱 Problemi applicazione"],
    ["📲 Richiesta aggiunta eventi, film o serie tv"]
]


# SOTTOMENU
visione_menu = [
    ["📺 I canali si bloccano"],
    ["⚫️ Schermo nero"],
    ["⬅️ Indietro"]
]


app_menu = [
    ["🔑 Problemi di accesso all’app"],
    ["⬅️ Indietro"]
]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["menu"] = "main"

    await update.message.reply_text(
        "Benvenuto.\nSeleziona il problema:",
        reply_markup=ReplyKeyboardMarkup(
            main_menu,
            resize_keyboard=True
        )
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    testo = update.message.text


    # Se l'utente sta inviando una richiesta contenuto
    if context.user_data.get("richiesta"):

        user = update.message.from_user

        await context.bot.send_message(
            chat_id=ADMIN_USERNAME,
            text=(
                "📥 NUOVA RICHIESTA CONTENUTO\n\n"
                f"👤 Utente: {user.first_name}\n"
                f"🆔 ID: {user.id}\n\n"
                f"Richiesta:\n{testo}"
            )
        )

        await update.message.reply_text(
            "✅ Richiesta inviata allo staff.\n\nGrazie per la collaborazione.",
            reply_markup=ReplyKeyboardMarkup(
                [["⬅️ Indietro"]],
                resize_keyboard=True
            )
        )

        context.user_data["richiesta"] = False
        return


    # MENU PRINCIPALE

    if testo == "📺 Problemi visione":

        await update.message.reply_text(
            "Seleziona il problema:",
            reply_markup=ReplyKeyboardMarkup(
                visione_menu,
                resize_keyboard=True
            )
        )


    elif testo == "📱 Problemi applicazione":

        await update.message.reply_text(
            "Seleziona il problema:",
            reply_markup=ReplyKeyboardMarkup(
                app_menu,
                resize_keyboard=True
            )
        )


    elif testo == "📲 Richiesta aggiunta eventi, film o serie tv":

        context.user_data["richiesta"] = True

        await update.message.reply_text(
            "Invia ora il titolo dell’evento, del film o della serie tv che vuoi far inserire in lista.\n\n"
            "Puoi inviare anche la foto della locandina.\n\n"
            "Lo staff lavorerà la tua richiesta e aggiungerà il contenuto alla lista."
        )


    # PROBLEMI VISIONE

    elif testo == "📺 I canali si bloccano":

        await update.message.reply_text(
            "Esci dall’app, tieni spento il router per 5 minuti e riprova.\n\n"
            "In alternativa puoi provare ad utilizzare internet del cellulare collegandolo alla TV.",
            reply_markup=ReplyKeyboardMarkup(
                [["⬅️ Indietro"]],
                resize_keyboard=True
            )
        )


    elif testo == "⚫️ Schermo nero":

        await update.message.reply_text(
            "Controlla la connessione Internet.\n\n"
            "Dopodiché vai sulla schermata principale dell’app e aggiorna la lista canali premendo UPDATE in alto a destra.",
            reply_markup=ReplyKeyboardMarkup(
                [["⬅️ Indietro"]],
                resize_keyboard=True
            )
        )


    # PROBLEMI APPLICAZIONE

    elif testo == "🔑 Problemi di accesso all’app":

        await update.message.reply_text(
            "Controlla lo stato della linea Internet.\n\n"
            "Se il problema persiste, prova ad utilizzare Internet del cellulare collegandolo alla TV.\n\n"
            "Se il problema non si risolve procedi in questo modo:\n\n"
            "1) Esci dall’app e vai nelle impostazioni della chiavetta.\n"
            "2) Premi su Applicazioni e poi Gestisci app installate.\n"
            "3) Premi su OK-Tv.\n"
            "4) Premi su Cancella cache e riprova.\n\n"
            "Se il problema persiste premi anche Cancella dati.\n"
            "Apri l’app, inserisci le tue credenziali e riprova.",
            reply_markup=ReplyKeyboardMarkup(
                [["⬅️ Indietro"]],
                resize_keyboard=True
            )
        )


    # INDIETRO

    elif testo == "⬅️ Indietro":

        await update.message.reply_text(
            "Menu principale:",
            reply_markup=ReplyKeyboardMarkup(
                main_menu,
                resize_keyboard=True
            )
        )


def main():

    if not TOKEN:
        raise ValueError(
            "Token BOT_TOKEN non trovato nelle variabili ambiente"
        )


    application = Application.builder().token(TOKEN).build()


    application.add_handler(
        CommandHandler("start", start)
    )


    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler
        )
    )


    application.run_polling()


if __name__ == "__main__":
    main()
