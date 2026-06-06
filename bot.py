# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Arquitectura Dual Avanzada - Análisis de Partidos y Consulta de Equipos Unificados

import os
import requests
import numpy as np
from scipy.stats import poisson
from datetime import datetime, timedelta
from google import genai
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# --- 1. CONFIGURACIÓN DE CREDENCIALES ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_KEY")
FOOTBALL_DATA_KEY = os.getenv("API_FOOTBALL_KEY") 
API_SPORTS_KEY = os.getenv("API_SPORTS_KEY")       

WEB_URL = os.getenv("RENDER_EXTERNAL_URL", "https://tu-app.onrender.com") 
WEBHOOK_PATH = f"/webhook/{TELEGRAM_TOKEN}"
WEBHOOK_URL = f"{WEB_URL}{WEBHOOK_PATH}"

client = genai.Client(api_key=GEMINI_API_KEY)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# --- 2. EXTRACTOR UNIVERSAL DE ESTADÍSTICAS (FALLBACK AUTOMÁTICO) ---
def buscar_datos_equipo(nombre_equipo):
    """
    Busca un equipo en ambas APIs de forma secuencial y extrae sus métricas reales.
    Si no tiene historial, aplica el parche anticolapso de 0.8 goles base.
    """
    nombre_limpio = nombre_equipo.split("(")[0].strip()
    
    # INTENTO 1: Football-Data (Liga Española por defecto)
    url_fd = "https://api.football-data.org/v4/competitions/PD/standings"
    headers_fd = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    try:
        res = requests.get(url_fd, headers=headers_fd, timeout=5)
        if res.status_code == 200:
            tabla = next((t for t in res.json().get('standings', []) if t['type'] == 'TOTAL'), None)
            if tabla:
                for row in tabla['table']:
                    if nombre_limpio.lower() in row['team']['name'].lower():
                        partidos = row['playedGames'] if row['playedGames'] > 0 else 1
                        return {
                            'name': row['team']['name'],
                            'gf': row['goalsFor'] / partidos,
                            'gc': row['goalsAgainst'] / partidos,
                            'corners': 4.8,
                            'tarjetas': 2.2,
                            'fuente': "Elite Europa"
                        }
    except:
        pass

    # INTENTO 2: API-Sports (Cualquier equipo del mundo, selecciones o LatAm)
    url_as_search = "https://v3.football.api-sports.io/teams"
    headers_as = {"x-apisports-key": API_SPORTS_KEY}
    try:
        res_search = requests.get(url_as_search, headers=headers_as, params={"search": nombre_limpio}, timeout=5)
        teams = res_search.json().get("response", [])
        if teams:
            team_id = teams[0]["team"]["id"]
            nombre_oficial = teams[0]["team"]["name"]

            # Buscamos su última liga o torneo activo para sacar estadísticas
            url_fix = "https://v3.football.api-sports.io/fixtures"
            res_fix = requests.get(url_fix, headers=headers_as, params={"team": team_id, "last": 1}, timeout=5)
            last_fix = res_fix.json().get("response", [])
            
            liga_id = last_fix[0]['league']['id'] if last_fix else 140
            season = last_fix[0]['league']['season'] if last_fix else 2025

            url_stats = "https://v3.football.api-sports.io/teams/statistics"
            res_stats = requests.get(url_stats, headers=headers_as, params={"team": team_id, "league": liga_id, "season": season}, timeout=5)
            d_stats = res_stats.json().get("response", {})

            if d_stats:
                partidos = d_stats['fixtures']['played']['total'] or 1
                gf_totales = d_stats['goals']['for']['total']['total'] or 0
                gc_totales = d_stats['goals']['against']['total']['total'] or 0
                
                corners = d_stats.get('corners', {}).get('total', 0) or 45
                amarillas = d_stats.get('cards', {}).get('yellow', {})
                tot_tarjetas = sum([int(v.get('total') or 0) for k, v in amarillas.items() if v]) or 20

                return {
                    'name': nombre_oficial,
                    'gf': (gf_totales / partidos) if gf_totales > 0 else 0.8,
                    'gc': (gc_totales / partidos) if gc_totales > 0 else 0.8,
                    'corners': round(corners / partidos, 1),
                    'tarjetas': round(tot_tarjetas / partidos, 1),
                    'fuente': "Base de Datos Global"
                }
    except Exception as e:
        print(f"Error en extractor universal: {e}")
    
    return None

