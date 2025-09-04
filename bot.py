import json
import datetime
import uuid
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- CONFIG ---
TOKEN = "7817602011:AAHioblDdeZNdhUCuNRSqTKjK5PO-LotivI"
GROUP_ID = -1002093792613
LICENSES_FILE = "licenses.json"
ACTIVE_USERS_FILE = "active_users.json"

logging.basicConfig(level=logging.INFO)

# --- Carica licenze ---
try:
    with open(LICENSES_FILE, "r") as f:
        LICENSES = json.load(f)
except FileNotFoundError:
    LICENSES = {}

# --- Carica utenti attivi ---
try:
    with open(ACTIVE_USERS_FILE, "r") as f:
        ACTIVE_USERS = json.load(f)
except FileNotFoundError:
    ACTIVE_USERS = {}

# --- Funzioni licenze ---
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

# --- Crea chiave admin se non esiste ---
admin_key = None
for k, v in LICENSES.items():
    if v.get("admin", False):
        admin_key = k
        break
if not admin_key:
    admin_key, _ = create_license(admin=True)
    print(f"Chiave Admin generata: {admin_key} (scade 29/12/9999)")

# --- Comando /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if str(user_id) in ACTIVE_USERS:
        await update.message.reply_text("Benvenuto! Sei già registrato.")
    else:
        await update.message.reply_text("Benvenuto! Inserisci la tua chiave licenza:")

# --- Inserimento chiave licenza ---
async def license_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_key = update.message.text.strip().upper()
    valid, is_admin = activate_license(user_id, user_key)
    if not valid:
        await update.message.reply_text("Chiave non valida o già usata/scaduta ❌")
        return
    if is_admin:
        await update.message.reply_text(f"Accesso Admin attivato ✅\nChiave: {user_key}")
    else:
        await update.message.reply_text(f"Licenza attivata ✅\nChiave: {user_key}")

# --- Comando /licenze (solo admin) ---
async def manage_licenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if str(user_id) not in ACTIVE_USERS:
        await update.message.reply_text("Non hai accesso a questo comando ❌")
        return
    key = ACTIVE_USERS[str(user_id)]
    if not LICENSES[key].get("admin", False):
        await update.message.reply_text("Non hai permessi admin ❌")
        return

    keyboard = [
        [InlineKeyboardButton("🆕 Crea licenza", callback_data="create_license")],
        [InlineKeyboardButton("♻️ Rinnova licenza", callback_data="renew_license")],
        [InlineKeyboardButton("🗑 Elimina licenza", callback_data="delete_license")],
        [InlineKeyboardButton("⏳ Licenze scadute", callback_data="expired_license")],
        [InlineKeyboardButton("📜 Tutte le licenze", callback_data="all_licenses")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Gestione Licenze:", reply_markup=reply_markup)

# --- Callback bottoni admin ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    key = ACTIVE_USERS.get(str(user_id))
    if not key or not LICENSES[key].get("admin", False):
        await query.message.reply_text("Non hai permessi admin ❌")
        return

    if query.data == "create_license":
        # Mostra bottoni con durata
        keyboard = [
            [InlineKeyboardButton("1 mese", callback_data="duration_30")],
            [InlineKeyboardButton("3 mesi", callback_data="duration_90")],
            [InlineKeyboardButton("6 mesi", callback_data="duration_180")],
            [InlineKeyboardButton("12 mesi", callback_data="duration_365")]
        ]
        await query.message.reply_text("Seleziona la durata della nuova licenza:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("duration_"):
        days = int(query.data.split("_")[1])
        new_key, expiry = create_license(days_valid=days)
        await query.message.reply_text(f"Licenza creata ✅\nChiave: {new_key}\nScadenza: {expiry}")

    elif query.data == "renew_license":
        context.user_data["action"] = "renew"
        keyboard = [
            [InlineKeyboardButton("1 mese", callback_data="renew_30")],
            [InlineKeyboardButton("3 mesi", callback_data="renew_90")],
            [InlineKeyboardButton("6 mesi", callback_data="renew_180")],
            [InlineKeyboardButton("12 mesi", callback_data="renew_365")]
        ]
        await query.message.reply_text("Seleziona la durata per il rinnovo:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("renew_"):
        days = int(query.data.split("_")[1])
        action_key = context.user_data.get("selected_license")
        if not action_key:
            await query.message.reply_text("Errore: prima seleziona la chiave da rinnovare tramite messaggio testuale.")
            return
        LICENSES[action_key]["scadenza"] = (datetime.datetime.now() + datetime.timedelta(days=days)).isoformat()
        LICENSES[action_key]["usata"] = False
        save_licenses()
        context.user_data["selected_license"] = None
        await query.message.reply_text(f"Chiave {action_key} rinnovata ✅")

    elif query.data == "delete_license":
        context.user_data["action"] = "delete"
        await query.message.reply_text("Inserisci la chiave da eliminare:")

    elif query.data == "expired_license":
        expired = []
        now = datetime.datetime.now()
        for k, v in LICENSES.items():
            if not v.get("admin", False) and datetime.datetime.fromisoformat(v["scadenza"]) < now:
                expired.append(k)
        if expired:
            await query.message.reply_text("Licenze scadute:\n" + "\n".join(expired))
        else:
            await query.message.reply_text("Nessuna licenza scaduta ✅")

    elif query.data == "all_licenses":
        lines = []
        for k, v in LICENSES.items():
            tipo = "Admin" if v.get("admin", False) else "Utente"
            usata = "✅" if v.get("usata", False) else "❌"
            scadenza = v.get("scadenza", "N/A")
            lines.append(f"{k} | {tipo} | Usata: {usata} | Scade: {scadenza}")
        if lines:
            await query.message.reply_text("Tutte le licenze:\n" + "\n".join(lines))
        else:
            await query.message.reply_text("Nessuna licenza presente.")

# --- Gestione input rinnovo/eliminazione ---
async def handle_text_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    key = ACTIVE_USERS.get(str(user_id))
    if not key or not LICENSES[key].get("admin", False):
        return

    action = context.user_data.get("action")
    if not action:
        return

    input_key = update.message.text.strip().upper()
    if input_key not in LICENSES:
        await update.message.reply_text("Chiave non trovata ❌")
        context.user_data["action"] = None
        return

    if action == "renew":
        context.user_data["selected_license"] = input_key
        await update.message.reply_text(f"Chiave {input_key} selezionata. Ora scegli la durata con i bottoni ⏰")
    elif action == "delete":
        del LICENSES[input_key]
        save_licenses()
        await update.message.reply_text(f"Chiave {input_key} eliminata ✅")

    context.user_data["action"] = None

# --- Setup bot ---
app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("licenze", manage_licenses))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, license_entry))
app.add_handler(CallbackQueryHandler(button_callback))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_admin))

# --- Avvio bot ---
if __name__ == "__main__":
    app.run_polling()
