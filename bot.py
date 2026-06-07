# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Value Betting Engine Premium v16.1.2-GROQ (NameError Fixed & Fully Stable)

import os
import json
import sqlite3
import re
import asyncio
import aiohttp
from datetime import datetime
from google import genai
from scipy.stats import poisson
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- 1. CONFIGURACIÓN, CREDENCIALES Y CONSTANTES ---
VERSION_ACTUAL = "v16.1.2-GROQ" 

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_KEY")
FOOTBALL_DATA_KEY = os.getenv("API_FOOTBALL_KEY") 
API_SPORTS_KEY = os.getenv("API_SPORTS_KEY")       

# Variables de la pasarela de respaldo (Groq LPU)
RESPALDO_API_KEY = os.getenv("RESPALDO_API_KEY") 
RESPALDO_API_URL = os.getenv("RESPALDO_API_URL", "https://api.groq.com/openai/v1/chat/completions")
MODELO_GROQ = "llama3-70b-8192"  # Modelo óptimo de Groq para análisis táctico estructurado

WEB_URL = os.getenv("RENDER_EXTERNAL_URL", "https://tu-app.onrender.com") 
WEBHOOK_PATH = f"/webhook/{TELEGRAM_TOKEN}"
WEBHOOK_URL = f"{WEB_URL}{WEBHOOK_PATH}"

client = genai.Client(api_key=GEMINI_API_KEY)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

DB_NAME = "apuestas.db"
LIGAS_MAPA = {"WC", "CL", "PL", "ELC", "FL1", "BL1", "SA", "PD", "PPL", "DED", "BSA"}

# --- 2. GENERADOR DE TECLADO INTERACTIVO ---
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
    builder.row(
        types.InlineKeyboardButton(text=f"⚙️ Engine Núcleo: {VERSION_ACTUAL}", callback_data="info_version")
    )
    return builder.as_markup()

# --- 3. BASE DE DATOS LOCAL ---
def inicializar_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS predicciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, local TEXT, visitante TEXT,
            prob_over REAL, prob_btts REAL, goles_local_real INTEGER DEFAULT NULL,
            goles_visit_real INTEGER DEFAULT NULL, estado TEXT DEFAULT 'PENDIENTE'
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

# --- 4. CONSULTA ASÍNCROMA DE AGENDAS ---
async def consultar_partidos_del_dia():
    url_matches = "https://api.football-data.org/v4/matches"
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    partidos_detectados = []
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url_matches, headers=headers, timeout=4.0) as response:
                if response.status == 200:
                    data = await response.json()
                    matches = data.get("matches", [])
                    for m in matches:
                        cod_liga = m.get("competition", {}).get("code")
                        if cod_liga in LIGAS_MAPA:
                            partidos_detectados.append({
                                "liga": cod_liga,
                                "local": m["homeTeam"]["name"],
                                "visitante": m["awayTeam"]["name"],
                                "hora": m["utcDate"][11:16]
                            })
    except:
        pass
        
    if not partidos_detectados and API_SPORTS_KEY:
        url_as = "https://v3.football.api-sports.io/fixtures"
        headers_as = {"x-apisports-key": API_SPORTS_KEY}
        fecha_hoy = datetime.now().strftime('%Y-%m-%d')
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url_as, headers=headers_as, params={"date": fecha_hoy}, timeout=4.0) as res:
                    if res.status == 200:
                        data = await res.json()
                        fixtures = data.get("response", [])
                        for f in fixtures[:10]:
                            partidos_detectados.append({
                                "liga": f["league"]["country"][:3].upper(),
                                "local": f["teams"]["home"]["name"],
                                "visitante": f["teams"]["away"]["name"],
                                "hora": f["fixture"]["date"][11:16]
                            })
        except:
            pass
            
    return partidos_detectados

