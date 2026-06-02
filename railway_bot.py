import os
import time
import asyncio
import sqlite3
import requests
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler, ConversationHandler
)

# ================= CONFIG =================
TOKEN        = os.environ.get("BOT_TOKEN", "8884909837:AAEF9MHEhDytK66yJKhLMijttlOCcHhCqrU")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "3e1ae476b9msh23fa56ceb864394p189efcjsn0608a7111b65")

PNR_HOST   = "irctc-indian-railway-pnr-status.p.rapidapi.com"
TRAIN_HOST = "irctc1.p.rapidapi.com"

def pnr_headers():
    return {"x-rapidapi-host": PNR_HOST, "x-rapidapi-key": RAPIDAPI_KEY, "Content-Type": "application/json"}

def train_headers():
    return {"x-rapidapi-host": TRAIN_HOST, "x-rapidapi-key": RAPIDAPI_KEY}

# ================= DB =================
conn = sqlite3.connect("railway_bot.db", check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL")
c = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, username TEXT, language TEXT DEFAULT 'hi', joined INTEGER)""")
c.execute("""CREATE TABLE IF NOT EXISTS journey_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT, query TEXT, result TEXT, searched_at INTEGER)""")
c.execute("""CREATE TABLE IF NOT EXISTS favourite_trains (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, train_no TEXT, train_name TEXT)""")
c.execute("""CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT, train_no TEXT, pnr TEXT, active INTEGER DEFAULT 1, created_at INTEGER)""")
conn.commit()

# ================= STATES =================
PNR_INPUT     = 1
TRAIN_INPUT   = 2
STATION_INPUT = 3
LIVE_INPUT    = 7
COACH_TRAIN   = 8
BETWEEN_FROM  = 9
BETWEEN_TO    = 10
BETWEEN_DATE  = 11

# ================= UI =================
def main_keyboard(lang="hi"):
    return ReplyKeyboardMarkup([
        ["🎫 PNR Status",      "🚂 Train Schedule"],
        ["🔍 Trains Between",  "📍 Live Train"],
        ["🏛️ Station Board",  "⭐ Favourites"],
        ["📜 History",         "🔔 Alerts"],
        ["🌐 Language",        "ℹ️ Help"]
    ], resize_keyboard=True)

# ================= HELPERS =================
def get_user(uid):
    c.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    return c.fetchone()

def ensure_user(uid, username=None):
    c.execute("INSERT OR IGNORE INTO users (user_id,username,language,joined) VALUES (?,?,?,?)",
              (uid, username, "hi", int(time.time())))
    conn.commit()

def get_lang(uid):
    u = get_user(uid)
    return u[2] if u else "hi"

def save_history(uid, qtype, query, result):
    c.execute("INSERT INTO journey_history (user_id,type,query,result,searched_at) VALUES (?,?,?,?,?)",
              (uid, qtype, query, result[:200], int(time.time())))
    conn.commit()

def txt(lang, hi, en):
    return hi if lang == "hi" else en

def api_limit_msg(lang):
    return txt(lang,
        "⚠️ Is mahine ki API limit khatam ho gayi! Kal dobara try karo ya plan upgrade karo.",
        "⚠️ Monthly API limit exceeded! Try again tomorrow or upgrade plan.")

# ================= API CALLS =================
def api_pnr(pnr):
    try:
        r = requests.get(f"https://{PNR_HOST}/getPNRStatus/{pnr}", headers=pnr_headers(), timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def api_schedule(train_no):
    try:
        r = requests.get(f"https://{TRAIN_HOST}/api/v1/getTrainSchedule",
                         headers=train_headers(), params={"trainNo": train_no}, timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def api_live(train_no, start_day=1):
    try:
        r = requests.get(f"https://{TRAIN_HOST}/api/v1/liveTrainStatus",
                         headers=train_headers(), params={"trainNo": train_no, "startDay": str(start_day)}, timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def api_station(station_code, hours=2):
    try:
        r = requests.get(f"https://{TRAIN_HOST}/api/v3/getLiveStation",
                         headers=train_headers(), params={"fromStationCode": station_code, "hours": str(hours)}, timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def api_between(from_stn, to_stn, date):
    try:
        r = requests.get(f"https://{TRAIN_HOST}/api/v3/trainBetweenStations",
                         headers=train_headers(),
                         params={"fromStationCode": from_stn, "toStationCode": to_stn, "dateOfJourney": date},
                         timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

# ================= FORMATTERS =================
def check_limit(data, lang):
    if isinstance(data, dict):
        msg = data.get("message", "")
        if "429" in str(data.get("status","")) or "quota" in msg.lower() or "exceeded" in msg.lower():
            return api_limit_msg(lang)
    return None

def format_pnr(data, lang):
    try:
        limit = check_limit(data, lang)
        if limit: return limit
        if not data.get("success", True):
            msg = data.get("message", "")
            if "FLUSHED" in msg:
                return txt(lang, "❌ Ye PNR expire ho chuka hai!", "❌ This PNR is flushed!")
            return txt(lang, f"❌ PNR nahi mila! {msg}", f"❌ PNR not found! {msg}")
        d = data.get("data", data)
        if not d or "error" in data:
            return txt(lang, "❌ PNR nahi mila!", "❌ PNR not found!")
        pnr        = d.get("pnrNumber", "—")
        train      = d.get("trainNumber", "—")
        train_name = d.get("trainName", "—")
        from_stn   = d.get("boardingPoint", d.get("sourceStation", "—"))
        to_stn     = d.get("reservationUpto", d.get("destinationStation", "—"))
        doj        = d.get("dateOfJourney", "—")
        arr        = d.get("arrivalDate", "—")
        cls        = d.get("journeyClass", d.get("classType", "—"))
        chart      = d.get("chartStatus", "—")
        fare       = d.get("ticketFare", "—")
        passengers = d.get("passengerList", [])
        msg = (
            f"🎫 *PNR Status*\n━━━━━━━━━━━━━━━━━\n"
            f"🔢 PNR     : `{pnr}`\n"
            f"🚂 Train   : {train} - {train_name}\n"
            f"📍 From    : {from_stn}\n"
            f"📍 To      : {to_stn}\n"
            f"📅 Journey : {doj}\n"
            f"🕐 Arrival : {arr}\n"
            f"💺 Class   : {cls}\n"
            f"📋 Chart   : {chart}\n"
            f"💰 Fare    : ₹{fare}\n"
            f"━━━━━━━━━━━━━━━━━\n"
        )
        if passengers:
            msg += "👥 *Passenger Status:*\n"
            for p in passengers:
                i         = p.get("passengerSerialNumber", "—")
                booking   = p.get("bookingStatusDetails", "—")
                current   = p.get("currentStatusDetails", "—")
                curr_code = p.get("currentStatus", "")
                if curr_code == "CNF":   emoji = "✅"
                elif curr_code == "RAC": emoji = "🟡"
                elif curr_code in ("WL","RLWL","GNWL","PQWL"): emoji = "🔴"
                else: emoji = "ℹ️"
                msg += f"  {emoji} P{i}: Booked `{booking}` → Now *{current}*\n"
        return msg
    except:
        return txt(lang, "❌ Data parse nahi hua!", "❌ Could not parse!")

def format_schedule(data, lang):
    try:
        limit = check_limit(data, lang)
        if limit: return limit
        if "error" in data or not data.get("status"):
            return txt(lang, "❌ Train nahi mili!", "❌ Train not found!")
        d          = data.get("data", {})
        train_no   = d.get("trainNumber", "—")
        train_name = d.get("trainName", "—")
        run_days   = d.get("runDays", {})
        days_str   = ", ".join([day.upper() for day, runs in run_days.items() if runs]) if run_days else "—"
        stations   = d.get("stationList", [])
        msg = (
            f"🚂 *Train Schedule*\n━━━━━━━━━━━━━━━━━\n"
            f"🔢 Train   : {train_no} - {train_name}\n"
            f"📅 Runs on : {days_str}\n"
            f"━━━━━━━━━━━━━━━━━\n"
        )
        for s in stations[:15]:
            stn  = s.get("stationCode", "—")
            name = s.get("stationName", "—")
            arr  = s.get("arrivalTime", "—")
            dep  = s.get("departureTime", "—")
            day  = s.get("dayCount", "")
            halt = s.get("haltTime", "—")
            msg += f"🏛️ *{name}* ({stn}) — Day {day}\n"
            msg += f"   🟢 Arr: {arr}  🔴 Dep: {dep}  ⏸️ Halt: {halt}m\n\n"
        if len(stations) > 15:
            msg += f"_...aur {len(stations)-15} stations_\n"
        return msg
    except:
        return txt(lang, "❌ Schedule nahi mila!", "❌ Schedule not found!")

def format_live(data, lang):
    try:
        limit = check_limit(data, lang)
        if limit: return limit
        if "error" in data or not data.get("status"):
            return txt(lang, "❌ Live status nahi mila! Train chal rahi hai?", "❌ Live status not found!")
        d          = data.get("data", {})
        train_no   = d.get("trainNumber", "—")
        train_name = d.get("trainName", "—")
        curr       = d.get("currentStation", {})
        curr_name  = curr.get("stationName", "—") if isinstance(curr, dict) else str(curr)
        curr_code  = curr.get("stationCode", "—") if isinstance(curr, dict) else "—"
        nxt        = d.get("nextStation", {})
        next_name  = nxt.get("stationName", "—") if isinstance(nxt, dict) else str(nxt)
        delay      = d.get("delayedBy", 0)
        status     = d.get("trainStatus", d.get("status", "—"))
        delay_txt  = f"⚠️ {delay} min late" if delay and int(str(delay) or 0) > 0 else "✅ On Time"
        return (
            f"📍 *Live Train Status*\n━━━━━━━━━━━━━━━━━\n"
            f"🚂 Train     : {train_no} - {train_name}\n"
            f"📍 At        : *{curr_name}* ({curr_code})\n"
            f"➡️ Next Stop : {next_name}\n"
            f"⏱️ Delay     : {delay_txt}\n"
            f"📊 Status    : {status}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"_Updated: {time.strftime('%I:%M %p')}_"
        )
    except:
        return txt(lang, "❌ Live status nahi mila!", "❌ Live status not found!")

def format_station(data, lang, stn_code):
    try:
        limit = check_limit(data, lang)
        if limit: return limit
        trains = data.get("data", [])
        if not trains:
            return txt(lang, f"❌ {stn_code} ka data nahi mila!", f"❌ No data for {stn_code}!")
        msg = f"🏛️ *Station Board — {stn_code.upper()}*\n━━━━━━━━━━━━━━━━━\n\n"
        for t in trains[:10]:
            tno   = t.get("trainNumber", "—")
            tname = t.get("trainName", "—")
            arr   = t.get("arrivalTime", "—")
            dep   = t.get("departureTime", "—")
            ttype = t.get("trainType", "—")
            msg  += f"🚂 *{tno}* - {tname}\n"
            msg  += f"   🔵 {ttype}  🟢 Arr: {arr}  🔴 Dep: {dep}\n\n"
        if len(trains) > 10:
            msg += f"_...aur {len(trains)-10} trains_"
        return msg
    except:
        return txt(lang, "❌ Data parse nahi hua!", "❌ Could not parse!")

def format_between(data, lang, from_stn, to_stn):
    try:
        limit = check_limit(data, lang)
        if limit: return limit
        trains = data.get("data", [])
        if not trains:
            return txt(lang, "❌ Koi train nahi mili!", "❌ No trains found!")
        msg = f"🔍 *Trains: {from_stn} → {to_stn}*\n━━━━━━━━━━━━━━━━━\n\n"
        for t in trains[:10]:
            tno   = t.get("train_number", t.get("trainNumber", "—"))
            tname = t.get("train_name", t.get("trainName", "—"))
            dep   = t.get("from_std", t.get("departureTime", "—"))
            arr   = t.get("to_sta", t.get("arrivalTime", "—"))
            dur   = t.get("duration", "—")
            days  = t.get("run_days", [])
            days_str = ", ".join(days) if isinstance(days, list) else "—"
            msg  += f"🚂 *{tno}* - {tname}\n"
            msg  += f"   🟢 Dep: {dep}  🔴 Arr: {arr}  ⏱️ {dur}\n"
            msg  += f"   📅 {days_str}\n\n"
        if len(trains) > 10:
            msg += f"_...aur {len(trains)-10} trains_"
        return msg
    except:
        return txt(lang, "❌ Data parse nahi hua!", "❌ Could not parse!")

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid, update.effective_user.username)
    await update.message.reply_text(
        "🚂 *Indian Railway Bot*\n━━━━━━━━━━━━━━━━━\n\n"
        "Namaste! 🙏\n\n"
        "✅ PNR Status\n✅ Train Schedule\n✅ Live Train Status\n"
        "✅ Trains Between Stations\n✅ Station Board\n"
        "✅ Favourites & Alerts\n\n"
        "Neeche se option chuno 👇",
        reply_markup=main_keyboard(get_lang(uid)), parse_mode="Markdown")
    return ConversationHandler.END

# ================= PNR =================
async def pnr_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    await update.message.reply_text(
        txt(lang, "🎫 *PNR Status*\n\nApna 10 digit PNR bhejo 👇\n_Example: 8448678822_",
                  "🎫 *PNR Status*\n\nEnter 10 digit PNR 👇\n_Example: 8448678822_"),
        parse_mode="Markdown")
    return PNR_INPUT

async def pnr_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    lang = get_lang(uid)
    pnr  = update.message.text.strip()
    if not pnr.isdigit() or len(pnr) != 10:
        await update.message.reply_text(txt(lang, "❌ 10 digit PNR daalo!", "❌ Enter valid 10 digit PNR!"))
        return PNR_INPUT
    msg    = await update.message.reply_text(txt(lang, "⏳ PNR check ho raha hai...", "⏳ Checking PNR..."))
    data   = api_pnr(pnr)
    result = format_pnr(data, lang)
    save_history(uid, "PNR", pnr, result)
    await msg.edit_text(result, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Refresh", callback_data=f"pnr_{pnr}"),
            InlineKeyboardButton("🔔 Alert",   callback_data=f"alert_pnr_{pnr}")
        ]]))
    return ConversationHandler.END

# ================= TRAIN SCHEDULE =================
async def schedule_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    await update.message.reply_text(
        txt(lang, "🚂 *Train Schedule*\n\nTrain number bhejo 👇\n_Example: 22177_",
                  "🚂 *Train Schedule*\n\nEnter train number 👇\n_Example: 22177_"),
        parse_mode="Markdown")
    return TRAIN_INPUT

async def schedule_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid      = update.effective_user.id
    lang     = get_lang(uid)
    train_no = update.message.text.strip()
    if not train_no.isdigit():
        await update.message.reply_text(txt(lang, "❌ Sahi train number daalo!", "❌ Enter valid train number!"))
        return TRAIN_INPUT
    msg    = await update.message.reply_text(txt(lang, "⏳ Schedule aa raha hai...", "⏳ Fetching schedule..."))
    data   = api_schedule(train_no)
    result = format_schedule(data, lang)
    save_history(uid, "SCHEDULE", train_no, result)
    await msg.edit_text(result, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⭐ Favourite", callback_data=f"fav_add_{train_no}"),
            InlineKeyboardButton("📍 Live",      callback_data=f"live_{train_no}")
        ]]))
    return ConversationHandler.END

# ================= LIVE STATUS =================
async def live_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    await update.message.reply_text(
        txt(lang, "📍 *Live Train*\n\nTrain number bhejo 👇\n_Example: 22177_",
                  "📍 *Live Train*\n\nEnter train number 👇\n_Example: 22177_"),
        parse_mode="Markdown")
    return LIVE_INPUT

async def live_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid      = update.effective_user.id
    lang     = get_lang(uid)
    train_no = update.message.text.strip()
    if not train_no.isdigit():
        await update.message.reply_text(txt(lang, "❌ Sahi train number daalo!", "❌ Enter valid train number!"))
        return LIVE_INPUT
    msg    = await update.message.reply_text(txt(lang, "⏳ Live status aa raha hai...", "⏳ Fetching live status..."))
    data   = api_live(train_no)
    result = format_live(data, lang)
    save_history(uid, "LIVE", train_no, result)
    await msg.edit_text(result, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Refresh",    callback_data=f"live_{train_no}"),
            InlineKeyboardButton("🔔 Late Alert", callback_data=f"alert_train_{train_no}")
        ]]))
    return ConversationHandler.END

# ================= STATION BOARD =================
async def station_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    await update.message.reply_text(
        txt(lang, "🏛️ *Station Board*\n\nStation code bhejo 👇\n_Example: CSMT, NDLS, PUNE_",
                  "🏛️ *Station Board*\n\nEnter station code 👇\n_Example: CSMT, NDLS, PUNE_"),
        parse_mode="Markdown")
    return STATION_INPUT

async def station_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    lang = get_lang(uid)
    stn  = update.message.text.strip().lower()
    msg  = await update.message.reply_text(txt(lang, "⏳ Station board aa raha hai...", "⏳ Fetching station board..."))
    data = api_station(stn)
    result = format_station(data, lang, stn)
    save_history(uid, "STATION", stn.upper(), result)
    await msg.edit_text(result, parse_mode="Markdown")
    return ConversationHandler.END

# ================= TRAINS BETWEEN =================
async def between_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    await update.message.reply_text(
        txt(lang, "🔍 *Trains Between Stations*\n\nFrom station code bhejo 👇\n_Example: CSMT_",
                  "🔍 *Trains Between Stations*\n\nEnter FROM station code 👇\n_Example: CSMT_"),
        parse_mode="Markdown")
    return BETWEEN_FROM

async def between_to_fn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    context.user_data["between_from"] = update.message.text.strip().upper()
    await update.message.reply_text(
        txt(lang, "📍 To station code bhejo 👇\n_Example: NDLS_",
                  "📍 Enter TO station code 👇\n_Example: NDLS_"),
        parse_mode="Markdown")
    return BETWEEN_TO

async def between_date_fn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    context.user_data["between_to"] = update.message.text.strip().upper()
    await update.message.reply_text(
        txt(lang, "📅 Date bhejo (YYYYMMDD format) 👇\n_Example: 20260609_",
                  "📅 Enter date (YYYYMMDD) 👇\n_Example: 20260609_"),
        parse_mode="Markdown")
    return BETWEEN_DATE

async def between_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid      = update.effective_user.id
    lang     = get_lang(uid)
    date     = update.message.text.strip()
    from_stn = context.user_data.get("between_from", "")
    to_stn   = context.user_data.get("between_to", "")
    msg      = await update.message.reply_text(txt(lang, "⏳ Trains dhundh raha hun...", "⏳ Searching trains..."))
    data     = api_between(from_stn, to_stn, date)
    result   = format_between(data, lang, from_stn, to_stn)
    save_history(uid, "BETWEEN", f"{from_stn}-{to_stn}", result)
    await msg.edit_text(result, parse_mode="Markdown")
    return ConversationHandler.END

# ================= FAVOURITES =================
async def favourites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    lang = get_lang(uid)
    c.execute("SELECT train_no, train_name FROM favourite_trains WHERE user_id=?", (uid,))
    rows = c.fetchall()
    if not rows:
        await update.message.reply_text(
            txt(lang, "⭐ Koi favourite nahi!\n\nTrain schedule dekh ke ⭐ save karo.",
                      "⭐ No favourites!\n\nSearch a train and save to favourites."),
            parse_mode="Markdown")
        return
    msg  = "⭐ *Favourite Trains*\n\n"
    btns = []
    for tno, tname in rows:
        msg += f"🚂 {tno} - {tname or 'Unknown'}\n"
        btns.append([
            InlineKeyboardButton(f"📍 Live: {tno}", callback_data=f"live_{tno}"),
            InlineKeyboardButton("🗑️ Remove",       callback_data=f"fav_rm_{tno}")
        ])
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(btns), parse_mode="Markdown")

# ================= HISTORY =================
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    lang = get_lang(uid)
    c.execute("SELECT type,query,searched_at FROM journey_history WHERE user_id=? ORDER BY searched_at DESC LIMIT 10", (uid,))
    rows = c.fetchall()
    if not rows:
        await update.message.reply_text(txt(lang, "📜 Koi history nahi!", "📜 No history!"))
        return
    msg = "📜 *Search History*\n\n"
    for qtype, query, ts in rows:
        date = time.strftime("%d/%m %I:%M%p", time.localtime(ts))
        msg += f"🔹 {qtype}: `{query}` — {date}\n"
    await update.message.reply_text(msg, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ Clear History", callback_data="clear_history")]]))

# ================= ALERTS =================
async def alerts_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    lang = get_lang(uid)
    c.execute("SELECT id,type,train_no,pnr FROM alerts WHERE user_id=? AND active=1", (uid,))
    rows = c.fetchall()
    msg  = "🔔 *Active Alerts*\n\n"
    btns = []
    if not rows:
        msg += txt(lang, "Koi alert nahi!\nPNR ya Train check karte waqt set karo.", "No alerts set!")
    for aid, atype, tno, pnr in rows:
        label = f"PNR: {pnr}" if atype == "PNR" else f"Train: {tno}"
        msg  += f"🔔 {atype} — {label}\n"
        btns.append([InlineKeyboardButton(f"❌ Remove #{aid}", callback_data=f"alert_rm_{aid}")])
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(btns) if btns else None, parse_mode="Markdown")

# ================= HELP =================
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ *Railway Bot — Help*\n━━━━━━━━━━━━━━━━━\n\n"
        "🎫 *PNR Status* — Ticket ka current status\n"
        "🚂 *Train Schedule* — Train ke sare stops\n"
        "📍 *Live Train* — Abhi kahan hai train\n"
        "🔍 *Trains Between* — Do stations ke beech trains\n"
        "🏛️ *Station Board* — Station pe aane wali trains\n"
        "⭐ *Favourites* — Apni trains save karo\n"
        "📜 *History* — Purane searches\n"
        "🔔 *Alerts* — Alert set karo\n"
        "🌐 *Language* — Hindi / English\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "🆘 Helpline: *139* | RPF: *182* | Medical: *138*",
        parse_mode="Markdown")

# ================= LANGUAGE =================
async def language_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌐 *Language*\n\nChuno / Select:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🇮🇳 Hindi",   callback_data="lang_hi"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")
        ]]), parse_mode="Markdown")

# ================= CALLBACK =================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = query.from_user.id
    lang  = get_lang(uid)
    data  = query.data
    await query.answer()

    if data.startswith("pnr_"):
        pnr    = data[4:]
        result = format_pnr(api_pnr(pnr), lang)
        await query.edit_message_text(result, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Refresh", callback_data=f"pnr_{pnr}"),
                InlineKeyboardButton("🔔 Alert",   callback_data=f"alert_pnr_{pnr}")
            ]]))

    elif data.startswith("live_"):
        tno    = data[5:]
        result = format_live(api_live(tno), lang)
        await query.edit_message_text(result, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Refresh",    callback_data=f"live_{tno}"),
                InlineKeyboardButton("🔔 Late Alert", callback_data=f"alert_train_{tno}")
            ]]))

    elif data.startswith("fav_add_"):
        tno = data[8:]
        c.execute("INSERT OR IGNORE INTO favourite_trains (user_id,train_no) VALUES (?,?)", (uid, tno))
        conn.commit()
        await query.answer("⭐ Favourite mein add!", show_alert=True)

    elif data.startswith("fav_rm_"):
        tno = data[7:]
        c.execute("DELETE FROM favourite_trains WHERE user_id=? AND train_no=?", (uid, tno))
        conn.commit()
        await query.answer("🗑️ Remove ho gaya!", show_alert=True)

    elif data == "clear_history":
        c.execute("DELETE FROM journey_history WHERE user_id=?", (uid,))
        conn.commit()
        await query.edit_message_text("🗑️ History clear ho gayi!")

    elif data.startswith("alert_pnr_"):
        pnr = data[10:]
        c.execute("INSERT INTO alerts (user_id,type,pnr,created_at) VALUES (?,?,?,?)", (uid,"PNR",pnr,int(time.time())))
        conn.commit()
        await query.answer("🔔 Alert set ho gaya!", show_alert=True)

    elif data.startswith("alert_train_"):
        tno = data[12:]
        c.execute("INSERT INTO alerts (user_id,type,train_no,created_at) VALUES (?,?,?,?)", (uid,"TRAIN",tno,int(time.time())))
        conn.commit()
        await query.answer("🔔 Alert set ho gaya!", show_alert=True)

    elif data.startswith("alert_rm_"):
        aid = int(data[9:])
        c.execute("UPDATE alerts SET active=0 WHERE id=? AND user_id=?", (aid, uid))
        conn.commit()
        await query.answer("❌ Alert remove ho gaya!", show_alert=True)

    elif data.startswith("lang_"):
        new_lang = data[5:]
        c.execute("UPDATE users SET language=? WHERE user_id=?", (new_lang, uid))
        conn.commit()
        await query.edit_message_text(txt(new_lang, "✅ Hindi set ho gayi!", "✅ English set!"))

# ================= TEXT HANDLER =================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid  = update.effective_user.id
    ensure_user(uid, update.effective_user.username)
    if text == "🎫 PNR Status":       return await pnr_start(update, context)
    elif text == "🚂 Train Schedule": return await schedule_start(update, context)
    elif text == "📍 Live Train":     return await live_start(update, context)
    elif text == "🔍 Trains Between": return await between_start(update, context)
    elif text == "🏛️ Station Board": return await station_start(update, context)
    elif text == "⭐ Favourites":     return await favourites(update, context)
    elif text == "📜 History":        return await history(update, context)
    elif text == "🔔 Alerts":         return await alerts_menu(update, context)
    elif text == "🌐 Language":       return await language_menu(update, context)
    elif text == "ℹ️ Help":           return await help_cmd(update, context)

# ================= ERROR =================
async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    import traceback
    print(f"[ERROR] {context.error}")
    traceback.print_exc()

# ================= RUN =================
app = (
    ApplicationBuilder()
    .token(TOKEN)
    .connect_timeout(30)
    .read_timeout(30)
    .write_timeout(30)
    .pool_timeout(30)
    .build()
)

conv_pnr = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^🎫 PNR Status$"), pnr_start)],
    states={PNR_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pnr_check)]},
    fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
)
conv_schedule = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^🚂 Train Schedule$"), schedule_start)],
    states={TRAIN_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_check)]},
    fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
)
conv_live = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^📍 Live Train$"), live_start)],
    states={LIVE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, live_check)]},
    fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
)
conv_station = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^🏛️ Station Board$"), station_start)],
    states={STATION_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, station_check)]},
    fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
)
conv_between = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^🔍 Trains Between$"), between_start)],
    states={
        BETWEEN_FROM: [MessageHandler(filters.TEXT & ~filters.COMMAND, between_to_fn)],
        BETWEEN_TO:   [MessageHandler(filters.TEXT & ~filters.COMMAND, between_date_fn)],
        BETWEEN_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, between_check)],
    },
    fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
)

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help",  help_cmd))
app.add_handler(conv_pnr)
app.add_handler(conv_schedule)
app.add_handler(conv_live)
app.add_handler(conv_station)
app.add_handler(conv_between)
app.add_handler(CallbackQueryHandler(callback_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_error_handler(error_handler)

print("🚂 INDIAN RAILWAY BOT RUNNING!")
app.run_polling(drop_pending_updates=True, allowed_updates=["message", "callback_query"])
