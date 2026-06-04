import os
import telebot
import requests
from flask import Flask
from threading import Thread

# 1. CONFIGURACIÓN
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
FOOTBALL_API_KEY = "B84749a157ea4c37ba11fd237d62c74a" # Tu API Key
HEADERS = {'X-Auth-Token': FOOTBALL_API_KEY}

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# 2. SERVIDOR MANTENIMIENTO (Render)
@app.route('/')
def home():
    return "Bot de Datos Reales Activo", 200

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

# 3. COMANDOS PRINCIPALES
@bot.message_handler(commands=['start', 'partidos'])
def listar_partidos(message):
    url = "https://api.football-data.org/v4/matches?status=TIMED"
    try:
        response = requests.get(url, headers=HEADERS).json()
        matches = response['matches'][:8]
        
        texto = "⚽ **PARTIDOS DE HOY**\n\n"
        for m in matches:
            # Creamos un botón con el match_id real
            h = m['homeTeam']['name']
            a = m['awayTeam']['name']
            m_id = m['id']
            texto += f"🔹 {h} vs {a}\n/ver_{m_id}\n\n"
        
        bot.reply_to(message, texto, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, "❌ Error al conectar con la base de datos.")

# 4. MOTOR DE ESTADÍSTICAS REALES (Por ID de partido)
@bot.message_handler(func=lambda message: message.text.startswith('/ver_'))
def ver_estadisticas(message):
    match_id = message.text.split('_')[1]
    url = f"https://api.football-data.org/v4/matches/{match_id}"
    
    try:
        data = requests.get(url, headers=HEADERS).json()
        h = data['homeTeam']['name']
        a = data['awayTeam']['name']
        
        # Obtenemos estadísticas si están disponibles
        reporte = f"📊 **DATOS OFICIALES**\n"
        reporte += f"⚽ {h} vs {a}\n\n"
        reporte += f"🏠 Goles {h}: {data['score']['fullTime']['home']}\n"
        reporte += f"✈️ Goles {a}: {data['score']['fullTime']['away']}\n"
        reporte += f"🏆 Competición: {data['competition']['name']}\n"
        reporte += f"⏰ Estado: {data['status']}"
        
        bot.reply_to(message, reporte, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, "❌ No hay estadísticas detalladas para este partido aún.")

# 5. ARRANQUE
if __name__ == "__main__":
    Thread(target=run_flask).start()
    print("Bot Estadístico Real Corriendo...")
    bot.infinity_polling()
