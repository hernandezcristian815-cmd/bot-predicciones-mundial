# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Value Betting Engine Premium v16.1.3-GROQ (Uptime & Timeout Fixed)

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
VERSION_ACTUAL = "v16.1.3-GROQ" 

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_KEY")
FOOTBALL_DATA_KEY = os.getenv("API_FOOTBALL_KEY") 
API_SPORTS_KEY = os.getenv("API_SPORTS_KEY")       

RESPALDO_API_KEY = os.getenv("RESPALDO_API_KEY") 
RESPALDO_API_URL = os.getenv("RESPALDO_API_URL", "https://api.groq.com/openai/v1/chat/completions")
MODELO_GROQ = "llama3-70b-8192"  

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
        types.InlineKeyboardButton(text=f"⚙️ Engine: {VERSION_ACTUAL}", callback_data="info_version")
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
            async with session.get(url_matches, headers=headers, timeout=2.0) as response:
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
                async with session.get(url_as, headers=headers_as, params={"date": fecha_hoy}, timeout=2.0) as res:
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

# --- 5. PASARELA DE RESPALDO: GROQ LPU ---
async def consultar_ia_respaldo(prompt):
    if not RESPALDO_API_KEY:
        return "⚠️ Error de Cuota: Gemini se saturó y no se detectó la clave de Groq."
        
    headers = {
        "Authorization": f"Bearer {RESPALDO_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODELO_GROQ,
        "messages": [
            {"role": "system", "content": "Eres un Tipster Analítico Profesional. Generas informes técnicos de fútbol usando Markdown limpio."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.25,
        "max_tokens": 1200
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(RESPALDO_API_URL, headers=headers, json=payload, timeout=8.0) as response:
                if response.status == 200:
                    res_data = await response.json()
                    return res_data['choices'][0]['message']['content'].strip() + "\n\n⚡ _(Análisis de respaldo por Groq LPU)_"
                else:
                    return "❌ Cuota excedida temporalmente en pasarelas de lenguaje artificial."
    except:
        return "❌ Error de conexión temporal con las pasarelas cognitivas."

# --- 6. NÚCLEO ARQUITECTÓNICO HÍBRIDO ---
async def ejecutar_sistema_cognitivo(prompt, es_json=False):
    try:
        loop = asyncio.get_event_loop()
        config_dict = {"response_mime_type": "application/json"} if es_json else None
        
        response = await loop.run_in_executor(
            None, 
            lambda: client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=config_dict
            )
        )
        return response.text.strip(), "Gemini-2.5"
    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
            if es_json:
                prompt += " Responde estrictamente un JSON plano, sin sintaxis ni marcas de bloques markdown."
            resultado_groq = await consultar_ia_respaldo(prompt)
            return resultado_groq, "Groq LPU"
        else:
            raise e

# --- 7. EXTRACCIÓN COGNITIVA Y OPTIMIZACIÓN DE TIMEOUTS ---
async def obtener_datos_crudos_ia(nombre_equipo):
    prompt = f"""
    Proporciona los datos estadísticos crudos del equipo: "{nombre_equipo}" en sus últimos 10 juegos.
    Devuelve estrictamente un objeto JSON:
    {{"name": "{nombre_equipo}", "gf": 1.50, "gc": 1.10, "corners": 5.0, "tarjetas": 2.0, "forma": "V-E-V-D-V"}}
    """
    try:
        raw_text, fuente = await ejecutar_sistema_cognitivo(prompt, es_json=True)
        raw_text = re.sub(r'^```json\s*', '', raw_text)
        raw_text = re.sub(r'\s*```$', '', raw_text)
        data = json.loads(raw_text)
        data['fuente'] = fuente
        return data
    except:
        return {"name": nombre_equipo, "gf": 1.30, "gc": 1.20, "corners": 4.5, "tarjetas": 2.0, "forma": "E-V-D-E-E", "fuente": "Resguardo Matemático"}

async def buscar_datos_equipo(nombre_equipo):
    nombre_limpio = nombre_equipo.strip()
    
    async with aiohttp.ClientSession() as session:
        headers_fd = {"X-Auth-Token": FOOTBALL_DATA_KEY}
        # Reducción drástica del timeout a 0.8s para evitar cuelgues en Telegram
        for liga in ["WC", "PL", "PD"]:
            url_fd = f"https://api.football-data.org/v4/competitions/{liga}/standings"
            try:
                async with session.get(url_fd, headers=headers_fd, timeout=0.8) as res:
                    if res.status == 200:
                        data = await res.json()
                        tabla = next((t for t in data.get('standings', []) if t['type'] == 'TOTAL'), None)
                        if tabla:
                            for row in tabla['table']:
                                name_oficial = row['team']['name']
                                if nombre_limpio.lower() in name_oficial.lower() or name_oficial.lower() in nombre_limpio.lower():
                                    partidos = max(1, row['playedGames'])
                                    return {
                                        'name': name_oficial, 'gf': row['goalsFor'] / partidos, 'gc': row['goalsAgainst'] / partidos, 
                                        'corners': 5.0, 'tarjetas': 2.0, 'forma': "Data Activa", 'fuente': f"Football-Data ({liga})"
                                    }
            except: pass

    return await obtener_datos_crudos_ia(nombre_limpio)

# --- 8. PROCESAMIENTO MATEMÁTICO PURO (POISSON) ---
def calcular_probabilidades(local_stats, visit_stats):
    promedio_goles = 1.25
    xg_local = max(0.15, (local_stats["gf"] / promedio_goles) * (visit_stats["gc"] / promedio_goles) * promedio_goles)
    xg_visit = max(0.15, (visit_stats["gf"] / promedio_goles) * (local_stats["gc"] / promedio_goles) * promedio_goles)

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
    Analiza el partido: {local_stats['name']} vs {visit_stats['name']}.
    Datos calculados:
    - xG: Local {estadisticas['xg_local']} vs {estadisticas['xg_visitante']} Visitante
    - Probabilidad Over 2.5: {estadisticas['prob_over_25']}% (Cuota sugerida: >{estadisticas['cuota_over_minima']})
    - Probabilidad BTTS: {estadisticas['prob_btts']}% (Cuota sugerida: >{estadisticas['cuota_btts_minima']})
    - Córners Totales: ~{corners} | Tarjetas Totales: ~{tarjetas}

    Genera un informe usando formato Markdown estructurado con estas dos secciones:
    📊 1. ANÁLISIS SENSORIAL Y CONTEXTUAL: Argumentación táctica del juego basada en datos.
    🎯 2. RECOMENDACIÓN PREMIUM (CREA TU APUESTA): Una apuesta combinada lógica para Bet365/Wplay.
    """
    informe, fuente_motor = await ejecutar_sistema_cognitivo(prompt, es_json=False)
    return informe, fuente_motor

# --- 10. INTERFAZ Y MANEJADORES DE TELEGRAM ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    texto_bienvenida = f"🤖 *Value Betting Engine Premium Active*\n⚙️ *Versión:* `{VERSION_ACTUAL}`\n\nEl sistema unificado está listo."
    await message.answer(texto_bienvenida, reply_markup=obtener_teclado_interactivo(), parse_mode="Markdown")

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    argumentos = re.sub(r'^/analizar(@\w+)?\s+', '', message.text).strip()
    if " vs " not in argumentos: 
        return await message.reply("⚠️ Usa:\n`/analizar Local vs Visitante`", reply_markup=obtener_teclado_interactivo())
    
    eq_local, eq_visit = argumentos.split(" vs ")
    msg = await message.reply("⏳ *Procesando solicitud en los servidores alternos...*")

    stats_local = await buscar_datos_equipo(eq_local)
    stats_visit = await buscar_datos_equipo(eq_visit)

    estadisticas = calcular_probabilidades(stats_local, stats_visit)
    corners_avg = round((stats_local['corners'] + stats_visit['corners']) / 2, 1)
    tarjetas_avg = round((stats_local['tarjetas'] + stats_visit['tarjetas']) / 2, 1)
    
    partido_id = guardar_prediccion(stats_local['name'], stats_visit['name'], estadisticas['prob_over_25'], estadisticas['prob_btts'])
    informe_scouting, motor_usado = await generar_informe_scouting_ia(estadisticas, stats_local, stats_visit, corners_avg, tarjetas_avg)
    
    texto_final = (
        f"🆔 *INFORME PREMIUM METRIC-BET: #{partido_id} ({VERSION_ACTUAL})*\n⚽ *{stats_local['name']} vs {stats_visit['name']}*\n"
        f"🔬 _Motor IA: {motor_usado}_\n\n"
        f"📊 *PROYECCIONES MATEMÁTICAS (PYTHON):*\n"
        f"🔹 Goles Esperados (xG): `{estadisticas['xg_local']} - {estadisticas['xg_visitante']}`\n"
        f"📈 Probabilidad Over 2.5: `{estadisticas['prob_over_25']}%` | *Cuota:* `{estadisticas['cuota_over_minima']}`\n"
        f"🔥 Probabilidad Ambos Anotan: `{estadisticas['prob_btts']}%` | *Cuota:* `{estadisticas['cuota_btts_minima']}`\n"
        f"🚩 Córners: `~{corners_avg}` | 🟨 Tarjetas: `~{tarjetas_avg}`\n\n"
        f"🔬 *INFORME TÁCTICO DE SCOUTING:*\n\n{informe_scouting}\n\n"
        f"📥 Registrar cierre con: `/resultado {partido_id} GolesLocal-GolesVisitante`"
    )
    await msg.edit_text(texto_final, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("resultado"))
async def registrar_resultado(message: types.Message):
    argumentos = message.text.replace("/resultado", "").strip().split()
    if len(argumentos) != 2: return await message.reply("⚠️ Usa: `/resultado ID Marcador` (Ej: `/resultado 1 2-1`)")
    prediccion_id, marcador = argumentos
    try:
        goles_l, goles_v = map(int, marcador.split("-"))
        if registrar_resultado_db(prediccion_id, goles_l, goles_v):
            await message.reply(f"✅ Marcador guardado: `{goles_l}-{goles_v}`.")
        else: 
            await message.reply("❌ ID inexistente.")
    except: 
        await message.reply("⚠️ Error de formato.")

# --- 11. MANEJADOR DE SALUD PARA UPTIMEROBOT (HEALTCHECK RATIO) ---
async def handles_ping_alive(request):
    """Ruta Raíz HTTP GET que responde a UptimeRobot para mantener la app activa 24/7"""
    return web.json_response({"status": "online", "version": VERSION_ACTUAL, "engine": "stable"})

async def on_startup(bot: Bot): 
    inicializar_db()
    await bot.set_webhook(WEBHOOK_URL)

def main():
    dp.startup.register(on_startup)
    app = web.Application()
    
    # NUEVO: Vinculamos la ruta raíz '/' para responder los pings de monitoreo
    app.router.add_get("/", handles_ping_alive)
    
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

if __name__ == "__main__": 
    main()
