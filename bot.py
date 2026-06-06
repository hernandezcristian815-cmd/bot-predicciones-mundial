# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Motor Estadístico de Fútbol - Arquitectura Dual API + IA Desglosada

import os
import requests
import numpy as np
from scipy.stats import poisson
from datetime import datetime
from google import genai
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# --- 1. CONFIGURACIÓN DE CREDENCIALES ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_KEY")

# Ahora tenemos dos motores de datos
FOOTBALL_DATA_KEY = os.getenv("API_FOOTBALL_KEY") # Para Europa Top
API_SPORTS_KEY = os.getenv("API_SPORTS_KEY")       # Para Amistosos, LatAm y Cartelera

WEB_URL = os.getenv("RENDER_EXTERNAL_URL", "https://tu-app.onrender.com") 
WEBHOOK_PATH = f"/webhook/{TELEGRAM_TOKEN}"
WEBHOOK_URL = f"{WEB_URL}{WEBHOOK_PATH}"

client = genai.Client(api_key=GEMINI_API_KEY)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# --- 2. MOTOR PRINCIPAL: FOOTBALL-DATA (Europa Top) ---
def obtener_stats_football_data(nombre_equipo, competicion="PD"):
    url = f"https://api.football-data.org/v4/competitions/{competicion}/standings"
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200: return None, None
        data = response.json()
        tabla_total = next((t for t in data.get('standings', []) if t['type'] == 'TOTAL'), None)
        if not tabla_total: return None, None

        stats = {}
        nombre_oficial = nombre_equipo
        for row in tabla_total['table']:
            if nombre_equipo.lower() in row['team']['name'].lower():
                nombre_oficial = row['team']['name']
                partidos = row['playedGames'] if row['playedGames'] > 0 else 1
                stats['gf_home'] = stats['gf_away'] = row['goalsFor'] / partidos
                stats['gc_home'] = stats['gc_away'] = row['goalsAgainst'] / partidos
                # Datos simulados de tarjetas/córners si la API no los da en esta capa
                stats['corners'] = 4.5 
                stats['tarjetas'] = 2.1
                break
        return (stats, nombre_oficial) if len(stats) >= 4 else (None, None)
    except:
        return None, None

# --- 3. MOTOR SECUNDARIO: API-SPORTS (Amistosos y LatAm) ---
def obtener_stats_api_sports(nombre_equipo):
    url_search = "https://v3.football.api-sports.io/teams"
    headers = {"x-apisports-key": API_SPORTS_KEY}
    try:
        # 1. Buscar ID del equipo
        res_search = requests.get(url_search, headers=headers, params={"search": nombre_equipo})
        teams = res_search.json().get("response", [])
        if not teams: return None, None
        team_id = teams[0]["team"]["id"]
        nombre_oficial = teams[0]["team"]["name"]

        # 2. Buscar últimos partidos (Aproximación para amistosos/LatAm)
        url_fixtures = "https://v3.football.api-sports.io/fixtures"
        res_fix = requests.get(url_fixtures, headers=headers, params={"team": team_id, "last": 5})
        fixtures = res_fix.json().get("response", [])
        
        goles_favor = 0
        goles_contra = 0
        for f in fixtures:
            if f['teams']['home']['id'] == team_id:
                goles_favor += f['goals']['home'] if f['goals']['home'] else 0
                goles_contra += f['goals']['away'] if f['goals']['away'] else 0
            else:
                goles_favor += f['goals']['away'] if f['goals']['away'] else 0
                goles_contra += f['goals']['home'] if f['goals']['home'] else 0

        # Calculamos promedios
        partidos = len(fixtures) if len(fixtures) > 0 else 1
        stats = {
            'gf_home': goles_favor / partidos, 'gc_home': goles_contra / partidos,
            'gf_away': goles_favor / partidos, 'gc_away': goles_contra / partidos,
            'corners': 5.2, # Promedio estadístico genérico inyectado
            'tarjetas': 2.8 # Promedio estadístico genérico inyectado
        }
        return stats, nombre_oficial
    except Exception as e:
        print(f"Error Motor Secundario: {e}")
        return None, None

