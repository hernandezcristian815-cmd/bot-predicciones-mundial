# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Arquitectura de Fallback Cognitivo Inteligente (IA Total para Fútbol)

import os
import requests
import json
import numpy as np
from scipy.stats import poisson
from datetime import datetime, timedelta
from google import genai
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# --- 1. CREDENCIALES ---
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

# --- 2. MOTOR DE RESPALDO CON IA (FALLBACK COGNITIVO) ---
def generar_stats_con_ia(nombre_equipo):
    """Usa Gemini para estimar las métricas de un equipo si la API falla."""
    prompt = f"""
    Actúa como una base de datos estadística de fútbol profesional. Requiero las métricas estimadas de rendimiento actual (basadas en sus últimos 10 partidos oficiales o amistosos internacionales) para el equipo o selección: "{nombre_equipo}".
    
    Debes devolver ÚNICAMENTE un objeto JSON con la siguiente estructura exacta (sin textos aclaratorios, sin markdown, solo el JSON limpio):
    {{
        "name": "Nombre Oficial del Equipo",
        "gf": 1.75,
        "gc": 1.10,
        "corners": 5.4,
        "tarjetas": 2.3
    }}
    Nota: 'gf' son goles a favor por partido y 'gc' goles en contra por partido. Sé lo más preciso posible según su actualidad.
    """
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        text = response.text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        data['fuente'] = "Inteligencia Predictiva IA"
        return data
    except Exception as e:
        print(f"Error generando stats con IA: {e}")
        return None

# --- 3. EXTRACTOR DE DATOS TRADICIONAL ---
def buscar_datos_equipo(nombre_equipo):
    nombre_limpio = nombre_equipo.split("(")[0].strip()
    
    # Intento 1: API Football-Data
    url_fd = "https://api.football-data.org/v4/competitions/PD/standings"
    headers_fd = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    try:
        res = requests.get(url_fd, headers=headers_fd, timeout=4)
        if res.status_code == 200:
            tabla = next((t for t in res.json().get('standings', []) if t['type'] == 'TOTAL'), None)
            if tabla:
                for row in tabla['table']:
                    if nombre_limpio.lower() in row['team']['name'].lower():
                        partidos = row['playedGames'] if row['playedGames'] > 0 else 1
                        return {
                            'name': row['team']['name'], 'gf': row['goalsFor'] / partidos,
                            'gc': row['goalsAgainst'] / partidos, 'corners': 4.8, 'tarjetas': 2.2,
                            'fuente': "Base de Datos Europea"
                        }
    except: pass

    # Intento 2: API-Sports
    url_as = "https://v3.football.api-sports.io/teams"
    headers_as = {"x-apisports-key": API_SPORTS_KEY}
    try:
        res_search = requests.get(url_as, headers=headers_as, params={"search": nombre_limpio}, timeout=4)
        teams = res_search.json().get("response", [])
        if teams:
            team_id = teams[0]["team"]["id"]
            nombre_oficial = teams[0]["team"]["name"]
            url_stats = f"https://v3.football.api-sports.io/teams/statistics?team={team_id}&league=140&season=2025"
            res_stats = requests.get(url_stats, headers=headers_as, timeout=4)
            d_stats = res_stats.json().get("response", {})
            if d_stats:
                partidos = d_stats['fixtures']['played']['total'] or 1
                return {
                    'name': nombre_oficial,
                    'gf': (d_stats['goals']['for']['total']['total'] or 0) / partidos,
                    'gc': (d_stats['goals']['against']['total']['total'] or 0) / partidos,
                    'corners': 5.0, 'tarjetas': 2.5, 'fuente': "Base de Datos Global"
                }
    except: pass

    # ACTIVACIÓN DE RESPALDO: Si las APIs fallan o no lo encuentran, la IA toma el control
    return generar_stats_con_ia(nombre_limpio)

# --- 4. CÁLCULOS MATEMÁTICOS ---
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

def consultar_gemini_analisis(estadisticas, local, visitante, corners_avg, tarjetas_avg):
    prompt = f"""
    Eres un analista de apuestas de fútbol directo, amigable y muy experto. Hablas claro para cualquier entendedor.
    
    MÉTRICAS DEL ENCUENTRO:
    - {local} vs {visitante}
    - xG esperado: {local} ({estadisticas['xg_local']}) - {visitante} ({estadisticas['xg_visitante']})
    - Probabilidad Over 2.5 goles: {estadisticas['prob_over_25']}%
    - Ambos Anotan (BTTS): {estadisticas['prob_btts']}%
    - Promedio de Córners total del juego: {corners_avg}
    - Promedio de Tarjetas total del juego: {tarjetas_avg}
    
    Redacta un análisis desglosado de máximo 5 líneas explicando de forma sencilla qué esperar del partido basándote en los números y dinámicas de juego (goles, córners y juego fuerte). Termina recomendando la apuesta con más valor.
    """
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        return response.text.strip()
    except: return "⚠️ El experto en IA está calculando..."

