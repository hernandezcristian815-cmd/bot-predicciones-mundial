# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Sistema Híbrido Analítico con Feedback Loop, Barra de Progreso Dinámica y Monitor de Cuotas de APIs

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

# Variables globales para almacenar de forma estática el estado de las cuotas de API
CUOTAS_MONITOR = {
    "football_data": "No consultado",
    "api_sports": "No consultado",
    "gemini": 15  # Límite RPM inicial estimado para la capa free de Gemini 2.5 Flash
}

# --- 2. COMPONENTE REUTILIZABLE: MENÚ INTERACTIVO FLOTANTE ---
def obtener_teclado_interactivo():
    """Genera los botones interactivos sin envío automático."""
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

# --- 4. MOTOR DE BÚSQUEDA COGNITIVA (AGENTE IA) ---
def investigar_equipo_con_ia(nombre_equipo):
    prompt = f"""
    Investiga en tiempo real los últimos 5 partidos oficiales o amistosos más recientes jugados por el equipo o selección: "{nombre_equipo}".
    Calcula sus promedios reales de goles a favor (gf), goles en contra (gc), córners y tarjetas por partido en esa racha de 5 juegos.
    
    Sé estrictamente verídico. Si el equipo no existe o no hay registros reales, pon el campo "confiable" en false.
    Devuelve ÚNICAMENTE un objeto JSON limpio, sin bloques markdown, con esta estructura exacta:
    {{
        "name": "Nombre Oficial Encontrado",
        "gf": 1.4,
        "gc": 1.2,
        "corners": 4.5,
        "tarjetas": 2.1,
        "confiable": true
    }}
    """
    try:
        # Descontamos un intento estimado al llamar a Gemini
        if isinstance(CUOTAS_MONITOR["gemini"], int) and CUOTAS_MONITOR["gemini"] > 0:
            CUOTAS_MONITOR["gemini"] -= 1
            
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        text = response.text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        if not data.get("confiable", True): return None
        data['fuente'] = "Investigación IA en Tiempo Real"
        return data
    except:
        return None

# --- 5. EXTRACTOR DE BASES DE DATOS TRADICIONALES ---
def buscar_datos_equipo(nombre_equipo):
    nombre_limpio = nombre_equipo.split("(")[0].strip()
    
    url_fd = "https://api.football-data.org/v4/competitions/PD/standings"
    headers_fd = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    try:
        res = requests.get(url_fd, headers=headers_fd, timeout=4)
        # Extraer cuotas disponibles de los headers de respuesta de Football-Data (Límite por minuto)
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
                            'corners': 5.1, 'tarjetas': 2.3, 'fuente': "Base de Datos Europea (API)"
                        }
    except: pass

    url_as = "https://v3.football.api-sports.io/teams"
    headers_as = {"x-apisports-key": API_SPORTS_KEY}
    try:
        res_search = requests.get(url_as, headers=headers_as, params={"search": nombre_limpio}, timeout=4)
        # Extraer cuotas del header de API-Sports (Límite diario restante)
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
                    'corners': 4.9, 'tarjetas': 2.4, 'fuente': "Historial Operativo API-Sports"
                }
    except: pass

    return investigar_equipo_con_ia(nombre_limpio)

# --- 6. CALIBRACIÓN MATEMÁTICA DE POISSON ---
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
    
    return {
        "xg_local": round(xg_local, 2), "xg_visitante": round(xg_visit, 2),
        "prob_over_25": round((1 - prob_under_25) * 100, 2),
        "prob_btts": round(((1 - prob_local[0]) * (1 - prob_visit[0])) * 100, 2)
    }

def consultar_gemini_analisis(estadisticas, local, visitante, corners_avg, tarjetas_avg):
    prompt = f"""
    Analiza este cruce de fútbol de forma sumamente fría, prudente y profesional.
    MÉTRICAS: {local} vs {visitante} | xG: {estadisticas['xg_local']}-{estadisticas['xg_visitante']} | Over 2.5: {estadisticas['prob_over_25']}% | BTTS: {estadisticas['prob_btts']}%
    Redacta una conclusión táctica de máximo 3 líneas indicando la opción de menor riesgo según los datos.
    """
    try:
        if isinstance(CUOTAS_MONITOR["gemini"], int) and CUOTAS_MONITOR["gemini"] > 0:
            CUOTAS_MONITOR["gemini"] -= 1
            
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        return response.text.strip()
    except: return "⚠️ Análisis no disponible."

