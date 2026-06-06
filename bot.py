# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Value Betting Engine Premium - Totalmente Calibrado, Híbrido y Blindado

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

# Monitor global dinámico de consumo de credenciales
CUOTAS_MONITOR = {
    "football_data": "No consultado",
    "api_sports": "No consultado",
    "gemini": 15
}

# --- 2. COMPONENTE REUTILIZABLE: MENÚ INTERACTIVO FLOTANTE ---
def obtener_teclado_interactivo():
    """Genera los botones interactivos que escriben en la barra sin enviar automáticamente."""
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="📊 Analizar Partido", switch_inline_query_current_chat="/analizar "),
        types.InlineKeyboardButton(text="🔍 Buscar Equipo", switch_inline_query_current_chat="/equipo ")
    )
    builder.row(
        types.InlineKeyboardButton(text="📈 Ver Efectividad", callback_data="ver_efectividad_ia")
    )
    return builder.as_markup()

# --- 3. GESTIÓN DE BASE DE DATOS (SQLITE) ---
def inicializar_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS predicciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
            local TEXT,
            visitante TEXT,
            prob_over REAL,
            prob_btts REAL,
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
    cursor.execute("""
        INSERT INTO predicciones (fecha, local, visitante, prob_over, prob_btts)
        VALUES (?, ?, ?, ?, ?)
    """, (fecha_hoy, local, visitante, prob_over, prob_btts))
    id_generado = cursor.lastrowid
    conn.commit()
    conn.close()
    return id_generado