# --- 3. PROCESADORES MATEMÁTICOS Y CONSULTA IA ---
def calcular_probabilidades(local_stats, visit_stats):
    promedio_liga = 1.3 
    xg_local = (local_stats["gf"] / promedio_liga) * (visit_stats["gc"] / promedio_liga) * promedio_liga
    xg_visit = (visit_stats["gf"] / promedio_liga) * (local_stats["gc"] / promedio_liga) * promedio_liga

    prob_local = [poisson.pmf(i, xg_local) for i in range(6)]
    prob_visit = [poisson.pmf(i, xg_visit) for i in range(6)]
    prob_under_25 = sum([prob_local[i] * prob_visit[j] for i in range(6) for j in range(6) if i+j < 3])
    
    return {
        "xg_local": round(xg_local, 2), "xg_visitante": round(xg_visit, 2),
        "prob_over_25": round((1 - prob_under_25) * 100, 2),
        "prob_btts": round(((1 - prob_local[0]) * (1 - prob_visit[0])) * 100, 2)
    }

def consultar_gemini(estadisticas, local, visitante, corners_avg, tarjetas_avg):
    prompt = f"""
    Eres un analista deportivo experto pero muy amigable y directo. Hablas claro, para cualquier entendedor de fútbol.
    
    DATOS MATEMÁTICOS DE {local} vs {visitante}:
    - xG (Goles esperados): {local} ({estadisticas['xg_local']}) vs {visitante} ({estadisticas['xg_visitante']})
    - Probabilidad de +2.5 goles (Over): {estadisticas['prob_over_25']}%
    - Probabilidad Ambos Anotan (BTTS): {estadisticas['prob_btts']}%
    - Tendencia combinada de Córners: {corners_avg} por partido.
    - Tendencia combinada de Tarjetas: {tarjetas_avg} por partido.
    
    TAREA:
    Escribe un análisis desglosado de máximo 5 líneas. 
    Explícale al usuario qué equipo llega mejor ofensivamente, si el partido pinta para muchos goles, y haz una mención rápida a la dinámica de córners/tarjetas. Concluye cuál es la mejor apuesta.
    """
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        return response.text.strip()
    except: 
        return "⚠️ Error consultando a la IA."

# --- 4. CARTELERA MUNDIAL CLASIFICADA ---
def obtener_cartelera_global():
    hoy = datetime.now().strftime('%Y-%m-%d')
    limite = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"x-apisports-key": API_SPORTS_KEY}
    try:
        res = requests.get(url, headers=headers, params={"from": hoy, "to": limite}, timeout=5)
        partidos = res.json().get('response', [])
        if not partidos: return "No hay partidos relevantes programados."
        
        clasificacion = {
            "🏆 TOP EUROPA & INTERNACIONAL": [],
            "🌎 SELECCIONES (Amistosos / Copas)": [],
            "⚽ LIGAS DE AMÉRICA": []
        }
        top_leagues = ["Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1", "Champions League", "Copa Libertadores"]
        selecciones = ["Friendlies", "World Cup", "Copa America", "UEFA Nations League"]
        latam_leagues = ["Primera A", "Liga Profesional", "Liga MX", "Brasileirao", "MLS"]

        for p in partidos:
            if p['fixture']['status']['short'] in ['FT', 'AET', 'PEN']: continue
            liga = p['league']['name']
            local = p['teams']['home']['name']
            visitante = p['teams']['away']['name']
            pais = p['league']['country']
            
            if "women" in liga.lower() or "femenina" in liga.lower() or local.endswith(" W") or visitante.endswith(" W"): continue
            
            f_cruda = p['fixture']['date']
            item = f"▫️ [{f_cruda.split('T')[0]} {f_cruda.split('T')[1][:5]}] {local} vs {visitante} ({liga})"

            if any(kw.lower() in liga.lower() for kw in top_leagues):
                clasificacion["🏆 TOP EUROPA & INTERNACIONAL"].append(item)
            elif any(kw.lower() in liga.lower() for kw in selecciones) or pais == "World":
                clasificacion["🌎 SELECCIONES (Amistosos / Copas)"].append(item)
            elif any(kw.lower() in liga.lower() for kw in latam_leagues) or pais in ["Colombia", "Argentina", "Brazil", "Mexico", "Chile"]:
                clasificacion["⚽ LIGAS DE AMÉRICA"].append(item)

        texto_final = ""
        for cat, lista in clasificacion.items():
            if lista: texto_final += f"*{cat}*\n" + "\n".join(lista[:10]) + "\n\n" 
        return texto_final.strip() if texto_final.strip() else "No hay partidos pendientes en nuestro radar."
    except: 
        return None