# --- 5. PASARELA DE RESPALDO: INFERENCIA DE ALTA VELOCIDAD CON GROQ ---
async def consultar_ia_respaldo(prompt):
    """Mecanismo Fallback: Si Gemini agota cuota, Groq rescata el flujo a velocidad LPU"""
    if not RESPALDO_API_KEY:
        return "⚠️ Error de Cuota: Gemini se saturó y no se detectó la clave de Groq en Render."
        
    headers = {
        "Authorization": f"Bearer {RESPALDO_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODELO_GROQ,
        "messages": [
            {
                "role": "system", 
                "content": "Eres un Tipster Analítico de Fútbol Profesional. Analizas datos matemáticos con precisión y presentas tus análisis e informes técnicos usando formato Markdown limpio."
            },
            {
                "role": "user", 
                "content": prompt
            }
        ],
        "temperature": 0.25,
        "max_tokens": 1200
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(RESPALDO_API_URL, headers=headers, json=payload, timeout=10.0) as response:
                if response.status == 200:
                    res_data = await response.json()
                    return res_data['choices'][0]['message']['content'].strip() + "\n\n⚡ _(Informe de emergencia procesado por Groq LPU)_"
                elif response.status == 429:
                    return "❌ Error Crítico: Se agotaron los límites por minuto tanto de Gemini como de Groq."
                else:
                    detalles = await response.text()
                    return f"❌ Falló pasarela Groq. Estado HTTP: {response.status}. Detalle: {detalles}"
    except Exception as e:
        return f"❌ Error en la llamada HTTP asíncrona hacia el cluster de Groq: {e}"

# --- 6. NÚCLEO ARQUITECTÓNICO HÍBRIDO (CORREGIDO DE TODO NAMEERROR) ---
async def ejecutar_sistema_cognitivo(prompt, es_json=False):
    """Conmutador inteligente: Envía el prompt a Gemini; ante un RESOURCE_EXHAUSTED redirige a Groq"""
    try:
        loop = asyncio.get_event_loop()
        
        # Corrección: Diccionario nativo directo sin depender de genai_types
        config_dict = {"response_mime_type": "application/json"} if es_json else None
        
        # Intento con el motor primario (Gemini)
        response = await loop.run_in_executor(
            None, 
            lambda: client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=config_dict
            )
        )
        return response.text.strip(), "Métricas Crudas (Gemini)" if es_json else "Gemini-2.5"
    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
            if es_json:
                prompt += " Responde estrictamente un JSON plano, sin sintaxis ni marcas de bloques markdown."
            resultado_groq = await consultar_ia_respaldo(prompt)
            return resultado_groq, "Métricas Crudas (Groq)" if es_json else "Groq LPU"
        else:
            raise e

# --- 7. EXTRACCIÓN COGNITIVA DE MÉTRICAS COMPLEMENTARIAS ---
async def obtener_datos_crudos_ia(nombre_equipo):
    prompt = f"""
    Proporciona los datos estadísticos crudos y promedios por partido del equipo o selección de fútbol: "{nombre_equipo}" en sus últimos 10 juegos oficiales.
    Devuelve estrictamente un objeto JSON con el siguiente formato, usando valores numéricos reales:
    {{"name": "{nombre_equipo}", "gf": 1.60, "gc": 1.10, "corners": 5.1, "tarjetas": 2.2, "forma": "V-E-V-D-V"}}
    No incluyas marcas markdown de código (como ```json), solo el JSON limpio.
    """
    try:
        raw_text, fuente = await ejecutar_sistema_cognitivo(prompt, es_json=True)
        raw_text = re.sub(r'^```json\s*', '', raw_text)
        raw_text = re.sub(r'\s*```$', '', raw_text)
        
        data = json.loads(raw_text)
        data['fuente'] = fuente
        return data
    except:
        return {"name": nombre_equipo, "gf": 1.30, "gc": 1.20, "corners": 4.5, "tarjetas": 2.0, "forma": "E-E-V-D-E", "fuente": "Resguardo Numérico"}

