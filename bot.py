import os
import requests
import telebot
import google.generativeai as genai
from flask import Flask
from threading import Thread
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")
API_KEY = os.getenv("API_FOOTBALL_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

genai.configure(api_key=GEMINI_KEY)
modelo = genai.GenerativeModel("gemini-1.5-flash")

HEADERS = {
    "x-apisports-key": API_KEY
}

# Flask para Render
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot activo"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# Partidos de hoy
@bot.message_handler(commands=["hoy"])
def partidos_hoy(message):

    fecha = datetime.now().strftime("%Y-%m-%d")

    url = f"https://v3.football.api-sports.io/fixtures?date={fecha}"

    r = requests.get(url, headers=HEADERS)
    data = r.json()

    fixtures = data["response"][:15]

    texto = "⚽ PARTIDOS DE HOY\n\n"

    for f in fixtures:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        liga = f["league"]["name"]
        fid = f["fixture"]["id"]

        texto += f"🆔 {fid}\n{home} vs {away}\n🏆 {liga}\n\n"

    bot.reply_to(message, texto)

# Analizar partido
@bot.message_handler(commands=["analizar"])
def analizar(message):

    try:
        fixture_id = message.text.split()[1]

        url = f"https://v3.football.api-sports.io/fixtures?id={fixture_id}"

        r = requests.get(url, headers=HEADERS)
        data = r.json()

        partido = data["response"][0]

        local = partido["teams"]["home"]["name"]
        visitante = partido["teams"]["away"]["name"]
        liga = partido["league"]["name"]

        prompt = f"""
        Analiza estadísticamente este partido.

        Local: {local}
        Visitante: {visitante}
        Liga: {liga}

        Describe fortalezas, debilidades,
        rendimiento reciente y datos relevantes.

        No recomiendes apuestas.
        """

        respuesta = modelo.generate_content(prompt)

        bot.reply_to(
            message,
            f"📊 {local} vs {visitante}\n\n{respuesta.text[:4000]}"
        )

    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(
        message,
        "⚽ Bot de análisis de fútbol\n\n"
        "/hoy -> cartelera del día\n"
        "/analizar ID -> análisis de un partido"
    )

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling(skip_pending=True)