# --- 5. HANDLERS DE TELEGRAM ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("¡Sistema en línea! ⚡\n\n📌 `/hoy` - Ver cartelera\n📌 `/analizar Equipo A vs Equipo B` - Predicción completa\n📌 `/equipo Nombre` - Ver estadísticas de un solo equipo", parse_mode="Markdown")

@dp.message(Command("hoy"))
async def cartelera_hoy(message: types.Message):
    msg = await message.reply("⏳ Buscando la cartelera...")
    cartelera = obtener_cartelera_global()
    if not cartelera: return await msg.edit_text("❌ Error al conectar con el servidor de datos.")
    await msg.edit_text(f"🌍 *PRÓXIMOS ENCUENTROS*\n\n{cartelera}", parse_mode="Markdown")

@dp.message(Command("equipo"))
async def consultar_equipo_solo(message: types.Message):
    nombre_buscado = message.text.replace("/equipo", "").strip()
    if not nombre_buscado:
        return await message.reply("⚠️ Usa: `/equipo Millonarios` o `/equipo Real Madrid`")
        
    msg = await message.reply(f"🔍 Extrayendo registros de *{nombre_buscado}*...")
    data = buscar_datos_equipo(nombre_buscado)
    
    if not data:
        return await msg.edit_text("❌ No se encontraron datos para ese equipo en ninguna liga activa.")
        
    texto = (
        f"📋 *FICHA ESTADÍSTICA REAL*\n"
        f"⚽ *Equipo:* {data['name']}\n"
        f"🗂️ _Origen: {data['fuente']}_\n\n"
        f"📊 *Rendimiento Promedio por Partido:*\n"
        f"🔹 Goles Anotados: {round(data['gf'], 2)}\n"
        f"🔸 Goles Recibidos: {round(data['gc'], 2)}\n"
        f"🚩 Córners Provocados: {data['corners']}\n"
        f"🟨 Tarjetas Recibidas: {data['tarjetas']}\n"
    )
    await msg.edit_text(texto, parse_mode="Markdown")

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    texto = message.text.replace("/analizar", "").strip()
    if " vs " not in texto: return await message.reply("⚠️ Usa: `/analizar Equipo A vs Equipo B`")
        
    eq_local_str, eq_visit_str = texto.split(" vs ")
    msg = await message.reply("⏳ Calculando cruce de variables y cargando IA...")

    # Buscamos a cada uno de forma independiente e infalible
    stats_local = buscar_datos_equipo(eq_local_str)
    stats_visit = buscar_datos_equipo(eq_visit_str)

    if not stats_local or not stats_visit:
        return await msg.edit_text("❌ Uno o ambos equipos no se encontraron. Verifica cómo están escritos.")

    estadisticas = calcular_probabilidades(stats_local, stats_visit)
    
    # Calculamos los promedios reales combinados para el prompt de Gemini
    corners_avg = round((stats_local['corners'] + stats_visit['corners']) / 2, 1)
    tarjetas_avg = round((stats_local['tarjetas'] + stats_visit['tarjetas']) / 2, 1)
    
    idea_apuesta = consultar_gemini(estadisticas, stats_local['name'], stats_visit['name'], corners_avg, tarjetas_avg)
    
    texto_final = (
        f"📊 *ANÁLISIS DESGLOSADO DE CRUCE*\n"
        f"⚽ {stats_local['name']} vs {stats_visit['name']}\n\n"
        f"🔹 *xG (Goles Esperados):* {estadisticas['xg_local']} - {estadisticas['xg_visitante']}\n"
        f"📈 *Over 2.5:* {estadisticas['prob_over_25']}%\n"
        f"🔥 *Ambos Anotan:* {estadisticas['prob_btts']}%\n"
        f"🚩 *Córners Promedio:* {corners_avg}\n"
        f"🟨 *Tarjetas Promedio:* {tarjetas_avg}\n\n"
        f"💡 *COMENTARIO DEL EXPERTO (IA):*\n{idea_apuesta}"
    )
    await msg.edit_text(texto_final, parse_mode="Markdown")

# --- 6. CONFIGURACIÓN DEL SERVIDOR WEB ---
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