async def buscar_datos_equipo(nombre_equipo):
    nombre_limpio = nombre_equipo.strip()
    
    async with aiohttp.ClientSession() as session:
        headers_fd = {"X-Auth-Token": FOOTBALL_DATA_KEY}
        for liga in ["WC", "PL", "PD", "BSA"]:
            url_fd = f"[https://api.football-data.org/v4/competitions/](https://api.football-data.org/v4/competitions/){liga}/standings"
            try:
                async with session.get(url_fd, headers=headers_fd, timeout=2.0) as res:
                    if res.status == 200:
                        data = await res.json()
                        tabla = next((t for t in data.get('standings', []) if t['type'] == 'TOTAL'), None)
                        if tabla:
                            for row in tabla['table']:
                                name_oficial = row['team']['name']
                                if nombre_limpio.lower() in name_oficial.lower() or name_oficial.lower() in nombre_limpio.lower():
                                    partidos = row['playedGames'] if row['playedGames'] > 0 else 1
                                    return {
                                        'name': name_oficial, 'gf': row['goalsFor'] / partidos, 'gc': row['goalsAgainst'] / partidos, 
                                        'corners': 5.0, 'tarjetas': 2.1, 'forma': "Data Activa Liga", 'fuente': f"API Football-Data ({liga})"
                                    }
            except: pass

        url_as = "[https://v3.football.api-sports.io/teams](https://v3.football.api-sports.io/teams)"
        headers_as = {"x-apisports-key": API_SPORTS_KEY}
        try:
            async with session.get(url_as, headers=headers_as, params={"search": nombre_limpio}, timeout=2.0) as res_search:
                if res_search.status == 200:
                    search_data = await res_search.json()
                    teams = search_data.get("response", [])
                    if teams:
                        team_id = teams[0]["team"]["id"]
                        nombre_oficial = teams[0]["team"]["name"]
                        url_fix = f"[https://v3.football.api-sports.io/fixtures?team=](https://v3.football.api-sports.io/fixtures?team=){team_id}&last=5"
                        
                        async with session.get(url_fix, headers=headers_as, timeout=2.0) as res_fix:
                            if res_fix.status == 200:
                                fix_data = await res_fix.json()
                                fixtures = fix_data.get("response", [])
                                if fixtures:
                                    g_favor = sum([(f['goals']['home'] if f['teams']['home']['id'] == team_id else f['goals']['away']) for f in fixtures if f['goals']['home'] is not None])
                                    g_contra = sum([(f['goals']['away'] if f['teams']['home']['id'] == team_id else f['goals']['home']) for f in fixtures if f['goals']['home'] is not None])
                                    partidos = len(fixtures) if len(fixtures) > 0 else 1
                                    return {
                                        'name': nombre_oficial, 'gf': g_favor / partidos, 'gc': g_contra / partidos, 
                                        'corners': 4.8, 'tarjetas': 2.3, 'forma': "Data Activa Fixtures", 'fuente': "API API-Sports"
                                    }
        except: pass

    return await obtener_datos_crudos_ia(nombre_limpio)

# --- 8. PROCESAMIENTO MATEMÁTICO PURO (DISTRIBUCIÓN DE POISSON) ---
def calcular_probabilidades(local_stats, visit_stats):
    promedio_goles = 1.25
    
    xg_local = (local_stats["gf"] / promedio_goles) * (visit_stats["gc"] / promedio_goles) * promedio_goles
    xg_visit = (visit_stats["gf"] / promedio_goles) * (local_stats["gc"] / promedio_goles) * promedio_goles

    xg_local = max(0.15, xg_local)
    xg_visit = max(0.15, xg_visit)

    prob_local = [poisson.pmf(i, xg_local) for i in range(6)]
    prob_visit = [poisson.pmf(i, xg_visit) for i in range(6)]
    
    prob_under_25 = sum([prob_local[i] * prob_visit[j] for i in range(6) for j in range(6) if i+j < 3])
    p_over = round((1 - prob_under_25) * 100, 2)
    p_btts = round(((1 - prob_local[0]) * (1 - prob_visit[0])) * 100, 2)
    
    return {
        "xg_local": round(xg_local, 2), "xg_visitante": round(xg_visit, 2), "prob_over_25": p_over, "prob_btts": p_btts,
        "cuota_over_minima": round(100 / (p_over if p_over > 0 else 1) * 1.05, 2), "cuota_btts_minima": round(100 / (p_btts if p_btts > 0 else 1) * 1.05, 2)
    }