# --- 4. ORQUESTADOR Y MATEMÁTICAS ---
def calcular_probabilidades(goles_local, goles_visitante):
    promedio_liga = 1.3 
    xg_local = (goles_local["gf_home"] / promedio_liga) * (goles_visitante["gc_away"] / promedio_liga) * promedio_liga
    xg_visit = (goles_visitante["gf_away"] / promedio_liga) * (goles_local["gc_home"] / promedio_liga) * promedio_liga

    prob_local = [poisson.pmf(i, xg_local) for i in range(6)]
    prob_visit = [poisson.pmf(i, xg_visit) for i in range(6)]

    prob_under_25 = sum([prob_local[i] * prob_visit[j] for i in range(6) for j in range(6) if i+j < 3])
    
    return {
        "xg_local": round(xg_local, 2), "xg_visitante": round(xg_visit, 2),
        "prob_over_25": round((1 - prob_under_25) * 100, 2),
        "prob_btts": round(((1 - prob_local[0]) * (1 - prob_visit[0])) * 100, 2),
        "corners_local": goles_local.get('corners', 4.5),
        "tarjetas_local": goles_local.get('tarjetas', 2.0)
    }

def consultar_gemini(estadisticas, local, visitante):
    prompt = f"""
    Eres un analista deportivo experto pero muy amigable y directo. Hablas claro, para cualquier entendedor de fútbol.
    
    DATOS MATEMÁTICOS DE {local} vs {visitante}:
    - xG (Goles esperados): {local} ({estadisticas['xg_local']}) vs {visitante} ({estadisticas['xg_visitante']})
    - Probabilidad de +2.5 goles (Over): {estadisticas['prob_over_25']}%
    - Probabilidad Ambos Anotan (BTTS): {estadisticas['prob_btts']}%
    - Tendencia de Córners (Local): {estadisticas['corners_local']} por partido.
    - Tendencia de Tarjetas (Local): {estadisticas['tarjetas_local']} por partido.
    
    TAREA:
    Escribe un análisis desglosado de máximo 5 líneas. 
    Explícale al usuario qué equipo llega mejor ofensivamente, si el partido pinta para muchos goles, y haz una mención rápida a la dinámica de córners/tarjetas. Concluye cuál es la mejor apuesta.
    """
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        return response.text.strip()
    except: return "⚠️ Error consultando a la IA."

# --- 5. CARTELERA MUNDIAL (API-SPORTS) ---
# --- 5. CARTELERA MUNDIAL CLASIFICADA (API-SPORTS) ---
def obtener_cartelera_global():
    hoy = datetime.now().strftime('%Y-%m-%d')
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"x-apisports-key": API_SPORTS_KEY}
    
    try:
        res = requests.get(url, headers=headers, params={"date": hoy})
        partidos = res.json().get('response', [])
        if not partidos: return "No hay partidos relevantes hoy."
        
        # Diccionario para agrupar las categorías
        clasificacion = {
            "🏆 TOP EUROPA & INTERNACIONAL": [],
            "🌎 SELECCIONES (Amistosos / Copas)": [],
            "⚽ LIGAS DE AMÉRICA": []
        }

        # Palabras clave para el filtrado
        top_leagues = ["Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1", "Champions League", "Europa League", "Copa Libertadores", "Euro Championship"]
        selecciones = ["Friendlies", "World Cup", "Copa America", "UEFA Nations League"]
        latam_leagues = ["Primera A", "Liga Profesional", "Liga MX", "Brasileirao", "Primera Division", "MLS"]

        for p in partidos:
            local = p['teams']['home']['name']
            visitante = p['teams']['away']['name']
            liga = p['league']['name']
            pais = p['league']['country']
            
            item = f"▫️ {local} vs {visitante} ({liga})"

            # Lógica de clasificación
            if any(kw.lower() in liga.lower() for kw in top_leagues):
                clasificacion["🏆 TOP EUROPA & INTERNACIONAL"].append(item)
            elif any(kw.lower() in liga.lower() for kw in selecciones) or pais == "World":
                clasificacion["🌎 SELECCIONES (Amistosos / Copas)"].append(item)
            elif any(kw.lower() in liga.lower() for kw in latam_leagues) or pais in ["Colombia", "Argentina", "Brazil", "Mexico", "Chile"]:
                clasificacion["⚽ LIGAS DE AMÉRICA"].append(item)

        # Construir el mensaje final ensamblando los grupos
        texto_final = ""
        for categoria, lista in clasificacion.items():
            if lista:
                # Mostramos máximo 10 partidos por categoría para no saturar Telegram
                texto_final += f"*{categoria}*\n" + "\n".join(lista[:10]) + "\n\n" 

        if not texto_final.strip():
            return "Hoy solo hay partidos de divisiones menores o ligas no clasificadas en nuestro radar."

        return texto_final.strip()
    except Exception as e:
        print(f"Error clasificando cartelera: {e}")
        return None
