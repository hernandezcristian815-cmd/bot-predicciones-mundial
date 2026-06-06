# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Value Betting Engine Premium - Edición Mundial & Calendario en Tiempo Real

import os
import requests
import json
import sqlite3
import numpy as np
from scipy.stats import poisson
from datetime import datetime, timedelta
from google import genai
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- 1. CONFIGURACIÓN Y CREDENCIALES ---
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

DB_NAME = "apuestas.db"
LIGAS_GRATUITAS = ["WC", "CL", "PL", "ELC", "FL1", "BL1", "SA", "PD", "PPL", "DED", "BSA"]

CUOTAS_MONITOR = {
    "football_data": "No consultado",
    "api_sports": "No consultado",
    "gemini": 15
}

# --- 2. BOTONES INTERACTIVOS MEJORADOS ---
def obtener_teclado_interactivo():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="📅 Partidos de Hoy", callback_data="ver_partidos_hoy"),
        types.InlineKeyboardButton(text="📊 Analizar Partido", switch_inline_query_current_chat="/analizar ")
    )
    builder.row(
        types.InlineKeyboardButton(text="🔍 Buscar Equipo", switch_inline_query_current_chat="/equipo "),
        types.InlineKeyboardButton(text="📈 Ver Efectividad", callback_data="ver_efectividad_ia")
    )
    return builder.as_markup()

