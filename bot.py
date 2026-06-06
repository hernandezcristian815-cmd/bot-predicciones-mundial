# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Motor Estadístico de Fútbol - Arquitectura Webhook

import os
import requests
import numpy as np
from scipy.stats import poisson
from google import genai
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# --- 1. CONFIGURACIÓN DE CREDENCIALES ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
FOOTBALL_API_KEY = os.getenv("API_FOOTBALL_KEY") 
GEMINI_API_KEY = os.getenv("GEMINI_KEY")

# Render inyecta automáticamente RENDER_EXTERNAL_URL en sus Web Services
WEB_URL = os.getenv("RENDER_EXTERNAL_URL", "https://tu-app.onrender.com") 
WEBHOOK_PATH = f"/webhook/{TELEGRAM_TOKEN}"
WEBHOOK_URL = f"{WEB_URL}{WEBHOOK_PATH}"

if not all([TELEGRAM_TOKEN, FOOTBALL_API_KEY, GEMINI_API_KEY]):
    raise ValueError("Faltan variables de entorno esenciales.")

# --- 2. INICIALIZACIÓN DE SERVICIOS ---
client = genai.Client(api_key=GEMINI_API_KEY)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# --- 3. FUNCIONES DE EXTRACCIÓN Y MATEMÁTICAS ---
def buscar_equipo(nombre_equipo):
    url = "https://v3.football.api-sports.io/teams"
    # Cambiamos a la cabecera oficial directa de API-Sports
    headers = {"x-apisports-key": FOOTBALL_API_KEY} 
    
    response = requests.get(url, headers=headers, params={"search": nombre_equipo})
    data = response.json().get("response", [])
    if data:
        return data[0]["team"]["id"], data[0]["team"]["name"]
    return None, None

def obtener_goles_promedio(equipo_id, liga_id=140, season="2025"):
    url = "https://v3.football.api-sports.io/teams/statistics"
    headers = {"x-apisports-key": FOOTBALL_API_KEY}
    
    response = requests.get(url, headers=headers, params={"team": equipo_id, "league": liga_id, "season": season})
    if response.status_code == 200:
        stats = response.json().get("response", {})
        try:
            return {
                "gf_home": float(stats['goals']['for']['average']['home']),
                "gc_home": float(stats['goals']['against']['average']['home']),
                "gf_away": float(stats['goals']['for']['average']['away']),
                "gc_away": float(stats['goals']['against']['average']['away'])
            }
        except:
            return None
    return None

def calcular_probabilidades(goles_local, goles_visitante):
    promedio_liga = 1.3 
    xg_local = (goles_local["gf_home"] / promedio_liga) * (goles_visitante["gc_away"] / promedio_liga) * promedio_liga
    xg_visit = (goles_visitante["gf_away"] / promedio_liga) * (goles_local["gc_home"] / promedio_liga) * promedio_liga

    prob_local = [poisson.pmf(i, xg_local) for i in range(6)]
    prob_visit = [poisson.pmf(i, xg_visit) for i in range(6)]

    prob_under_25 = sum([prob_local[i] * prob_visit[j] for i in range(6) for j in range(6) if i+j < 3])
    
    return {
        "xg_local": round(xg_local, 2),
        "xg_visitante": round(xg_visit, 2),
        "prob_over_25": round((1 - prob_under_25) * 100, 2),
        "prob_btts": round(((1 - prob_local[0]) * (1 - prob_visit[0])) * 100, 2)
    }

def consultar_gemini(estadisticas, local, visitante):
    prompt = f"""
    Actúa como un estadista deportivo. Datos EXACTOS (Poisson) de {local} vs {visitante}:
    - xG {local}: {estadisticas['xg_local']}
    - xG {visitante}: {estadisticas['xg_visitante']}
    - Over 2.5: {estadisticas['prob_over_25']}%
    - Ambos Anotan: {estadisticas['prob_btts']}%
    
    Escribe una breve "idea de apuesta" (máximo 4 líneas) basada ESTRICTAMENTE en estos números. Concluye qué mercado tiene más valor.
    """
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        return response.text.strip()
    except Exception:
        return "⚠️ Error consultando a la IA."

# --- 4. HANDLERS DE TELEGRAM ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("¡Sistema en línea! ⚡ (Arquitectura Webhook)\n\nUsa: `/analizar Equipo A vs Equipo B`", parse_mode="Markdown")

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    texto = message.text.replace("/analizar", "").strip()
    if " vs " not in texto:
        await message.reply("⚠️ Usa: `/analizar Equipo A vs Equipo B`", parse_mode="Markdown")
        return
        
    eq_local_str, eq_visit_str = texto.split(" vs ")
    msg = await message.reply("⏳ Procesando datos en tiempo real...")

    id_local, nombre_local = buscar_equipo(eq_local_str.strip())
    id_visit, nombre_visit = buscar_equipo(eq_visit_str.strip())

    if not id_local or not id_visit:
        return await msg.edit_text("❌ Equipos no encontrados en la API.")

    stats_local, stats_visit = obtener_goles_promedio(id_local), obtener_goles_promedio(id_visit)
    if not stats_local or not stats_visit:
         return await msg.edit_text("❌ Sin datos de goles esta temporada.")

    estadisticas = calcular_probabilidades(stats_local, stats_visit)
    idea_apuesta = consultar_gemini(estadisticas, nombre_local, nombre_visit)
    
    texto_final = (
        f"📊 *ANÁLISIS DE PARTIDO*\n"
        f"⚽ {nombre_local} vs {nombre_visit}\n\n"
        f"🔹 *xG:* {estadisticas['xg_local']} - {estadisticas['xg_visitante']}\n"
        f"📈 *Over 2.5:* {estadisticas['prob_over_25']}%\n"
        f"🔥 *Ambos Anotan:* {estadisticas['prob_btts']}%\n\n"
        f"💡 *CONCLUSIÓN IA:*\n{idea_apuesta}"
    )
    await msg.edit_text(texto_final, parse_mode="Markdown")

# --- 5. CONFIGURACIÓN DEL SERVIDOR WEB ---
async def on_startup(bot: Bot):
    # Le decimos a Telegram a qué URL enviar los mensajes
    await bot.set_webhook(WEBHOOK_URL)
    print(f"Webhook configurado en: {WEBHOOK_URL}")

def main():
    dp.startup.register(on_startup)
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    
    # Render usa la variable de entorno PORT automáticamente
    port = int(os.environ.get("PORT", 10000))
    web.run_app(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