# --- 9. CONFIGURACIÓN DEL PROMPT ANALÍTICO ---
async def generar_informe_scouting_ia(estadisticas, local_stats, visit_stats, corners, tarjetas):
    prompt = f"""
    Actúa como un Tipster Analítico de Fútbol Profesional. Analiza el cruce de alta competencia: {local_stats['name']} vs {visit_stats['name']}.
    
    MÉTRICAS MATEMÁTICAS PROCESADAS POR EL SISTEMA (PYTHON):
    - Goles Esperados (xG): {local_stats['name']} {estadisticas['xg_local']} vs {estadisticas['xg_visitante']} {visit_stats['name']}
    - Probabilidad Over 2.5 Goles: {estadisticas['prob_over_25']}% (Cuota de Valor sugerida: >{estadisticas['cuota_over_minima']})
    - Probabilidad Ambos Anotan (BTTS): {estadisticas['prob_btts']}% (Cuota de Valor sugerida: >{estadisticas['cuota_btts_minima']})
    - Líneas de Campo Estimadas: Córners Totales ~{corners} | Tarjetas Totales ~{tarjetas}
    - Estado de Forma Reciente de Equipos: Local [{local_stats['forma']}] | Visitante [{visit_stats['forma']}]

    Redacta un informe profundo, claro y altamente técnico dividido en dos secciones obligatorias:
    📊 1. ANÁLISIS SENSORIAL Y CONTEXTUAL: Cruza el xG matemático calculado con las rachas de los equipos para argumentar el flujo esperado del juego.
    🎯 2. RECOMENDACIÓN PREMIUM (CREA TU APUESTA): Genera una combinada específica para Bet365 uniendo goles, córners y tarjetas basadas en los datos de arriba. Explica la lógica del pick.
    """
    informe, fuente_motor = await ejecutar_sistema_cognitivo(prompt, es_json=False)
    return informe, fuente_motor

# --- 10. INTERFAZ Y MANEJADORES DE TELEGRAM ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    texto_bienvenida = (
        f"🤖 *Value Betting Engine Premium Active*\n"
        f"⚙️ *Versión en producción:* `{VERSION_ACTUAL}`\n\n"
        f"Selecciona una de las funciones analíticas del menú estructurado:"
    )
    await message.answer(texto_bienvenida, reply_markup=obtener_teclado_interactivo(), parse_mode="Markdown")

@dp.message(Command("hoy"))
async def cmd_hoy(message: types.Message):
    msg_espera = await message.reply("⏳ Sincronizando agenda real de partidos de hoy...")
    await procesar_agenda_comun(msg_espera)

