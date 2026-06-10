import os
import requests
import datetime
from telebot import TeleBot, types
from scipy.stats import poisson

# Configuración de Tokens desde tus variables de entorno en Render
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "TU_TELEGRAM_TOKEN")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY", "TU_API_KEY_RAPIDAPI")
bot = TeleBot(TOKEN)

# ----------------------------------------------------------------------
# 1. GENERADOR DE BARRAS VISUALES (Estilo la imagen del Reel)
# ----------------------------------------------------------------------
def make_bar(percentage, color_emoji="🟩", length=12):
    filled = int((percentage / 100) * length)
    filled = max(1, min(filled, length)) # Asegurar mínimo 1 bloque
    empty = length - filled
    return f"{color_emoji * filled}{'⬛' * empty}"

# ----------------------------------------------------------------------
# 2. MOTOR MATEMÁTICO (Poisson para xG, Tarjetas y Corners)
# ----------------------------------------------------------------------
def calculate_advanced_stats(xg_local, xg_visitante):
    # Valores de ejemplo basados en promedios que simulan la API
    cards_esperadas = 4.3
    over_cards_prob = 62
    corners_esperados = 10.0
    over_corners_prob = 54
    
    # Poisson básico para el Over/Under de goles
    prob_under25 = 0.0
    for h in range(4):
        for a in range(4):
            if (h + a) <= 2.5:
                prob_under25 += poisson.pmf(h, xg_local) * poisson.pmf(a, xg_visitante)
    
    over25_prob = round((1 - prob_under25) * 100)
    btts_si = round((1 - poisson.pmf(0, xg_local)) * (1 - poisson.pmf(0, xg_visitante)) * 100)
    
    return {
        "cards": cards_esperadas, "cards_prob": over_cards_prob,
        "corners": corners_esperados, "corners_prob": over_corners_prob,
        "btts": btts_si, "over25": over25_prob
    }

# ----------------------------------------------------------------------
# 3. CONTROLADORES DE TELEGRAM (Calendario interactivo)
# ----------------------------------------------------------------------
@bot.message_handler(commands=['start', 'menu'])
def send_welcome(message):
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    
    # Generamos los próximos 4 días del Mundial de forma dinámica
    base_date = datetime.date(2026, 6, 11) # Inicio del Mundial
    for i in range(4):
        current_date = base_date + datetime.timedelta(days=i)
        date_str = current_date.strftime("%Y-%m-%d")
        nice_format = current_date.strftime("%A, %d de %B")
        
        keyboard.add(types.InlineKeyboardButton(text=f"📅 {nice_format}", callback_data=f"date_{date_str}"))
        
    bot.send_message(
        message.chat_id if hasattr(message, 'chat_id') else message.chat.id,
        "🤖 *TERMINAL IA — MUNDIAL 2026*\n\nSelecciona una fecha del calendario para cargar los partidos del día:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('date_'))
def handle_date_selection(call):
    selected_date = call.data.split('_')[1]
    
    # Simulación de respuesta de tu API de Football Data para esa fecha
    # En producción harías: requests.get(f"URL_API?date={selected_date}")
    mock_matches = {
        "2026-06-11": [{"id": "101", "teams": "USA vs México", "time": "16:00"}],
        "2026-06-12": [{"id": "102", "teams": "Argentina vs Alemania", "time": "13:00"},
                       {"id": "103", "teams": "España vs Portugal", "time": "19:00"}],
        "2026-06-13": [{"id": "104", "teams": "Colombia vs Italia", "time": "15:00"}]
    }
    
    matches = mock_matches.get(selected_date, [])
    
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    if not matches:
        keyboard.add(types.InlineKeyboardButton(text="⬅️ Volver al menú", callback_data="back_menu"))
        bot.edit_message_text("❌ No hay partidos programados o cargados para esta fecha.", call.message.chat.id, call.message.message_id, reply_markup=keyboard)
        return

    for m in matches:
        keyboard.add(types.InlineKeyboardButton(text=f"⚽ [{m['time']}] {m['teams']}", callback_data=f"match_{m['id']}"))
    
    keyboard.add(types.InlineKeyboardButton(text="⬅️ Cambiar de fecha", callback_data="back_menu"))
    bot.edit_message_text(f"👇 *PARTIDOS PARA EL {selected_date}:*\nSelecciona uno para correr el modelo estadístico:", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data == "back_menu")
def handle_back_menu(call):
    # Permite regresar al calendario principal de fechas
    send_welcome(call.message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('match_'))
def handle_match_analysis(call):
    match_id = call.data.split('_')[1]
    
    # Mapeo básico de datos para el análisis
    match_names = {"101": ("USA", "MÉXICO"), "102": ("ARGENTINA", "ALEMANIA"), "103": ("ESPAÑA", "PORTUGAL"), "104": ("COLOMBIA", "ITALIA")}
    local, visitante = match_names.get(match_id, ("LOCAL", "VISITANTE"))

    # Datos base de xG obtenidos de tu API-Football o procesados por Groq/Gemini
    xg_local, xg_visitante = 1.03, 0.46
    stats = calculate_advanced_stats(xg_local, xg_visitante)
    
    # ----------------------------------------------------------------------
    # CONSTRUCCIÓN DEL LOOK VISUAL ESTILO TERMINAL (Como en la foto)
    # ----------------------------------------------------------------------
    terminal_template = (
        f"📊 *TERMINAL DATA — PROYECCIÓN IA*\n"
        f"`------------------------------------------`\n"
        f"       *XG LOCAL* *XG VISITANTE*\n"
        f"      * {xg_local} * * {xg_visitante} *\n"
        f"`------------------------------------------`\n\n"
        
        f"⚽ *LÍNEAS DE GOLES PROYECTADOS*\n"
        f"1.5  {make_bar(85, '🟩')}\n"
        f"2.5  {make_bar(stats['over25'], '🟦')}\n"
        f"3.5  {make_bar(20, '🟨')}\n\n"
        
        f"🔄 *AMBOS MARCAN (BTTS)*\n"
        f"SÍ: *{stats['btts']}%* | NO: *{100 - stats['btts']}%*\n"
        f"{make_bar(stats['btts'], '🟩', length=16)}\n\n"
        
        f"🟨 *TARJETAS*\n"
        f"Esperadas: *{stats['cards']}* | Over 3.5: *{stats['cards_prob']}%*\n"
        f"{make_bar(stats['cards_prob'], '🟥', length=16)}\n\n"
        
        f"🚩 *CORNERS*\n"
        f"Esperados: *{stats['corners']}* | Over 9.5: *{stats['corners_prob']}%*\n"
        f"{make_bar(stats['corners_prob'], '🟪', length=16)}\n"
        f"`------------------------------------------`\n"
        f"🤖 _Análisis estadístico de entretenimiento._"
    )
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="🔄 Analizar otro partido", callback_data="back_menu"))
    
    bot.edit_message_text(
        text=terminal_template,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ----------------------------------------------------------------------
# Ejecución del Bot
# ----------------------------------------------------------------------
if __name__ == "__main__":
    print("🤖 Bot con interfaz Opta/Visual corriendo en Render...")
    bot.infinity_polling()
