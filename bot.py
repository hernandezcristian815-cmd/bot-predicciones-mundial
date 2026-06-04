import os
import datetime
import telebot
import requests
import google.generativeai as genai
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
from threading import Thread

# 1. CONFIGURACIÓN SEGURA DE LLAVES (Variables de Entorno)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8837935575:AAG8uUQN2Nto0bAV8BZggEwgAIg4g3r-KPk")
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY", "28bc5f100ca73109d8e71d0649f6a385")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

# Inicializar bots e IA
bot = telebot.TeleBot(TELEGRAM_TOKEN)
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-pro')

# Servidor Flask para Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Predictivo PRO Internacional en Vivo", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# Palabras clave para filtrar de forma inteligente las competiciones de alto valor e importancia internacional
PALABRAS_COMPETICION_TOP = [
    "friendlies", "international", "world cup", "euro", "copa america", "champions league", 
    "europa league", "premier league", "primera division", "liga betplay", "serie a", 
    "bundesliga", "ligue 1", "copa libertadores", "copa sudamericana", "liga mx"
]

def consultar_cartelera_importante(fecha_str):
    """Consulta todos los partidos del día y filtra dinámicamente los más importantes y comerciales"""
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {
        'x-rapidapi-host': 'v3.football.api-sports.io',
        'x-rapidapi-key': API_FOOTBALL_KEY
    }
    params = {'date': fecha_str}
    partidos_filtrados = []
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=12).json()
        if "response" in response and response["response"]:
            for item in response["response"]:
                nombre_liga = item["league"]["name"].lower()
                
                # Filtrar solo si pertenece a una competición o categoría de alto interés comercial
                if any(palabra in nombre_liga for palabra in PALABRAS_COMPETICION_TOP):
                    partidos_filtrados.append({
                        "home": item["teams"]["home"]["name"],
                        "away": item["teams"]["away"]["name"],
                        "league": item["league"]["name"]
                    })
    except Exception as e:
        print(f"Error consultando cartelera global: {e}")
        
    return partidos_filtrados

# Comando /start o /ayuda
@bot.message_handler(commands=['start', 'ayuda', 'help'])
def enviar_lista_comandos(message):
    texto_ayuda = (
        "🤖 *¡Bienvenido al Centro de Analítica Deportiva IA!*\n\n"
        "Aquí tienes los comandos para interactuar en el grupo:\n\n"
        "⚽ `/polla` o `/partidos` \- Despliega los partidos más importantes del planeta \(Selecciones, Copas y Ligas Top\) con botones interactivos\.\n"
        "ℹ️ `/ayuda` o `/start` \- Muestra este menú de asistencia\.\n\n"
        "_Presiona el botón de cualquier partido para generar el informe matemático avanzado para tus apuestas\._"
    )
    bot.send_message(message.chat.id, texto_ayuda, parse_mode="MarkdownV2")

