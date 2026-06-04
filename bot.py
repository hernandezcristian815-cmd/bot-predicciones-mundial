import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
from threading import Thread

# Configuración del Bot con tus datos reales
TOKEN = "8837935575:AAG8uUQN2Nto0bAV8BZggEwgAIg4g3r-KPk"
bot = telebot.TeleBot(TOKEN)

# Servidor Flask para mantener vivo el puerto en Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot está vivo y corriendo", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# Cartelera simulada con los datos dinámicos
PARTIDOS_HOY = {
    "partido_1": {
        "equipos": "Real Madrid vs. Barcelona",
        "texto": "📊 *REPORTE IA: Real Madrid vs. Barcelona*\n\n• Victoria Local: 46.2% 🟢\n• Empate: 23.5% 🟡\n• Victoria Visitante: 30.3% 🔴\n\n_Marcador probable: 2 - 1_"
    },
    "partido_2": {
        "equipos": "Manchester City vs. Liverpool",
        "texto": "📊 *REPORTE IA: Manchester City vs. Liverpool*\n\n• Victoria Local: 51.8% 🟢\n• Empate: 22.0% 🟡\n• Victoria Visitante: 26.2% 🔴\n\n_Marcador probable: 3 - 1_"
    },
    "partido_3": {
        "equipos": "Bayern Múnich vs. Dortmund",
        "texto": "📊 *REPORTE IA: Bayern Múnich vs. Dortmund*\n\n• Victoria Local: 58.7% 🟢\n• Empate: 18.4% 🟡\n• Victoria Visitante: 22.9% 🔴\n\n_Marcador probable: 3 - 2_"
    }
}

@bot.message_handler(commands=['polla', 'partidos'])
def enviar_menu_partidos(message):
    markup = InlineKeyboardMarkup()
    markup.row_width = 1
    
    for key, info in PARTIDOS_HOY.items():
        markup.add(InlineKeyboardButton(info["equipos"], callback_data=key))
        
    bot.send_message(
        message.chat.id, 
        "⚽ *¡Cartelera futbolera del día!*\nSelecciona un partido para ver el análisis predictivo de la IA:", 
        parse_mode="Markdown", 
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: True)
def procesar_seleccion(call):
    id_partido = call.data
    if id_partido in PARTIDOS_HOY:
        analisis = PARTIDOS_HOY[id_partido]["texto"]
        bot.send_message(call.message.chat.id, analisis, parse_mode="Markdown")
        bot.answer_callback_query(call.id, text="Análisis generado con éxito")

if __name__ == "__main__":
    print("Iniciando servidor web...")
    server_thread = Thread(target=run_flask)
    server_thread.start()
    
    print("Bot corriendo con éxito...")
    bot.infinity_polling()