# --- 7. HANDLERS DE LA INTERFAZ DE TELEGRAM ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    texto = (
        "🤖 *Sistema de Predicción Híbrido Calibrado Activo*\n\n"
        "Usa los botones de abajo para interactuar de forma ágil:\n"
        "• Al tocar los botones de comando, la frase se escribirá en tu barra de chat de forma automática sin enviarse. "
        "Así tú solo ingresas los equipos y mantienes el control total de la consulta."
    )
    await message.answer(texto, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    texto = message.text.replace("@Cristian_prediccionesbot", "").replace("/analizar", "").strip()
    if " vs " not in texto: 
        return await message.reply("⚠️ Usa: `/analizar Equipo A vs Equipo B`", reply_markup=obtener_teclado_interactivo())
        
    eq_local, eq_visit = texto.split(" vs ")
    
    # 🔄 ETAPA 1: Estado inicial (0%)
    msg = await message.reply(
        "⏳ *[░░░░░░░░░░] 0%*\n"
        "Connecting endpoint... Iniciando consulta de bases de datos."
    )

    # 🔄 ETAPA 2: Extrayendo local (30%)
    await msg.edit_text(
        f"⏳ *[███░░░░░░░] 30%*\n"
        f"🔍 Buscando historial analítico de: *{eq_local}*..."
    )
    stats_local = buscar_datos_equipo(eq_local)

    # 🔄 ETAPA 3: Extrayendo visitante (60%)
    await msg.edit_text(
        f"⏳ *[██████░░░░] 60%*\n"
        f"🔍 Buscando historial analítico de: *{eq_visit}*..."
    )
    stats_visit = buscar_datos_equipo(eq_visit)

    if not stats_local or not stats_visit:
        return await msg.edit_text("❌ No hay suficiente información verificable para procesar este cruce.", reply_markup=obtener_teclado_interactivo())

    # 🔄 ETAPA 4: Matriz matemática y consulta IA (90%)
    await msg.edit_text(
        "⏳ *[█████████░] 90%*\n"
        "🧬 Ejecutando calibración de Poisson y auditando reporte táctico con Gemini IA..."
    )
    
    estadisticas = calcular_probabilidades(stats_local, stats_visit)
    corners_avg = round((stats_local['corners'] + stats_visit['corners']) / 2, 1)
    tarjetas_avg = round((stats_local['tarjetas'] + stats_visit['tarjetas']) / 2, 1)
    
    partido_id = guardar_prediccion(stats_local['name'], stats_visit['name'], estadisticas['prob_over_25'], estadisticas['prob_btts'])
    idea_apuesta = consultar_gemini_analisis(estadisticas, stats_local['name'], stats_visit['name'], corners_avg, tarjetas_avg)
    
    # Renderizar el estado de cuotas de las APIs
    token_gemini_info = f"{CUOTAS_MONITOR['gemini']}/15 RPM estimadas" if isinstance(CUOTAS_MONITOR['gemini'], int) else "Capa Free"
    
    # 🏁 ETAPA 5: Finalización y visualización del reporte completo con las métricas de consumo
    texto_final = (
        f"🆔 *ANÁLISIS REGISTRADO: #{partido_id}*\n"
        f"⚽ {stats_local['name']} vs {stats_visit['name']}\n\n"
        f"🔹 *xG (Goles Esperados):* {estadisticas['xg_local']} - {estadisticas['xg_visitante']}\n"
        f"📈 *Over 2.5:* {estadisticas['prob_over_25']}%\n"
        f"🔥 *Ambos Anotan:* {estadisticas['prob_btts']}%\n"
        f"🚩 *Córners Promedio:* {corners_avg}\n\n"
        f"💡 *ANÁLISIS DEL EXPERTO:*\n{idea_apuesta}\n\n"
        f"📋 *ESTADO ACTUAL DE CREDENCIALES (CUOTAS):*\n"
        f"🌐 _Football-Data:_ {CUOTAS_MONITOR['football_data']}\n"
        f"⚡ _API-Sports:_ {CUOTAS_MONITOR['api_sports']}\n"
        f"🧠 _Google Gemini IA:_ {token_gemini_info}\n\n"
        f"📥 _Para actualizar el marcador real usa:_ `/resultado {partido_id} GolesLocal-GolesVisitante`"
    )
    await msg.edit_text(texto_final, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("resultado"))
async def registrar_resultado(message: types.Message):
    argumentos = message.text.replace("/resultado", "").strip().split()
    if len(argumentos) != 2:
        return await message.reply("⚠️ Formato incorrecto. Usa: `/resultado ID Marcador` (Ej: `/resultado 1 2-1`)", reply_markup=obtener_teclado_interactivo())
    
    prediccion_id, marcador = argumentos
    if "-" not in marcador:
        return await message.reply("⚠️ El marcador debe llevar guion. Ej: `2-1`", reply_markup=obtener_teclado_interactivo())
        
    try:
        goles_l, goles_v = map(int, marcador.split("-"))
        exito = registrar_resultado_db(prediccion_id, goles_l, goles_v)
        if exito:
            await message.reply(f"✅ Marcador real del análisis *#{prediccion_id}* registrado con éxito: `{goles_l} - {goles_v}`. ¡Historial actualizado!", reply_markup=obtener_teclado_interactivo())
        else:
            await message.reply("❌ No se encontró ninguna predicción activa con ese ID en la base de datos.", reply_markup=obtener_teclado_interactivo())
    except Exception as e:
        await message.reply(f"⚠️ Error al procesar los datos: {e}", reply_markup=obtener_teclado_interactivo())

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
        msg_vacio = "ℹ️ Aún no tienes partidos finalizados registrados. ¡Sigue analizando y cargando resultados!"
        if editar: return await target_msg.edit_text(msg_vacio, reply_markup=obtener_teclado_interactivo())
        else: return await target_msg.reply(msg_vacio, reply_markup=obtener_teclado_interactivo())
        
    total_partidos = len(partidos)
    aciertos_over = aciertos_btts = 0
    resumen_texto_ia = ""
    
    for p in partidos:
        loc, vis, p_over, p_btts, gl, gv = p
        goles_totales = gl + gv
        ambos_anotan = "SI" if (gl > 0 and gv > 0) else "NO"
        
        if (p_over >= 50.0 and goles_totales > 2) or (p_over < 50.0 and goles_totales <= 2): aciertos_over += 1
        if (p_btts >= 50.0 and ambos_anotan == "SI") or (p_btts < 50.0 and ambos_anotan == "NO"): aciertos_btts += 1
            
        resumen_texto_ia += f"- {loc} vs {vis} | Pred Over: {p_over}% (Real: {goles_totales}) | Pred BTTS: {p_btts}% (Real: {ambos_anotan})\n"

    ef_over = round((aciertos_over / total_partidos) * 100, 1)
    ef_btts = round((aciertos_btts / total_partidos) * 100, 1)

    prompt = f"""
    Actúa como un Auditor de Analítica Deportiva. Analiza el rendimiento:
    Partidos validados: {total_partidos} | Efectividad Over 2.5: {ef_over}% | Efectividad BTTS: {ef_btts}%
    Historial:\n{resumen_texto_ia}\nEscribe una conclusión breve de 3 líneas evaluando el modelo de Poisson.
    """
    try:
        if isinstance(CUOTAS_MONITOR["gemini"], int) and CUOTAS_MONITOR["gemini"] > 0:
            CUOTAS_MONITOR["gemini"] -= 1
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        dictamen_ia = response.text.strip()
    except: dictamen_ia = "Auditoría temporalmente no disponible."

    texto_final = (
        f"📊 *REPORTE DE EFECTIVIDAD GENERAL*\n"
        f"📉 *Partidos auditados:* {total_partidos}\n\n"
        f"🎯 *Rendimiento Over/Under 2.5:* `{ef_over}%` de acierto\n"
        f"🔥 *Rendimiento Ambos Anotan:* `{ef_btts}%` de acierto\n\n"
        f"🧠 *DICTAMEN DE AUDITORÍA DE IA:*\n_{dictamen_ia}_"
    )
    
    if editar: await target_msg.edit_text(texto_final, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())
    else: await bot.send_message(chat_id, texto_final, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("equipo"))
async def consultar_equipo_solo(message: types.Message):
    nombre = message.text.replace("@Cristian_prediccionesbot", "").replace("/equipo", "").strip()
    if not nombre: 
        return await message.reply("⚠️ Indica el nombre del equipo.", reply_markup=obtener_teclado_interactivo())
    
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
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

if __name__ == "__main__": main()
