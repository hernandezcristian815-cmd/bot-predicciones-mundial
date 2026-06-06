# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Motor Estadístico de Fútbol - Webhook + Football-Data

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

WEB_URL = os.getenv("RENDER_EXTERNAL_URL", "https://tu-app.onrender.com") 
WEBHOOK_PATH = f"/webhook/{TELEGRAM_TOKEN}"
WEBHOOK_URL = f"{WEB_URL}{WEBHOOK_PATH}"

client = genai.Client(api_key=GEMINI_API_KEY)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# --- 2. EXTRACCIÓN DE DATOS EXACTOS (FOOTBALL-DATA.ORG) ---
def obtener_estadisticas_equipo(nombre_equipo, competicion="PD"):
    url = f"https://api.football-data.org/v4/competitions/{competicion}/standings"
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    
    try:
        print(f"--> 1. Buscando: {nombre_equipo} en liga {competicion}", flush=True)
        response = requests.get(url, headers=headers)
        
        if response.status_code != 200:
            print(f"--> ❌ Error API: {response.status_code} - {response.text}", flush=True)
            return None, None
            
        data = response.json()
        tipos_tabla = [t['type'] for t in data.get('standings', [])]
        print(f"--> 2. Tablas descargadas: {tipos_tabla}", flush=True)
        
        tabla_home = next((t for t in data.get('standings', []) if t['type'] == 'HOME'), None)
        tabla_away = next((t for t in data.get('standings', []) if t['type'] == 'AWAY'), None)
        
        if not tabla_home or not tabla_away:
            print("--> ❌ Faltan datos de tablas HOME o AWAY en esta liga.", flush=True)
            return None, None

        stats = {}
        nombre_oficial = nombre_equipo
        
        for row in tabla_home['table']:
            if nombre_equipo.lower() in row['team']['name'].lower():
                nombre_oficial = row['team']['name']
                partidos = row['playedGames'] if row['playedGames'] > 0 else 1
                stats['gf_home'] = row['goalsFor'] / partidos
                stats['gc_home'] = row['goalsAgainst'] / partidos
                print(f"--> 3. Datos Local OK: {stats['gf_home']} GF", flush=True)
                break
                
        for row in tabla_away['table']:
            if nombre_equipo.lower() in row['team']['name'].lower():
                partidos = row['playedGames'] if row['playedGames'] > 0 else 1
                stats['gf_away'] = row['goalsFor'] / partidos
                stats['gc_away'] = row['goalsAgainst'] / partidos
                print(f"--> 4. Datos Visitante OK: {stats['gf_away']} GF", flush=True)
                break

        print(f"--> 5. Stats finales listas: {stats}", flush=True)

        if len(stats) == 4:
            return stats, nombre_oficial
        
        print(f"--> ❌ El equipo '{nombre_equipo}' no está escrito igual que en la API.", flush=True)
        return None, None

    except Exception as e:
        print(f"--> ❌ Error fatal de sistema: {e}", flush=True)
        return None, None

# --- 3. MOTOR ESTADÍSTICO MATEMÁTICO ---
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
    await message.answer("¡Sistema en línea! ⚡ (Arquitectura Webhook + Football-Data)\n\nUsa: `/analizar Equipo A vs Equipo B`", parse_mode="Markdown")

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    texto = message.text.replace("/analizar", "").strip()
    if " vs " not in texto:
        await message.reply("⚠️ Usa: `/analizar Equipo A vs Equipo B`", parse_mode="Markdown")
        return
        
    eq_local_str, eq_visit_str = texto.split(" vs ")
    msg = await message.reply("⏳ Procesando datos en tiempo real...")

    stats_local, nombre_local = obtener_estadisticas_equipo(eq_local_str.strip())
    stats_visit, nombre_visit = obtener_estadisticas_equipo(eq_visit_str.strip())

    if not stats_local or not stats_visit:
        await msg.edit_text("❌ Equipos no encontrados o liga no soportada. (Verifica los nombres).")
        return

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
    await bot.set_webhook(WEBHOOK_URL)
    print(f"Webhook configurado en: {WEBHOOK_URL}")

def main():
    dp.startup.register(on_startup)
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    
    port = int(os.environ.get("PORT", 10000))
    web.run_app(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
