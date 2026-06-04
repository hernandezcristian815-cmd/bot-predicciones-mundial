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
    return "Bot Predictivo PRO Automatizado en Vivo", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# Ligas principales (Champions=2, Premier=39, LaLiga=140, Serie A=135, Colombia=239)
LEAGUE_IDS = [2, 39, 140, 135, 239]

def consultar_api_por_fecha(fecha_str):
    """Consulta la API de Fútbol para una fecha específica en formato YYYY-MM-DD"""
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {
        'x-rapidapi-host': 'v3.football.api-sports.io',
        'x-rapidapi-key': API_FOOTBALL_KEY
    }
    partidos_encontrados = []
    
    for league_id in LEAGUE_IDS:
        params = {'date': fecha_str, 'league': league_id}
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10).json()
            if "response" in response:
                for item in response["response"]:
                    partidos_encontrados.append({
                        "home": item["teams"]["home"]["name"],
                        "away": item["teams"]["away"]["name"]
                    })
        except Exception as e:
            print(f"Error consultando liga {league_id} en fecha {fecha_str}: {e}")
            
    return partidos_encontrados

# Comando /start o /ayuda para ver la lista de comandos
@bot.message_handler(commands=['start', 'ayuda', 'help'])
def enviar_lista_comandos(message):
    texto_ayuda = (
        "🤖 *¡Bienvenido al Centro de Analítica Deportiva IA!*\n\n"
        "Aquí tienes la lista de comandos disponibles para el grupo:\n\n"
        "⚽ `/polla` o `/partidos` \- Consulta la cartelera futbolera real (busca hoy y si no hay, te muestra mañana) con botones interactivos\.\n"
        "ℹ️ `/ayuda` o `/start` \- Despliega este menú de asistencia con los comandos disponibles\.\n\n"
        "_Selecciona un partido desde el menú interactivo para recibir un informe profundo de apuestas (Goles, Córners, Tarjetas y Marcador)_"
    )
    bot.send_message(message.chat.id, texto_ayuda, parse_mode="MarkdownV2")

# Comando /polla o /partidos con lógica inteligente hoy/mañana
@bot.message_handler(commands=['polla', 'partidos'])
def enviar_menu_dinamico(message):
    bot.send_message(message.chat.id, "🔍 Buscando partidos en la base de datos de la API...")
    
    ahora = datetime.datetime.now()
    fecha_hoy = ahora.strftime('%Y-%m-%d')
    fecha_manana = (ahora + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    
    # 1. Intentar buscar partidos de HOY
    lista_partidos = consultar_api_por_fecha(fecha_hoy)
    titulo_menu = "⚽ *¡Cartelera de HOY\!*"
    
    # 2. Si no hay partidos hoy, saltar automáticamente a MAÑANA
    if not lista_partidos:
        print("No se encontraron partidos para hoy, buscando cartelera de mañana...")
        lista_partidos = consultar_api_por_fecha(fecha_manana)
        titulo_menu = "🗓️ *Sin partidos hoy. ¡Cartelera de MAÑANA\!*"
        
    if not lista_partidos:
        bot.send_message(message.chat.id, "⏳ Por el momento no se reportan encuentros disponibles para hoy ni mañana en las ligas principales.")
        return
        
    markup = InlineKeyboardMarkup()
    markup.row_width = 1
    
    # Generamos los botones cuidando el límite de 64 bytes de Telegram en el callback
    for i, partido in enumerate(lista_partidos[:15]): # Límite de 15 botones para no saturar
        home_corto = partido['home'][:25]
        away_corto = partido['away'][:25]
        texto_boton = f"{partido['home']} vs. {partido['away']}"
        callback_data = f"p_{i}_{home_corto} vs {away_corto}"[:60]
        
        markup.add(InlineKeyboardButton(texto_boton, callback_data=callback_data))
        
    bot.send_message(
        message.chat.id, 
        f"{titulo_menu}\nSelecciona un encuentro para desplegar el análisis avanzado de apuestas con IA:", 
        parse_mode="MarkdownV2", 
        reply_markup=markup
    )

# Manejador interactivo PRO (Análisis completo de apuestas con Gemini)
@bot.callback_query_handler(func=lambda call: True)
def procesar_prediccion_ia(call):
    bot.answer_callback_query(call.id, text="Calculando Big Data, córners y tarjetas...")
    
    try:
        # Extraer el texto del partido limpiando el índice de control
        partido_nombre = call.data.split('_', 2)[-1]
        
        prompt = (
            f"Actúa como un tipster profesional, experto en Big Data de fútbol y analítica deportiva avanzada. "
            f"Genera un reporte de apuestas ultra profundo y realista para el partido: {partido_nombre}.\n\n"
            f"Basándote en tu conocimiento estadístico e histórico global, calcula las probabilidades reales "
            f"y estructura tu respuesta EXACTAMENTE con el siguiente formato Markdown para Telegram (usa emojis y negritas):\n\n"
            f"📊 *REPORTE PRO IA: [Nombre del Partido]*\n\n"
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
            f"3️⃣ [Tip arriesgado de alta cuota, ej: Local anota en el 2do tiempo]\n\n"
            f"_*Nota: Análisis matemático basado en tendencias estadísticas de rendimiento actual\._"
        )
        
        response = model.generate_content(prompt)
        analisis_final = response.text
        
        # Reemplazar puntos sueltos para evitar que se rompa el MarkdownV2 de Telegram si es necesario
        bot.send_message(call.message.chat.id, analisis_final, parse_mode="Markdown")
        
    except Exception as e:
        print(f"Error procesando la IA Avanzada: {e}")
        bot.send_message(call.message.chat.id, "❌ No logré procesar el análisis detallado en este momento. Inténtalo de nuevo.")

if __name__ == "__main__":
    print("Iniciando servidor web...")
    server_thread = Thread(target=run_flask)
    server_thread.start()
    
    print("Bot interactivo con IA PRO corriendo...")
    bot.infinity_polling()