def registrar_resultado_db(prediccion_id, goles_l, goles_v):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE predicciones 
        SET goles_local_real = ?, goles_visit_real = ?, estado = 'FINALIZADO'
        WHERE id = ?
    """, (goles_l, goles_v, prediccion_id))
    filas_afectadas = cursor.rowcount
    conn.commit()
    conn.close()
    return filas_afectadas > 0

# --- 4. MOTOR DE BÚSQUEDA COGNITIVA (AGENTE IA DE RESPALDO) ---
def investigar_equipo_con_ia(nombre_equipo):
    """Rastrea el rendimiento reciente de un equipo. Si la liga está inactiva, computa tendencias de peso."""
    prompt = f"""
    Investiga el rendimiento deportivo y goles recientes de: "{nombre_equipo}".
    Si compite en liga local actual, extrae sus métricas de los últimos 5 partidos oficiales.
    Si el torneo está en pausa o la data es escasa, deduce promedios realistas basados en su desempeño histórico cercano.
    
    Devuelve ÚNICAMENTE un objeto JSON limpio, sin bloques markdown de código, con esta estructura exacta:
    {{
        "name": "Nombre Oficial Encontrado",
        "gf": 1.35,
        "gc": 1.15,
        "corners": 4.8,
        "tarjetas": 2.2,
        "informacion_historica": true
    }}
    """
    try:
        if isinstance(CUOTAS_MONITOR["gemini"], int) and CUOTAS_MONITOR["gemini"] > 0:
            CUOTAS_MONITOR["gemini"] -= 1
            
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        text = response.text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        data['fuente'] = "Inferencia de Tendencia Histórica (IA)"
        return data
    except:
        return None

# --- 5. EXTRACTOR DE BASES DE DATOS TRADICIONALES ---
def buscar_datos_equipo(nombre_equipo):
    nombre_limpio = nombre_equipo.split("(")[0].strip()
    
    # Base 1: Football-Data
    url_fd = "https://api.football-data.org/v4/competitions/PD/standings"
    headers_fd = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    try:
        res = requests.get(url_fd, headers=headers_fd, timeout=4)
        if "X-Requests-Available-Minute" in res.headers:
            CUOTAS_MONITOR["football_data"] = f"{res.headers['X-Requests-Available-Minute']} req/min"
        if res.status_code == 200:
            tabla = next((t for t in res.json().get('standings', []) if t['type'] == 'TOTAL'), None)
            if tabla:
                for row in tabla['table']:
                    if nombre_limpio.lower() in row['team']['name'].lower():
                        partidos = row['playedGames'] if row['playedGames'] > 0 else 1
                        return {
                            'name': row['team']['name'], 'gf': row['goalsFor'] / partidos, 'gc': row['goalsAgainst'] / partidos, 
                            'corners': 5.2, 'tarjetas': 2.1, 'fuente': "Base de Datos Europea (API)"
                        }
    except: pass

    # Base 2: API-Sports
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
                return {
                    'name': nombre_oficial, 'gf': g_favor / partidos, 'gc': g_contra / partidos,
                    'corners': 4.7, 'tarjetas': 2.5, 'fuente': "Historial Operativo API-Sports"
                }
    except: pass

    # COMPLEMENTO IA TOTALMENTE CONECTADO Y REPARADO
    return investigar_equipo_con_ia(nombre_limpio)

# --- 6. DISTRIBUCIÓN DE POISSON CALIBRADA Y VALOR DE CUOTAS ---
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
    
    # Cálculo de cuotas mínimas con margen de resguardo del 5% (+EV)
    cuota_over_justa = round(100 / (p_over if p_over > 0 else 1) * 1.05, 2)
    cuota_btts_justa = round(100 / (p_btts if p_btts > 0 else 1) * 1.05, 2)

    return {
        "xg_local": round(xg_local, 2), "xg_visitante": round(xg_visit, 2),
        "prob_over_25": p_over, "prob_btts": p_btts,
        "cuota_over_minima": cuota_over_justa if cuota_over_justa < 15.0 else 1.10,
        "cuota_btts_minima": cuota_btts_justa if cuota_btts_justa < 15.0 else 1.10
    }

def consultar_gemini_analisis(estadisticas, local, visitante, corners_avg, tarjetas_avg):
    prompt = f"""
    Actúa como un analista experto en apuestas deportivas. Evalúa el cruce:
    {local} vs {visitante} | xG: {estadisticas['xg_local']}-{estadisticas['xg_visitante']} | Over 2.5: {estadisticas['prob_over_25']}% (Cuota sugerida: >{estadisticas['cuota_over_minima']}) | BTTS: {estadisticas['prob_btts']}% (Cuota sugerida: >{estadisticas['cuota_btts_minima']})
    
    Diseña una recomendación estructurada para la sección "Crea tu apuesta" uniendo Goles, Córners combinados ({corners_avg}) y Tarjetas ({tarjetas_avg}). Redacta con frialdad y precisión en máximo 4 líneas.
    """
    try:
        if isinstance(CUOTAS_MONITOR["gemini"], int) and CUOTAS_MONITOR["gemini"] > 0:
            CUOTAS_MONITOR["gemini"] -= 1
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        return response.text.strip()
    except: return "⚠️ Análisis de valor no disponible."

# --- 7. HANDLERS DE LA INTERFAZ DE TELEGRAM ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    texto = (
        "🤖 *Value Betting Engine Premium Activo*\n\n"
        "Usa los botones dinámicos de abajo. Al hacer clic, el comando aparecerá escrito en tu teclado de forma instantánea para que tú solo agregues los equipos:"
    )
    await message.answer(texto, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    # LIMPIEZA ABSOLUTA DE ALIAS EN CADENAS
    texto = message.text.replace("@Cristian_prediccionesbot", "").replace("/analizar", "").strip()
    if " vs " not in texto: 
        return await message.reply("⚠️ Usa: `/analizar Equipo A vs Equipo B`", reply_markup=obtener_teclado_interactivo())
        
    eq_local, eq_visit = texto.split(" vs ")
    
    # 🔄 PROGRESO 0%
    msg = await message.reply("⏳ *[░░░░░░░░░░] 0%* Abriendo pasarela de peticiones...")

    # 🔄 PROGRESO 30%
    await msg.edit_text(f"⏳ *[███░░░░░░░] 30%* Consultando registros de local: *{eq_local}*...")
    stats_local = buscar_datos_equipo(eq_local)

    # 🔄 PROGRESO 60%
    await msg.edit_text(f"⏳ *[██████░░░░] 60%* Consultando registros de visitante: *{eq_visit}*...")
    stats_visit = buscar_datos_equipo(eq_visit)

    if not stats_local or not stats_visit:
        return await msg.edit_text("❌ Error. Datos insuficientes en APIs y Agentes de IA.", reply_markup=obtener_teclado_interactivo())

    # 🔄 PROGRESO 90%
    await msg.edit_text("⏳ *[█████████░] 90%* Operando matrices de Poisson y estimando valor de cuotas...")
    
    estadisticas = calcular_probabilidades(stats_local, stats_visit)
    corners_avg = round((stats_local['corners'] + stats_visit['corners']) / 2, 1)
    tarjetas_avg = round((stats_local['tarjetas'] + stats_visit['tarjetas']) / 2, 1)
    
    partido_id = guardar_prediccion(stats_local['name'], stats_visit['name'], estadisticas['prob_over_25'], estadisticas['prob_btts'])
    idea_apuesta = consultar_gemini_analisis(estadisticas, stats_local['name'], stats_visit['name'], corners_avg, tarjetas_avg)
    
    token_gemini_info = f"{CUOTAS_MONITOR['gemini']}/15 RPM" if isinstance(CUOTAS_MONITOR['gemini'], int) else "Free"
    
    # 🏁 RESPUESTA FINAL CON MENÚ FLOTANTE INCORPORADO
    texto_final = (
        f"🆔 *ANÁLISIS DE VALOR: #{partido_id}*\n"
        f"⚽ *{stats_local['name']} vs {stats_visit['name']}*\n"
        f"🔬 _Origen L: {stats_local['fuente']} | V: {stats_visit['fuente']}_\n\n"
        f"📊 *PROYECCIÓN ESTADÍSTICA POISSON:*\n"
        f"🔹 Goles Esperados (xG): {estadisticas['xg_local']} - {estadisticas['xg_visitante']}\n"
        f"📈 Prob. Over 2.5: {estadisticas['prob_over_25']}% | *Buscar Cuota:* `{estadisticas['cuota_over_minima']}+`\n"
        f"🔥 Prob. Ambos Anotan: {estadisticas['prob_btts']}% | *Buscar Cuota:* `{estadisticas['cuota_btts_minima']}+`\n"
        f"🚩 Córners Promedio: ~{corners_avg} | 🟨 Tarjetas: ~{tarjetas_avg}\n\n"
        f"🛠️ *SUGERENCIA CREA TU APUESTA (IA):*\n`{idea_apuesta}`\n\n"
        f"📋 *MONITOR OPERATIVO DE SERVIDORES (CUOTAS):*\n"
        f"🌐 _Football-Data:_ {CUOTAS_MONITOR['football_data']}\n"
        f"⚡ _API-Sports:_ {CUOTAS_MONITOR['api_sports']}\n"
        f"🧠 _Google Gemini:_ {token_gemini_info}\n\n"
        f"📥 _Registrar marcador real:_ `/resultado {partido_id} GolesLocal-GolesVisitante`"
    )
    await msg.edit_text(texto_final, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("resultado"))
async def registrar_resultado(message: types.Message):
    argumentos = message.text.replace("/resultado", "").strip().split()
    if len(argumentos) != 2: 
        return await message.reply("⚠️ Usa: `/resultado ID Marcador` (Ej: `/resultado 1 2-1`)", reply_markup=obtener_teclado_interactivo())
    
    prediccion_id, marcador = argumentos
    try:
        goles_l, goles_v = map(int, marcador.split("-"))
        if registrar_resultado_db(prediccion_id, goles_l, goles_v):
            await message.reply(f"✅ Marcador real del análisis *#{prediccion_id}* guardado: `{goles_l} - {goles_v}`. ¡Matriz de efectividad actualizada!", reply_markup=obtener_teclado_interactivo())
        else:
            await message.reply("❌ ID de análisis no encontrado en la base de datos local.", reply_markup=obtener_teclado_interactivo())
    except: 
        await message.reply("⚠️ Formato de marcador incorrecto. Ej: `2-1`", reply_markup=obtener_teclado_interactivo())

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
        vacio = "ℹ️ No hay registros finalizados en esta sesión. Carga marcadores usando `/resultado`."
        if editar: return await target_msg.edit_text(vacio, reply_markup=obtener_teclado_interactivo())
        else: return await target_msg.reply(vacio, reply_markup=obtener_teclado_interactivo())
        
    total = len(partidos)
    ac_over = ac_btts = 0
    
    for p in partidos:
        if (p[2] >= 50.0 and (p[4]+p[5]) > 2) or (p[2] < 50.0 and (p[4]+p[5]) <= 2): ac_over += 1
        if (p[3] >= 50.0 and (p[4]>0 and p[5]>0)) or (p[3] < 50.0 and not (p[4]>0 and p[5]>0)): ac_btts += 1

    texto_final = (
        f"📊 *REPORTE DE EFECTIVIDAD REAL*\n"
        f"📉 *Partidos auditados:* {total}\n\n"
        f"🎯 *Rendimiento Over/Under 2.5:* `{round((ac_over/total)*100, 1)}%` de acierto\n"
        f"🔥 *Rendimiento Ambos Anotan:* `{round((ac_btts/total)*100, 1)}%` de acierto"
    )
    if editar: await target_msg.edit_text(texto_final, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())
    else: await bot.send_message(chat_id, texto_final, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("equipo"))
async def consultar_equipo_solo(message: types.Message):
    # LIMPIEZA ABSOLUTA DE ALIAS
    nombre = message.text.replace("@Cristian_prediccionesbot", "").replace("/equipo", "").strip()
    if not nombre: return await message.reply("⚠️ Indica el nombre del equipo.", reply_markup=obtener_teclado_interactivo())
    
    msg = await message.reply(f"🔍 Rastreando estadísticas verídicas de *{nombre}*...")
    data = buscar_datos_equipo(nombre)
    if not data: return await msg.edit_text("❌ No se encontraron datos para este equipo.", reply_markup=obtener_teclado_interactivo())
    
    texto = f"📋 *MÉTRICAS VERIFICADAS*\n⚽ *Equipo:* {data['name']}\n🧬 _Origen: {data['fuente']}_\n\n🔹 Goles Anotados: {round(data['gf'], 2)}\n🔸 Goles Recibidos: {round(data['gc'], 2)}\n🚩 Córners: {data['corners']}\n🟨 Tarjetas: {data['tarjetas']}\n"
    await msg.edit_text(texto, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

# --- 8. SERVIDOR WEB Y ACTIVACIÓN ---
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