# --- 3. BASE DE DATOS ---
def inicializar_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS predicciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT, local TEXT, visitante TEXT,
            prob_over REAL, prob_btts REAL,
            goles_local_real INTEGER DEFAULT NULL,
            goles_visit_real INTEGER DEFAULT NULL,
            estado TEXT DEFAULT 'PENDIENTE'
        )
    """)
    conn.commit()
    conn.close()

def guardar_prediccion(local, visitante, prob_over, prob_btts):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    fecha_hoy = datetime.now().strftime('%Y-%m-%d %H:%M')
    cursor.execute("INSERT INTO predicciones (fecha, local, visitante, prob_over, prob_btts) VALUES (?, ?, ?, ?, ?)", (fecha_hoy, local, visitante, prob_over, prob_btts))
    id_generado = cursor.lastrowid
    conn.commit()
    conn.close()
    return id_generado

def registrar_resultado_db(prediccion_id, goles_l, goles_v):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE predicciones SET goles_local_real = ?, goles_visit_real = ?, estado = 'FINALIZADO' WHERE id = ?", (goles_l, goles_v, prediccion_id))
    filas_afectadas = cursor.rowcount
    conn.commit()
    conn.close()
    return filas_afectadas > 0

# --- 4. MOTOR DE CALENDARIO DIARIO (NUEVO COMPONENTE) ---
def consultar_partidos_del_dia():
    """Consulta la agenda de partidos programados para la fecha de hoy en las ligas del plan."""
    headers_fd = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    hoy_str = datetime.now().strftime('%Y-%m-%d')
    partidos_detectados = []

    for liga in LIGAS_GRATUITAS:
        url_matches = f"https://api.football-data.org/v4/competitions/{liga}/matches"
        try:
            # Filtramos directo por la fecha actual en la API
            res = requests.get(url_matches, headers=headers_fd, params={"dateFrom": hoy_str, "dateTo": hoy_str}, timeout=3)
            if res.status_code == 200:
                matches = res.json().get("matches", [])
                for m in matches:
                    partidos_detectados.append({
                        "liga": liga,
                        "local": m["homeTeam"]["name"],
                        "visitante": m["awayTeam"]["name"],
                        "hora": m["utcDate"][11:16]
                    })
        except:
            pass
    return partidos_detectados

# --- 5. AGENTE COGNITIVO IA ---
def investigar_equipo_con_ia(nombre_equipo):
    prompt = f"""
    Investiga el rendimiento deportivo y goles recientes de: "{nombre_equipo}".
    Si compite en liga local o selección actual, extrae sus métricas de los últimos 5 partidos oficiales.
    Si el torneo está en pausa o la data es escasa, deduce promedios realistas basados en su desempeño histórico cercano.
    Devuelve ÚNICAMENTE un objeto JSON limpio, sin bloques markdown de código, con esta estructura exacta:
    {{"name": "Nombre Oficial Encontrado", "gf": 1.35, "gc": 1.15, "corners": 4.8, "tarjetas": 2.2, "informacion_historica": true}}
    """
    try:
        if isinstance(CUOTAS_MONITOR["gemini"], int) and CUOTAS_MONITOR["gemini"] > 0:
            CUOTAS_MONITOR["gemini"] -= 1
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        text = response.text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        data['fuente'] = "Inferencia de Tendencia Histórica (IA)"
        return data
    except: return None

# --- 6. EXTRACTOR DE ESTADÍSTICAS ---
def buscar_datos_equipo(nombre_equipo):
    nombre_limpio = nombre_equipo.split("(")[0].strip()
    headers_fd = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    
    for liga in LIGAS_GRATUITAS:
        url_fd = f"https://api.football-data.org/v4/competitions/{liga}/standings"
        try:
            res = requests.get(url_fd, headers=headers_fd, timeout=3)
            if "X-Requests-Available-Minute" in res.headers:
                CUOTAS_MONITOR["football_data"] = f"{res.headers['X-Requests-Available-Minute']} req/min"
            if res.status_code == 200:
                tabla = next((t for t in res.json().get('standings', []) if t['type'] == 'TOTAL'), None)
                if tabla:
                    for row in tabla['table']:
                        if nombre_limpio.lower() in row['team']['name'].lower() or row['team']['name'].lower() in nombre_limpio.lower():
                            partidos = row['playedGames'] if row['playedGames'] > 0 else 1
                            return {
                                'name': row['team']['name'], 'gf': row['goalsFor'] / partidos, 'gc': row['goalsAgainst'] / partidos, 
                                'corners': 5.2, 'tarjetas': 2.1, 'fuente': f"Football-Data ({liga})"
                            }
        except: pass

    url_as = "https://v3.football.api-sports.io/teams"
    headers_as = {"x-apisports-key": API_SPORTS_KEY}
    try:
        res_search = requests.get(url_as, headers=headers_as, params={"search": nombre_limpio}, timeout=4)
        if "x-ratelimit-requests-remaining" in res_search.headers:
            CUOTAS_MONITOR["api_sports"] = f"{res_search.headers['x-ratelimit-requests-remaining']} req/día"
        teams = res_search.json().get("response", [])
        if teams:
            team_id = teams[0]["team"]["id"]
            nombre_oficial = teams[0]["team"]["name"]
            url_fix = f"https://v3.football.api-sports.io/fixtures?team={team_id}&last=5"
            res_fix = requests.get(url_fix, headers=headers_as, timeout=4)
            fixtures = res_fix.json().get("response", [])
            if fixtures:
                g_favor = sum([(f['goals']['home'] if f['teams']['home']['id'] == team_id else f['goals']['away']) for f in fixtures if f['goals']['home'] is not None])
                g_contra = sum([(f['goals']['away'] if f['teams']['home']['id'] == team_id else f['goals']['home']) for f in fixtures if f['goals']['home'] is not None])
                partidos = len(fixtures)
                return {'name': nombre_oficial, 'gf': g_favor / partidos, 'gc': g_contra / partidos, 'corners': 4.7, 'tarjetas': 2.5, 'fuente': "Historial Operativo API-Sports"}
    except: pass

    return investigar_equipo_con_ia(nombre_limpio)

# --- 7. POISSON Y VALOR DE CUOTAS ---
def calcular_probabilidades(local_stats, visit_stats):
    promedio_goles_equipo = 1.25
    fuerza_ataque_local = local_stats["gf"] / promedio_goles_equipo
    debilidad_defensa_visit = visit_stats["gc"] / promedio_goles_equipo
    fuerza_ataque_visit = visit_stats["gf"] / promedio_goles_equipo
    debilidad_defensa_local = local_stats["gc"] / promedio_goles_equipo
    
    xg_local = fuerza_ataque_local * debilidad_defensa_visit * promedio_goles_equipo
    xg_visit = fuerza_ataque_visit * debilidad_defensa_local * promedio_goles_equipo

    prob_local = [poisson.pmf(i, xg_local) for i in range(6)]
    prob_visit = [poisson.pmf(i, xg_visit) for i in range(6)]
    
    prob_under_25 = sum([prob_local[i] * prob_visit[j] for i in range(6) for j in range(6) if i+j < 3])
    p_over = round((1 - prob_under_25) * 100, 2)
    p_btts = round(((1 - prob_local[0]) * (1 - prob_visit[0])) * 100, 2)
    
    cuota_over_justa = round(100 / (p_over if p_over > 0 else 1) * 1.05, 2)
    cuota_btts_justa = round(100 / (p_btts if p_btts > 0 else 1) * 1.05, 2)

    return {
        "xg_local": round(xg_local, 2), "xg_visitante": round(xg_visit, 2), "prob_over_25": p_over, "prob_btts": p_btts,
        "cuota_over_minima": cuota_over_justa if cuota_over_justa < 15.0 else 1.10, "cuota_btts_minima": cuota_btts_justa if cuota_btts_justa < 15.0 else 1.10
    }

def consulting_gemini_analisis(estadisticas, local, visitante, corners_avg, tarjetas_avg):
    prompt = f"Actúa como analista experto de apuestas. Evalúa: {local} vs {visitante} | xG: {estadisticas['xg_local']}-{estadisticas['xg_visitante']}. Sugiere una combinada corta de Goles, Córners promedio ({corners_avg}) y Tarjetas ({tarjetas_avg}) para 'Crea tu apuesta'. Máximo 3 líneas."
    try:
        if isinstance(CUOTAS_MONITOR["gemini"], int) and CUOTAS_MONITOR["gemini"] > 0:
            CUOTAS_MONITOR["gemini"] -= 1
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        return response.text.strip()
    except: return "⚠️ Análisis no disponible."

# --- 8. HANDLERS TELEGRAM ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("🤖 *Value Betting Engine Premium Activo*\nUsa el menú para ver la agenda o procesar llaves:", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("hoy"))
async def cmd_hoy(message: types.Message):
    await procesar_y_enviar_agenda(message.chat.id, message)

@dp.callback_query(lambda c: c.data == "ver_partidos_hoy")
async def boton_hoy_callback(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await procesar_y_enviar_agenda(callback_query.from_user.id, callback_query.message, editar=True)

async def procesar_y_enviar_agenda(chat_id, target_msg, editar=False):
    aviso = "⏳ Rastreando agenda de partidos para el día de hoy..."
    msg_espera = await target_msg.edit_text(aviso) if editar else await bot.send_message(chat_id, aviso)
    
    agenda = consultar_partidos_del_dia()
    if not agenda:
        vacio = "📅 *AGENDA DE HOY:*\n\nℹ️ No hay partidos de las ligas del plan programados para hoy.\n_(Nota: Las ligas europeas están en receso estival de pretemporada y vísperas del Mundial)_."
        return await msg_espera.edit_text(vacio, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())
        
    texto = "📅 *PARTIDOS PROGRAMADOS PARA HOY:*\n\n"
    for p in agenda:
        texto += f"🏆 *[{p['liga']}]* `{p['hora']}` | `{p['local']} vs {p['visitante']}`\n"
    texto += "\n💡 _Copia los nombres y usa `/analizar Local vs Visitante` para procesar el valor de las cuotas._"
    await msg_espera.edit_text(texto, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    texto = message.text.replace("@Cristian_prediccionesbot", "").replace("/analizar", "").strip()
    if " vs " not in texto: return await message.reply("⚠️ Usa: `/analizar Equipo A vs Equipo B`", reply_markup=obtener_teclado_interactivo())
    eq_local, eq_visit = texto.split(" vs ")
    msg = await message.reply("⏳ *[░░░░░░░░░░] 0%* Iniciando consulta...")

    await msg.edit_text(f"⏳ *[███░░░░░░░] 30%* Escaneando local: {eq_local}")
    stats_local = buscar_datos_equipo(eq_local)
    await msg.edit_text(f"⏳ *[██████░░░░] 60%* Escaneando visitante: {eq_visit}")
    stats_visit = buscar_datos_equipo(eq_visit)

    if not stats_local or not stats_visit:
        return await msg.edit_text("❌ Datos insuficientes en servidores.", reply_markup=obtener_teclado_interactivo())

    await msg.edit_text("⏳ *[█████████░] 90%* Calculando cuotas de valor (+EV)...")
    estadisticas = calcular_probabilidades(stats_local, stats_visit)
    corners_avg = round((stats_local['corners'] + stats_visit['corners']) / 2, 1)
    tarjetas_avg = round((stats_local['tarjetas'] + stats_visit['tarjetas']) / 2, 1)
    
    partido_id = guardar_prediccion(stats_local['name'], stats_visit['name'], estadisticas['prob_over_25'], estadisticas['prob_btts'])
    idea_apuesta = consulting_gemini_analisis(estadisticas, stats_local['name'], stats_visit['name'], corners_avg, tarjetas_avg)
    token_info = f"{CUOTAS_MONITOR['gemini']}/15 RPM" if isinstance(CUOTAS_MONITOR['gemini'], int) else "Free"
    
    texto_final = (
        f"🆔 *ANÁLISIS DE VALOR: #{partido_id}*\n⚽ *{stats_local['name']} vs {stats_visit['name']}*\n🔬 _L: {stats_local['fuente']} | V: {stats_visit['fuente']}_\n\n"
        f"📊 *PROYECCIÓN POISSON:*\n🔹 xG: {estadisticas['xg_local']} - {estadisticas['xg_visitante']}\n"
        f"📈 Prob. Over 2.5: {estadisticas['prob_over_25']}% | *Cuota:* `{estadisticas['cuota_over_minima']}+`\n"
        f"🔥 Prob. BTTS: {estadisticas['prob_btts']}% | *Cuota:* `{estadisticas['cuota_btts_minima']}+`\n"
        f"🚩 Córners: ~{corners_avg} | 🟨 Tarjetas: ~{tarjetas_avg}\n\n"
        f"🛠️ *CREA TU APUESTA (IA):*\n`{idea_apuesta}`\n\n"
        f"📋 *MONITOR SERVIDORES:*\n🌐 _Football-Data:_ {CUOTAS_MONITOR['football_data']} | ⚡ _API-Sports:_ {CUOTAS_MONITOR['api_sports']} | 🧠 _Gemini:_ {token_info}\n\n"
        f"📥 `/resultado {partido_id} GolesLocal-GolesVisitante`"
    )
    await msg.edit_text(texto_final, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("resultado"))
async def registrar_resultado(message: types.Message):
    argumentos = message.text.replace("/resultado", "").strip().split()
    if len(argumentos) != 2: return await message.reply("⚠️ Usa: `/resultado ID Marcador`", reply_markup=obtener_teclado_interactivo())
    prediccion_id, marcador = argumentos
    try:
        goles_l, goles_v = map(int, marcador.split("-"))
        if registrar_resultado_db(prediccion_id, goles_l, goles_v):
            await message.reply(f"✅ Marcador real guardado: `{goles_l}-{goles_v}`.", reply_markup=obtener_teclado_interactivo())
        else: await message.reply("❌ ID no encontrado.", reply_markup=obtener_teclado_interactivo())
    except: await message.reply("⚠️ Formato incorrecto.", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("efectividad"))
async def mostrar_efectividad(message: types.Message):
    await procesar_y_enviar_efectividad(message.chat.id, message)

@dp.callback_query(lambda c: c.data == "ver_efectividad_ia")
async def boton_efectividad_callback(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await procesar_y_enviar_efectividad(callback_query.from_user.id, callback_query.message, editar=True)

async def procesar_y_enviar_efectividad(chat_id, target_msg, editar=False):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT local, visitante, prob_over, prob_btts, goles_local_real, goles_visit_real FROM predicciones WHERE estado = 'FINALIZADO'")
    partidos = cursor.fetchall()
    conn.close()
    if not partidos:
        vacio = "ℹ️ No hay registros finalizados en esta sesión."
        if editar: return await target_msg.edit_text(vacio, reply_markup=obtener_teclado_interactivo())
        else: return await target_msg.reply(vacio, reply_markup=obtener_teclado_interactivo())
    total = len(partidos)
    ac_over = ac_btts = 0
    for p in partidos:
        if (p[2] >= 50.0 and (p[4]+p[5]) > 2) or (p[2] < 50.0 and (p[4]+p[5]) <= 2): ac_over += 1
        if (p[3] >= 50.0 and (p[4]>0 and p[5]>0)) or (p[3] < 50.0 and not (p[4]>0 and p[5]>0)): ac_btts += 1
    texto_final = f"📊 *REPORTE DE EFECTIVIDAD*\n📉 Partidos: {total}\n🎯 Over 2.5: `{round((ac_over/total)*100,1)}%` acierto\n🔥 Ambos Anotan: `{round((ac_btts/total)*100,1)}%` acierto"
    if editar: await target_msg.edit_text(texto_final, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())
    else: await bot.send_message(chat_id, texto_final, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("equipo"))
async def consulting_equipo_solo(message: types.Message):
    nombre = message.text.replace("@Cristian_prediccionesbot", "").replace("/equipo", "").strip()
    if not nombre: return await message.reply("⚠️ Indica el equipo.", reply_markup=obtener_teclado_interactivo())
    msg = await message.reply("🔍 Buscando...")
    data = buscar_datos_equipo(nombre)
    if not data: return await msg.edit_text("❌ Sin datos.", reply_markup=obtener_teclado_interactivo())
    texto = f"📋 *MÉTRICAS VERIFICADAS*\n⚽ *Equipo:* {data['name']}\n🧬 _Origen: {data['fuente']}_\n\n🔹 Goles Anotados: {round(data['gf'], 2)}\n🔸 Goles Recibidos: {round(data['gc'], 2)}\n"
    await msg.edit_text(texto, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

async def on_startup(bot: Bot): 
    inicializar_db()
    await bot.set_webhook(WEBHOOK_URL)

def main():
    dp.startup.register(on_startup)
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

if __name__ == "__main__": main()