@dp.callback_query()
async def manejador_botones_interactivos(callback_query: types.CallbackQuery):
    await callback_query.answer()
    
    if callback_query.data == "info_version":
        await callback_query.message.answer(f"ℹ️ *Información del Sistema:*\nEstás corriendo el entorno de análisis unificado versión `{VERSION_ACTUAL}` con bypass automático hacia Groq LPU de baja latencia.", parse_mode="Markdown")
        
    elif callback_query.data == "ver_partidos_hoy":
        msg_inicial = await callback_query.message.answer("⏳ Solicitando partidos del día a los servidores...")
        await procesar_agenda_comun(msg_inicial)
        
    elif callback_query.data == "ver_efectividad_ia":
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT local, visitante, prob_over, prob_btts, goles_local_real, goles_visit_real FROM predicciones WHERE estado = 'FINALIZADO'")
        partidos = cursor.fetchall()
        conn.close()
        
        if not partidos:
            return await callback_query.message.answer(f"ℹ️ No hay registros finalizados para la versión `{VERSION_ACTUAL}`.", reply_markup=obtener_teclado_interactivo())
        
        total = len(partidos)
        ac_over = ac_btts = 0
        for p in partidos:
            if (p[2] >= 50.0 and (p[4]+p[5]) > 2) or (p[2] < 50.0 and (p[4]+p[5]) <= 2): ac_over += 1
            if (p[3] >= 50.0 and (p[4]>0 and p[5]>0)) or (p[3] < 50.0 and not (p[4]>0 and p[5]>0)): ac_btts += 1
            
        texto_efectividad = f"📊 *REPORTE DE EFECTIVIDAD REAL ({VERSION_ACTUAL}):*\n\n📉 Partidos Evaluados: `{total}`\n🎯 Over 2.5: `{round((ac_over/total)*100,1)}%` acierto\n🔥 Ambos Anotan: `{round((ac_btts/total)*100,1)}%` acierto"
        await callback_query.message.answer(texto_efectividad, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

async def procesar_agenda_comun(message_target: types.Message):
    agenda = await consultar_partidos_del_dia()
    if not agenda:
        await message_target.edit_text(f"📅 *AGENDA DE HOY ({VERSION_ACTUAL}):*\n\nℹ️ No se detectaron partidos en las APIs para el día de hoy.", parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())
        return
        
    texto = f"📅 *PARTIDOS DETECTADOS HOY ({VERSION_ACTUAL}):*\n\n"
    for p in agenda:
        texto += f"🏆 *[{p['liga']}]* `{p['hora']}` | `{p['local']} vs {p['visitante']}`\n"
    texto += "\n💡 _Copia el cruce y usa /analizar Local vs Visitante_"
    await message_target.edit_text(texto, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    argumentos = re.sub(r'^/analizar(@\w+)?\s+', '', message.text).strip()
    if " vs " not in argumentos: 
        return await message.reply("⚠️ Formato inválido. Usa:\n`/analizar Equipo Local vs Equipo Visitante`", reply_markup=obtener_teclado_interactivo())
    
    eq_local, eq_visit = argumentos.split(" vs ")
    msg = await message.reply("⏳ *[░░░░░░░░░░] 0%* Abriendo pasarelas asíncronas...")

    await msg.edit_text(f"⏳ *[███░░░░░░░] 30%* Extrayendo datos crudos de: {eq_local}")
    stats_local = await buscar_datos_equipo(eq_local)
    
    await msg.edit_text(f"⏳ *[██████░░░░] 60%* Extrayendo datos crudos de: {eq_visit}")
    stats_visit = await buscar_datos_equipo(eq_visit)

    await msg.edit_text(f"⏳ *[█████████░] 90%* Python ejecutando Poisson y gestionando motor analítico híbrido...")
    
    estadisticas = calcular_probabilidades(stats_local, stats_visit)
    corners_avg = round((stats_local['corners'] + stats_visit['corners']) / 2, 1)
    tarjetas_avg = round((stats_local['tarjetas'] + stats_visit['tarjetas']) / 2, 1)
    
    partido_id = guardar_prediccion(stats_local['name'], stats_visit['name'], estadisticas['prob_over_25'], estadisticas['prob_btts'])
    informe_scouting, motor_usado = await generar_informe_scouting_ia(estadisticas, stats_local, stats_visit, corners_avg, tarjetas_avg)
    
    texto_final = (
        f"🆔 *INFORME PREMIUM METRIC-BET: #{partido_id} ({VERSION_ACTUAL})*\n⚽ *{stats_local['name']} vs {stats_visit['name']}*\n"
        f"🔬 _L: {stats_local['fuente']} | V: {stats_visit['fuente']} | Motor IA: {motor_usado}_\n\n"
        f"📊 *PROYECCIONES MATEMÁTICAS CALCULADAS POR PYTHON:*\n"
        f"🔹 Goles Esperados (xG): `{estadisticas['xg_local']} - {estadisticas['xg_visitante']}`\n"
        f"📈 Probabilidad Over 2.5: `{estadisticas['prob_over_25']}%` | *Cuota Mínima:* `{estadisticas['cuota_over_minima']}`\n"
        f"🔥 Probabilidad Ambos Anotan: `{estadisticas['prob_btts']}%` | *Cuota Mínima:* `{estadisticas['cuota_btts_minima']}`\n"
        f"🚩 Córners Est.: `~{corners_avg}` | 🟨 Tarjetas Est.: `~{tarjetas_avg}`\n\n"
        f"🔬 *INFORME TÁCTICO DE SCOUTING ({motor_usado}):*\n\n{informe_scouting}\n\n"
        f"📥 Registrar cierre de evento con: `/resultado {partido_id} GolesLocal-GolesVisitante`"
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
            await message.reply(f"✅ Marcador guardado con éxito: `{goles_l}-{goles_v}`.", reply_markup=obtener_teclado_interactivo())
        else: 
            await message.reply("❌ El ID de predicción provisto no existe.", reply_markup=obtener_teclado_interactivo())
    except: 
        await message.reply("⚠️ Error de formato en el marcador. Usa un guion (Ej: 2-0).", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("equipo"))
async def consulting_equipo_solo(message: types.Message):
    nombre = re.sub(r'^/equipo(@\w+)?\s+', '', message.text).strip()
    if not nombre: 
        return await message.reply("⚠️ Indica el nombre del equipo. Ej: `/equipo Real Madrid`", reply_markup=obtener_teclado_interactivo())
    msg = await message.reply("🔍 Consultando registros crudos...")
    data = await buscar_datos_equipo(nombre)
    texto = f"📋 *MÉTRICAS CRUDAS ({VERSION_ACTUAL}):*\n\n⚽ *Equipo:* {data['name']}\n📈 Forma Reciente: `{data['forma']}`\n🧬 _Origen: {data['fuente']}_\n\n🔹 Goles Anotados/Partido: `{round(data['gf'], 2)}`\n🔸 Goles Recibidos/Partido: `{round(data['gc'], 2)}`"
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

if __name__ == "__main__": 
    main()