# --- 5. CARTELERA MUNDIAL ---
def obtener_cartelera_global():
    hoy = datetime.now().strftime('%Y-%m-%d')
    limite = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')
    url = f"https://v3.football.api-sports.io/fixtures?from={hoy}&to={limite}"
    headers = {"x-apisports-key": API_SPORTS_KEY}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        partidos = res.json().get('response', [])
        if not partidos: return "No hay partidos relevantes en este momento. Intenta más tarde."
        
        clasificacion = {
            "🏆 LIGAS TOP & INTERNACIONAL": [],
            "🌎 SELECCIONES MUNDIALES": [],
            "⚽ FÚTBOL SUDAMÉRICA & LATAM": []
        }
        top_leagues = ["premier", "la liga", "serie a", "bundesliga", "ligue 1", "champions", "libertadores"]
        selecciones = ["friendlies", "world cup", "copa america", "nations league", "championship"]
        latam_leagues = ["primera a", "liga profesional", "liga mx", "brasileirao", "mls", "primera division"]

        for p in partidos:
            if p['fixture']['status']['short'] in ['FT', 'AET', 'PEN']: continue
            liga = p['league']['name']
            local = p['teams']['home']['name']
            visitante = p['teams']['away']['name']
            pais = p['league']['country']
            
            if "women" in liga.lower() or "femenina" in liga.lower() or local.endswith(" W") or visitante.endswith(" W"): continue
            
            f_cruda = p['fixture']['date']
            item = f"▫️ [{f_cruda.split('T')[0]} {f_cruda.split('T')[1][:5]}] {local} vs {visitante} ({liga})"

            if any(kw in liga.lower() for kw in top_leagues):
                clasificacion["🏆 LIGAS TOP & INTERNACIONAL"].append(item)
            elif any(kw in liga.lower() for kw in selecciones) or pais == "World":
                clasificacion["🌎 SELECCIONES MUNDIALES"].append(item)
            elif any(kw in liga.lower() for kw in latam_leagues) or pais in ["Colombia", "Argentina", "Brazil", "Mexico", "Chile"]:
                clasificacion["⚽ FÚTBOL SUDAMÉRICA & LATAM"].append(item)

        texto_final = ""
        for cat, lista in clasificacion.items():
            if lista: texto_final += f"*{cat}*\n" + "\n".join(lista[:8]) + "\n\n" 
        return texto_final.strip() if texto_final.strip() else "No hay partidos en el radar por ahora."
    except: return "No hay partidos en el radar por ahora."

# --- 6. HANDLERS ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("¡Sistema de Predicción con Inteligencia Artificial Total Híbrida Línea! ⚡\n\n📌 `/hoy` - Cartelera filtrada\n📌 `/analizar Equipo A vs Equipo B` - Análisis con IA de Respaldo\n📌 `/equipo Nombre` - Ficha técnica por IA/API", parse_mode="Markdown")

@dp.message(Command("hoy"))
async def cartelera_hoy(message: types.Message):
    msg = await message.reply("⏳ Cargando cartelera...")
    cartelera = obtener_cartelera_global()
    await msg.edit_text(f"🌍 *PRÓXIMOS ENCUENTROS DE VALOR*\n\n{cartelera}", parse_mode="Markdown")

@dp.message(Command("equipo"))
async def consultar_equipo_solo(message: types.Message):
    nombre_buscado = message.text.replace("/equipo", "").strip()
    if not nombre_buscado: return await message.reply("⚠️ Usa: `/equipo Colombia`")
        
    msg = await message.reply(f"🔍 Rastreando métricas de *{nombre_buscado}*...")
    data = buscar_datos_equipo(nombre_buscado)
    
    if not data: return await msg.edit_text("❌ No fue posible procesar al equipo.")
        
    texto = (
        f"📋 *FICHA TÉCNICA PRO*\n"
        f"⚽ *Equipo:* {data['name']}\n"
        f"🧬 _Proveedor: {data['fuente']}_\n\n"
        f"🔹 Goles Favor (Promedio): {round(data['gf'], 2)}\n"
        f"🔸 Goles Contra (Promedio): {round(data['gc'], 2)}\n"
        f"🚩 Córners Esperados: {data['corners']}\n"
        f"🟨 Tarjetas Esperadas: {data['tarjetas']}\n"
    )
    await msg.edit_text(texto, parse_mode="Markdown")

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    texto = message.text.replace("/analizar", "").strip()
    if " vs " not in texto: return await message.reply("⚠️ Usa: `/analizar Equipo A vs Equipo B`")
        
    eq_local_str, eq_visit_str = texto.split(" vs ")
    msg = await message.reply("🧠 Procesando datos híbridos (API + IA)...")

    stats_local = buscar_datos_equipo(eq_local_str)
    stats_visit = buscar_datos_equipo(eq_visit_str)

    if not stats_local or not stats_visit:
        return await msg.edit_text("❌ Error crítico en el motor de inferencia cognitiva.")

    estadisticas = calcular_probabilidades(stats_local, stats_visit)
    corners_avg = round((stats_local['corners'] + stats_visit['corners']) / 2, 1)
    tarjetas_avg = round((stats_local['tarjetas'] + stats_visit['tarjetas']) / 2, 1)
    
    idea_apuesta = consultar_gemini_analisis(estadisticas, stats_local['name'], stats_visit['name'], corners_avg, tarjetas_avg)
    
    texto_final = (
        f"📊 *ANÁLISIS DE CRUCE INTEGRAL*\n"
        f"⚽ {stats_local['name']} vs {stats_visit['name']}\n"
        f"🧬 _Local: {stats_local['fuente']} | Visitante: {stats_visit['fuente']}_\n\n"
        f"🔹 *xG (Goles Esperados):* {estadisticas['xg_local']} - {estadisticas['xg_visitante']}\n"
        f"📈 *Over 2.5:* {estadisticas['prob_over_25']}%\n"
        f"🔥 *Ambos Anotan:* {estadisticas['prob_btts']}%\n"
        f"🚩 *Córners Promedio:* {corners_avg}\n"
        f"🟨 *Tarjetas Promedio:* {tarjetas_avg}\n\n"
        f"💡 *COMENTARIO DESGLOSADO:*\n{idea_apuesta}"
    )
    await msg.edit_text(texto_final, parse_mode="Markdown")

# --- 7. SERVIDOR WEB ---
async def on_startup(bot: Bot): await bot.set_webhook(WEBHOOK_URL)
def main():
    dp.startup.register(on_startup)
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

if __name__ == "__main__": main()