# Comando /polla o /partidos mejorado
@bot.message_handler(commands=['polla', 'partidos'])
def enviar_menu_dinamico(message):
    bot.send_message(message.chat.id, "🔍 Analizando el calendario global de partidos importantes...")
    
    ahora = datetime.datetime.now()
    fecha_hoy = ahora.strftime('%Y-%m-%d')
    fecha_manana = (ahora + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    
    # 1. Buscar cartelera filtrada de Hoy
    lista_partidos = consultar_cartelera_importante(fecha_hoy)
    titulo_menu = "⚽ *¡Cartelera de HOY \(Competiciones Top\)\!*"
    
    # 2. Si hoy ya se cerró la jornada, saltar automáticamente a Mañana
    if not lista_partidos:
        print("No hay más partidos top hoy, consultando la agenda de mañana...")
        lista_partidos = consultar_cartelera_importante(fecha_manana)
        titulo_menu = "🗓️ *Agenda de MAÑANA \(Partidos Principales\)\!*"
        
    if not lista_partidos:
        bot.send_message(message.chat.id, "⏳ En este momento no se registran partidos comerciales de gran calibre programados para hoy ni mañana.")
        return
        
    markup = InlineKeyboardMarkup()
    markup.row_width = 1
    
    # Generamos los botones con un límite máximo de 18 para no saturar el chat de Telegram
    for i, partido in enumerate(lista_partidos[:18]):
        home_corto = partido['home'][:22]
        away_corto = partido['away'][:22]
        texto_boton = f"{partido['home']} vs. {partido['away']} ({partido['league'][:15]})"
        callback_data = f"p_{i}_{home_corto}?{away_corto}"[:64]
        
        markup.add(InlineKeyboardButton(texto_boton, callback_data=callback_data))
        
    bot.send_message(
        message.chat.id, 
        f"{titulo_menu}\nSelecciona un encuentro para desplegar el análisis predictivo avanzado de apuestas con IA:", 
        parse_mode="MarkdownV2", 
        reply_markup=markup
    )

# Manejador interactivo PRO (Análisis completo de apuestas con Gemini)
@bot.callback_query_handler(func=lambda call: True)
def procesar_prediccion_ia(call):
    bot.answer_callback_query(call.id, text="Calculando Big Data, córners y tarjetas...")
    
    try:
        # Extraer los nombres limpios del callback
        partido_datos = call.data.split('_', 2)[-1]
        home_team, away_team = partido_datos.split('?')
        
        prompt = (
            f"Actúa como un tipster profesional, experto en Big Data de fútbol y analítica deportiva avanzada. "
            f"Genera un reporte de apuestas ultra profundo y realista para el partido de fútbol: {home_team} vs {away_team}.\n\n"
            f"Basándote en tu conocimiento estadístico e histórico global de estos equipos/selecciones, calcula las probabilidades reales "
            f"y estructura tu respuesta EXACTAMENTE con el siguiente formato Markdown para Telegram (usa emojis y negritas):\n\n"
            f"📊 *REPORTE PRO IA: {home_team} vs. {away_team}*\n\n"
            f"💰 *PROBABILIDADES 1X2:*\n"
            f"• Victoria Local: [X]% 🟢\n"
            f"• Empate: [Y]% 🟡\n"
            f"• Victoria Visitante: [Z]% 🔴\n\n"
            f"⚽ *MERCADO DE GOLES:*\n"
            f"• Línea sugerida: Over/Under [Línea de goles, ej: 2.5]\n"
            f"• Ambos Anotan: [Sí/No] ([Porcentaje]% de probabilidad)\n"
            f"• Marcador exacto más probable: [Ej: 2 - 1]\n\n"
            f"📐 *CÓRNERS Y 🟨 TARJETAS (ESTIMADO):*\n"
            f"• Córners totales estimados: [Rango, ej: 8.5 - 10.5]\n"
            f"• Tarjetas totales estimadas: [Rango, ej: 3.5 - 4.5]\n"
            f"• Equipo con más control de juego: [Nombre del equipo]\n\n"
            f"🔥 *TOP 3 TIPS DE APUESTAS DE ALTO VALOR:*\n"
            f"1️⃣ [Tip principal, ej: Ganador Local o Empate]\n"
            f"2️⃣ [Tip de goles o córners, ej: Más de 8.5 córners]\n"
            f"3️⃣ [Tip arriesgado de alta cuota, ej: Ambos anotan en el 2do tiempo]\n\n"
            f"_*Nota: Análisis matemático basado en tendencias estadísticas globales\._"
        )
        
        response = model.generate_content(prompt)
        analisis_final = response.text
        
        bot.send_message(call.message.chat.id, analisis_final, parse_mode="Markdown")
        
    except Exception as e:
        print(f"Error procesando la IA Avanzada: {e}")
        bot.send_message(call.message.chat.id, "❌ No logré procesar el análisis detallado. Inténtalo de nuevo.")

if __name__ == "__main__":
    print("Iniciando servidor web...")
    server_thread = Thread(target=run_flask)
    server_thread.start()
    
    print("Bot interactivo con IA PRO Internacional corriendo...")
    bot.infinity_polling()
