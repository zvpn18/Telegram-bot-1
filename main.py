import telebot
import os
from telebot import types

TOKEN = os.environ.get("TOKEN")
ADMIN_ID = os.environ.get("ADMIN_ID")

bot = telebot.TeleBot(TOKEN)

# Stati utente
user_state = {}

# MENU PRINCIPALE
main_menu = types.ReplyKeyboardMarkup(resize_keyboard=True)
main_menu.add("📺 Problemi visione")
main_menu.add("📱 Problemi applicazione") 
main_menu.add("📲 Richiesta aggiunta eventi, film o serie tv")

# SOTTOMENU
visione_menu = types.ReplyKeyboardMarkup(resize_keyboard=True)
visione_menu.add("📺 I canali si bloccano")
visione_menu.add("⚫️ Schermo nero")
visione_menu.add("⬅️ Indietro")

app_menu = types.ReplyKeyboardMarkup(resize_keyboard=True)
app_menu.add("🔑 Problemi di accesso all’app")
app_menu.add("⬅️ Indietro")

back_menu = types.ReplyKeyboardMarkup(resize_keyboard=True)
back_menu.add("⬅️ Indietro")

@bot.message_handler(commands=['start'])
def start(message):
    user_state[message.chat.id] = "main"
    bot.send_message(
        message.chat.id,
        "Benvenuto.\nSeleziona il problema:",
        reply_markup=main_menu
    )

@bot.message_handler(commands=['id'])
def get_id(message):
    bot.reply_to(message, f"Il tuo ID è: `{message.from_user.id}`\n\nCopia questo numero e mettilo in ADMIN_ID su TelebotHost", parse_mode="Markdown")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    if user_state.get(chat_id) == "richiesta":
        user = message.from_user
        caption = message.caption or "Nessun titolo"
        try:
            bot.send_photo(
                ADMIN_ID,
                message.photo[-1].file_id,
                caption=f"📥 NUOVA RICHIESTA CONTENUTO\n\n"
                        f"👤 Utente: {user.first_name}\n"
                        f"🆔 ID: {user.id}\n"
                        f"Username: @{user.username}\n\n"
                        f"Richiesta:\n{caption}"
            )
            bot.send_message(
                chat_id,
                "✅ Richiesta con locandina inviata allo staff.\n\nGrazie per la collaborazione.",
                reply_markup=back_menu
            )
        except Exception as e:
            bot.send_message(
                chat_id,
                "❌ Errore invio. Controlla che ADMIN_ID sia impostato correttamente",
                reply_markup=main_menu
            )
        user_state[chat_id] = "main"

@bot.message_handler(func=lambda m: True)
def message_handler(message):
    chat_id = message.chat.id
    testo = message.text
    
    if user_state.get(chat_id) == "richiesta":
        user = message.from_user
        try:
            bot.send_message(
                ADMIN_ID,
                f"📥 NUOVA RICHIESTA CONTENUTO\n\n"
                f"👤 Utente: {user.first_name}\n"
                f"🆔 ID: {user.id}\n"
                f"Username: @{user.username}\n\n"
                f"Richiesta:\n{testo}"
            )
            bot.send_message(
                chat_id,
                "✅ Richiesta inviata allo staff.\n\nGrazie per la collaborazione.",
                reply_markup=back_menu
            )
        except:
            bot.send_message(
                chat_id,
                "❌ Errore invio. L'admin deve prima avviare il bot con /start e ADMIN_ID deve essere impostato",
                reply_markup=main_menu
            )
        user_state[chat_id] = "main"
        return

    if testo == "📺 Problemi visione":
        bot.send_message(chat_id, "Seleziona il problema:", reply_markup=visione_menu)
    
    elif testo == "📱 Problemi applicazione":
        bot.send_message(chat_id, "Seleziona il problema:", reply_markup=app_menu)
    
    elif testo == "📲 Richiesta aggiunta eventi, film o serie tv":
        user_state[chat_id] = "richiesta"
        bot.send_message(
            chat_id,
            "Invia ora il titolo dell’evento, del film o della serie tv che vuoi far inserire in lista.\n\n"
            "Puoi inviare anche la foto della locandina.\n\n"
            "Lo staff lavorerà la tua richiesta e aggiungerà il contenuto alla lista."
        )

    elif testo == "📺 I canali si bloccano":
        bot.send_message(
            chat_id,
            "Esci dall’app, tieni spento il router per 5 minuti e riprova.\n\n"
            "In alternativa puoi provare ad utilizzare internet del cellulare collegandolo alla TV.",
            reply_markup=back_menu
        )
    
    elif testo == "⚫️ Schermo nero":
        bot.send_message(
            chat_id,
            "Controlla la connessione Internet.\n\n"
            "Dopodiché vai sulla schermata principale dell’app e aggiorna la lista canali premendo UPDATE in alto a destra.",
            reply_markup=back_menu
        )

    elif testo == "🔑 Problemi di accesso all’app":
        bot.send_message(
            chat_id,
            "Controlla lo stato della linea Internet.\n\n"
            "Se il problema persiste, prova ad utilizzare Internet del cellulare collegandolo alla TV.\n\n"
            "Se il problema non si risolve procedi in questo modo:\n\n"
            "1) Esci dall’app e vai nelle impostazioni della chiavetta.\n"
            "2) Premi su Applicazioni e poi Gestisci app installate.\n"
            "3) Premi su OK-Tv.\n"
            "4) Premi su Cancella cache e riprova.\n\n"
            "Se il problema persiste premi anche Cancella dati.\n"
            "Apri l’app, inserisci le tue credenziali e riprova.",
            reply_markup=back_menu
        )

    elif testo == "⬅️ Indietro":
        user_state[chat_id] = "main"
        bot.send_message(chat_id, "Menu principale:", reply_markup=main_menu)

print("Bot avviato...")
bot.infinity_polling(timeout=60)