# --- 6. HANDLERS DE TELEGRAM ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("¡Sistema en línea! ⚡ (Arquitectura Dual API)\n\nUsa `/hoy` para ver partidos o `/analizar Equipo A vs Equipo B`", parse_mode="Markdown")

@dp.message(Command("hoy"))
async def cartelera_hoy(message: types.Message):
    msg = await message.reply("⏳ Buscando la cartelera mundial del día...")
    cartelera = obtener_cartelera_global()
    if not cartelera:
        return await msg.edit_text("❌ Hubo un error buscando la cartelera (Verifica API_SPORTS_KEY).")
    await msg.edit_text(f"🌍 *CARTELERA MUNDIAL (INCLUYE AMISTOSOS)*\n\n{cartelera}\n\n👉 Copia y usa: `/analizar Equipo A vs Equipo B`", parse_mode="Markdown")

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    texto = message.text.replace("/analizar", "").strip()
    if " vs " not in texto: return await message.reply("⚠️ Usa: `/analizar Equipo A vs Equipo B`")
        
    eq_local_str, eq_visit_str = texto.split(" vs ")
    msg = await message.reply("⏳ Procesando con Inteligencia de Datos...")

    # 1. Intentamos con el Motor Principal (Europa Top)
    stats_local, n_local = obtener_stats_football_data(eq_local_str.strip())
    stats_visit, n_visit = obtener_stats_football_data(eq_visit_str.strip())
    motor_usado = "Europa Top (Football-Data)"

    # 2. Si falla, activamos el Motor Secundario (Amistosos / LatAm)
    if not stats_local or not stats_visit:
        stats_local, n_local = obtener_stats_api_sports(eq_local_str.strip())
        stats_visit, n_visit = obtener_stats_api_sports(eq_visit_str.strip())
        motor_usado = "Global/Amistosos (API-Sports)"

    if not stats_local or not stats_visit:
        return await msg.edit_text("❌ Equipos no encontrados en ninguna de las dos bases de datos.")

    estadisticas = calcular_probabilidades(stats_local, stats_visit)
    idea_apuesta = consultar_gemini(estadisticas, n_local, n_visit)
    
    texto_final = (
        f"📊 *ANÁLISIS DESGLOSADO*\n"
        f"⚽ {n_local} vs {n_visit}\n"
        f"⚙️ _Motor de datos: {motor_usado}_\n\n"
        f"🔹 *xG (Expectativa):* {estadisticas['xg_local']} - {estadisticas['xg_visitante']}\n"
        f"📈 *Over 2.5:* {estadisticas['prob_over_25']}%\n"
        f"🔥 *Ambos Anotan:* {estadisticas['prob_btts']}%\n"
        f"🚩 *Córners Promedio:* {estadisticas['corners_local']}\n"
        f"🟨 *Tarjetas Promedio:* {estadisticas['tarjetas_local']}\n\n"
        f"💡 *COMENTARIO DEL EXPERTO (IA):*\n{idea_apuesta}"
    )
    await msg.edit_text(texto_final, parse_mode="Markdown")

# --- 7. CONFIGURACIÓN DEL SERVIDOR WEB ---
async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL)

def main():
    dp.startup.register(on_startup)
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

if __name__ == "__main__":
    main()
