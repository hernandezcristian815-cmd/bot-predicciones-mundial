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
GEMINI_KEY = os.environ.get("GEMINI_KEY") # Se lee directo de Render de forma oculta

# Inicializar bots e IA
bot = telebot.TeleBot(TELEGRAM_TOKEN)
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-pro')

# Servidor Flask para Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Predictivo Automatizado Oculto en Vivo", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# Ligas principales (Champions=2, Premier=39, LaLiga=140, Serie A=135, Colombia=239)
LEAGUE_IDS = [2, 39, 140, 135, 239]

def obtener_partidos_del_dia():
    """Consulta la API de Fútbol para traer los partidos programados"""
    ahora = datetime.datetime.now()
    
    # Si ya es tarde en la noche (pasadas las 8 PM), busca la cartelera de mañana
    if ahora.hour >= 20:
        fecha_busqueda = (ahora + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        fecha_busqueda = ahora.strftime('%Y-%m-%d')
        
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {
        'x-rapidapi-host': 'v3.football.api-sports.io',
        'x-rapidapi-key': API_FOOTBALL_KEY
    }
    
    partidos = {}
    contador = 1
    
    for league_id in LEAGUE_IDS:
        params = {'date': fecha_busqueda, 'league': league_id}
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10).json()
            if "response" in response:
                for item in response["response"]:
                    home_team = item["teams"]["home"]["name"]
                    away_team = item["teams"]["away"]["name"]
                    partido_texto = f"{home_team} vs. {away_team}"
                    
                    partidos[f"p_{contador}"] = {
                        "equipos": partido_texto,
                        "home": home_team,
                        "away": away_team
                    }
                    contador += 1
        except Exception as e:
            print(f"Error consultando liga {league_id}: {e}")
            
    return partidos

# Comando /polla o /partidos
@bot.message_handler(commands=['polla', 'partidos'])
def enviar_menu_dinamico(message):
    bot.send_message(message.chat.id, "🔍 Consultando bases de datos de la API en tiempo real...")
    
    partidos_hoy = obtener_partidos_del_dia()
    
    if not partidos_hoy:
        bot.send_message(message.chat.id, "⏳ Por el momento no se reportan partidos disponibles en las ligas principales.")
        return
        
    markup = InlineKeyboardMarkup()
    markup.row_width = 1
    
    for key, info in partidos_hoy.items():
        callback_data = f"{info['home']}?{info['away']}"
        if len(callback_data) <= 64:
            markup.add(InlineKeyboardButton(info["equipos"], callback_data=callback_data))
        
    bot.send_message(
        message.chat.id, 
        "⚽ *¡Cartelera Real Automatizada!*\nSelecciona un encuentro para que procese el reporte matemático con IA:", 
        parse_mode="Markdown", 
        reply_markup=markup
    )

# Manejador del botón interactivo (Llama a Gemini en vivo)
@bot.callback_query_handler(func=lambda call: True)
def procesar_prediccion_ia(call):
    bot.answer_callback_query(call.id, text="Analizando estadísticas con la IA...")
    
    try:
        home_team, away_team = call.data.split('?')
        
        prompt = (
            f"Actúa como un experto en analítica deportiva y Big Data de fútbol. "
            f"Genera un reporte predictivo para el partido: {home_team} vs {away_team}. "
            f"Calcula matemáticamente basándote en tu conocimiento histórico las probabilidades exactas "
            f"de: Victoria Local, Empate y Victoria Visitante (la suma debe dar 100%). "
            f"Calcula también el marcador exacto más probable de acuerdo a la estadística.\n\n"
            f"Devuelve la respuesta estrictamente con el siguiente formato Markdown para Telegram (usa emojis):\n"
            f"📊 *REPORTE IA: [Nombre Local] vs. [Nombre Visitante]*\n\n"
            f"• Victoria Local: [X]% 🟢\n"
            f"• Empate: [Y]% 🟡\n"
            f"• Victoria Visitante: [Z]% 🔴\n\n"
            f"_Marcador probable: [Resultado]_"
        )
        
        response = model.generate_content(prompt)
        analisis_final = response.text
        
        bot.send_message(call.message.chat.id, analisis_final, parse_mode="Markdown")
        
    except Exception as e:
        print(f"Error procesando la IA: {e}")
        bot.send_message(call.message.chat.id, "❌ No logré procesar el análisis. Inténtalo de nuevo por favor.")

if __name__ == "__main__":
    print("Iniciando servidor web...")
    server_thread = Thread(target=run_flask)
    server_thread.start()
    
    print("Bot interactivo con IA corriendo...")
    bot.infinity_polling()
