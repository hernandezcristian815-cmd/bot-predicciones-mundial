# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Value Betting Engine Premium v16.1.9-GROQ - Diagnóstico de Logs e Inteligencia Inmune

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
VERSION_ACTUAL = "v16.1.9-GROQ" 

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
                    for m in data.get("matches", []):
                        cod_liga = m.get("competition", {}).get("code")
                        if cod_liga in LIGAS_MAPA:
                            partidos_detectados.append({
                                "liga": cod_liga, "local": m["homeTeam"]["name"],
                                "visitante": m["awayTeam"]["name"], "hora": m["utcDate"][11:16]
                            })
    except: pass
    return partidos_detectados

# --- 5. PASARELAS ASÍNCRONAS PARA EXTRACCIÓN NUMÉRICA ---
async def consultar_groq_crudo(prompt):
    if not RESPALDO_API_KEY: return None
    headers = {"Authorization": f"Bearer {RESPALDO_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama3-8b-8192", # Cambiado temporalmente a 8b para asegurar límites más amplios
        "messages": [
            {"role": "system", "content": "Return code only JSON string. No text markdown."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1, "max_tokens": 300
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(RESPALDO_API_URL, headers=headers, json=payload, timeout=5.0) as response:
                if response.status == 200:
                    data = await response.json()
                    text = data['choices'][0]['message']['content'].strip()
                    text = re.sub(r'^```json\s*|\s*```$', '', text, flags=re.IGNORECASE).strip()
                    return json.loads(text)
    except: pass
    return None

async def consultar_gemini_crudo(prompt):
    try:
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None, lambda: client.models.generate_content(
                    model='gemini-2.5-flash', contents=prompt, config={"response_mime_type": "application/json"}
                )
            ), timeout=5.0
        )
        text = response.text.strip()
        text = re.sub(r'^```json\s*|\s*```$', '', text, flags=re.IGNORECASE).strip()
        return json.loads(text)
    except: pass
    return None

# --- 6. LÓGICA COGNITIVA MULTI-ENGINE ---
async def obtener_datos_crudos_ia(nombre_equipo):
    prompt = f"""
    Provide statistical averages for the last 10 games of: "{nombre_equipo}".
    Return strictly JSON:
    {{"name": "{nombre_equipo}", "gf": 1.55, "gc": 0.95, "corners": 5.1, "tarjetas": 2.0, "forma": "V-V-E-D-V"}}
    """
    try:
        res_gemini, res_groq = await asyncio.gather(
            consultar_gemini_crudo(prompt),
            consultar_groq_crudo(prompt)
        )
    except:
        res_gemini, res_groq = None, None

    if res_gemini and res_groq:
        return {
            'name': res_gemini.get('name', nombre_equipo),
            'gf': (float(res_gemini.get('gf', 1.30)) + float(res_groq.get('gf', 1.30))) / 2,
            'gc': (float(res_gemini.get('gc', 1.20)) + float(res_groq.get('gc', 1.20))) / 2,
            'corners': (float(res_gemini.get('corners', 4.5)) + float(res_groq.get('corners', 4.5))) / 2,
            'tarjetas': (float(res_gemini.get('tarjetas', 2.0)) + float(res_groq.get('tarjetas', 2.0))) / 2,
            'forma': res_gemini.get('forma', "E-V-D-E-E"),
            'fuente': "Consenso Real (Gemini + Groq)"
        }
    
    single_res = res_gemini or res_groq
    if single_res:
        return {
            'name': single_res.get('name', nombre_equipo),
            'gf': float(single_res.get('gf', 1.30)),
            'gc': float(single_res.get('gc', 1.20)),
            'corners': float(single_res.get('corners', 4.5)),
            'tarjetas': float(single_res.get('tarjetas', 2.0)),
            'forma': single_res.get('forma', "E-V-D-E-E"),
            'fuente': "Single AI Scan Core"
        }

    return {"name": nombre_equipo, "gf": 1.40, "gc": 1.10, "corners": 4.8, "tarjetas": 1.9, "forma": "V-E-D-V-E", "fuente": "Modelado Resguardo Fijo"}

# --- 7. PROCESAMIENTO MATEMÁTICO PURO (POISSON) ---
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

# --- 8. REDACCIÓN COGNITIVA DEL SCOUTING ---
async def generar_informe_scouting_ia(estadisticas, local_stats, visit_stats, corners, tarjetas):
    prompt = f"""
    Actúa como un Tipster Analítico de Fútbol. Analiza el partido: {local_stats['name']} vs {visit_stats['name']}.
    Métricas reales calculadas por Python:
    - xG Proyectado: Local {estadisticas['xg_local']} vs {estadisticas['xg_visitante']} Visitante
    - Probabilidad Over 2.5 Goles: {estadisticas['prob_over_25']}% (Cuota justa: >{estadisticas['cuota_over_minima']})
    - Probabilidad Ambos Anotan (BTTS): {estadisticas['prob_btts']}% (Cuota justa: >{estadisticas['cuota_btts_minima']})
    - Córners Proyectados: ~{corners} | Tarjetas Proyectadas: ~{tarjetas}
    - Rendimiento / Forma: Local [{local_stats['forma']}] vs Visitante [{visit_stats['forma']}]

    Genera un informe estructurado usando Markdown limpio:
    📊 1. ANÁLISIS SENSORIAL Y CONTEXTUAL: Argumentación técnica del juego basada en datos.
    🎯 2. RECOMENDACIÓN PREMIUM (CREA TU APUESTA): Genera una combinada específica para Bet365/Wplay detallando su justificación táctica.
    Nota: Evita introducciones largas, sé directo, técnico y conciso.
    """
    
    # Intento 1: Intento primario con Gemini
    try:
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: client.models.generate_content(model='gemini-2.5-flash', contents=prompt)),
            timeout=20.0
        )
        return response.text.strip(), "Gemini 2.5-Flash"
    except Exception as gem_err:
        # LOGS DE AUDITORÍA: Pintamos el error de Gemini en la pantalla de Render
        print(f"⚠️ LOG INFRAESTRUCTURA - Falló Gemini: {gem_err}")

    # Intento 2: Salto inmediato a Groq LPU si Gemini da 429 o error
    if RESPALDO_API_KEY:
        headers = {"Authorization": f"Bearer {RESPALDO_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": MODELO_GROQ,
            "messages": [
                {"role": "system", "content": "Eres un Tipster Analítico de Élite. Ecribes reportes serios de fútbol en Markdown."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.25, "max_tokens": 1000
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(RESPALDO_API_URL, headers=headers, json=payload, timeout=20.0) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['choices'][0]['message']['content'].strip(), f"Groq LPU ({MODELO_GROQ})"
                    else:
                        print(f"⚠️ LOG INFRAESTRUCTURA - Falló Groq Status: {response.status}")
        except Exception as groq_err:
            print(f"⚠️ LOG INFRAESTRUCTURA - Falló Groq Exception: {groq_err}")

    # Cierre de pánico matemático si ambas cayeron
    return "⚠️ El módulo analítico de texto no pudo completarse debido a una saturación en las pasarelas externas. Monitoree las API Keys en Render.", "Predictor de Emergencia"

# --- 9. INTERFAZ Y MANEJADORES DE TELEGRAM ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    texto_bienvenida = f"🤖 *Value Betting Engine Premium Active*\n⚙️ *Versión:* `{VERSION_ACTUAL}`\n\nEl sistema desacoplado está listo para auditorías."
    await message.answer(texto_bienvenida, reply_markup=obtener_teclado_interactivo(), parse_mode="Markdown")

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    argumentos = re.sub(r'^/analizar(@\w+)?\s+', '', message.text).strip()
    if " vs " not in argumentos: 
        return await message.reply("⚠️ Usa:\n`/analizar Local vs Visitante`", reply_markup=obtener_teclado_interactivo())
    
    eq_local, eq_visit = argumentos.split(" vs ")
    msg = await message.reply("⏳ *[██░░░░░░░░] 20%* Abriendo compuertas asíncronas y consultando promedios por consenso...")

    asyncio.create_task(procesar_analisis_desacoplado(msg, eq_local, eq_visit))

async def procesar_analisis_desacoplado(msg: types.Message, eq_local, eq_visit):
    try:
        stats_local = await obtener_datos_crudos_ia(eq_local)
        await msg.edit_text(f"⏳ *[█████░░░░░] 50%* Datos de {stats_local['name']} listados. Computando rival...")
        
        stats_visit = await obtener_datos_crudos_ia(eq_visit)
        await msg.edit_text("⏳ *[████████░░] 80%* Python ejecutando algoritmo Poisson. Redactando scouting cognitivo profundo por consenso...")

        # Algoritmo de Poisson
        estadisticas = calcular_probabilidades(stats_local, stats_visit)
        corners_avg = round((stats_local['corners'] + stats_visit['corners']) / 2, 1)
        tarjetas_avg = round((stats_local['tarjetas'] + stats_visit['tarjetas']) / 2, 1)
        
        partido_id = guardar_prediccion(stats_local['name'], stats_visit['name'], estadisticas['prob_over_25'], estadisticas['prob_btts'])
        
        # Generación del informe táctico
        informe_scouting, motor_usado = await generar_informe_scouting_ia(estadisticas, stats_local, stats_visit, corners_avg, tarjetas_avg)
        
        texto_final = (
            f"🆔 *INFORME PREMIUM METRIC-BET: #{partido_id} ({VERSION_ACTUAL})*\n⚽ *{stats_local['name']} vs {stats_visit['name']}*\n"
            f"🔬 _L: {stats_local['fuente']} | V: {stats_visit['fuente']} | Redacción: {motor_usado}_\n\n"
            f"📊 *PROYECCIONES MATEMÁTICAS (PYTHON):*\n"
            f"🔹 Goles Esperados (xG): `{estadisticas['xg_local']} - {estadisticas['xg_visitante']}`\n"
            f"📈 Probabilidad Over 2.5: `{estadisticas['prob_over_25']}%` | *Cuota:* `{estadisticas['cuota_over_minima']}`\n"
            f"🔥 Probabilidad Ambos Anotan: `{estadisticas['prob_btts']}%` | *Cuota:* `{estadisticas['cuota_btts_minima']}`\n"
            f"🚩 Córners: `~{corners_avg}` | 🟨 Tarjetas: `~{tarjetas_avg}`\n\n"
            f"🔬 *INFORME TÁCTICO DE SCOUTING SERIO Y DETALLADO:*\n\n{informe_scouting}\n\n"
            f"📥 Registrar cierre con: `/resultado {partido_id} GolesLocal-GolesVisitante`"
        )
        
        if len(texto_final) > 4000:
            texto_final = texto_final[:3950] + "\n\n⚠️ _[Informe truncado por tamaño máximo de Telegram]_"
            
        await msg.edit_text(texto_final, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())
        
    except Exception as e:
        print(f"❌ ERROR CRÍTICO EN PROCESAMIENTO HILO: {e}")
        await msg.edit_text("❌ Ocurrió un desajuste imprevisto en los subprocesos de cómputo del servidor.", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("resultado"))
async def registrar_resultado(message: types.Message):
    argumentos = message.text.replace("/resultado", "").strip().split()
    if len(argumentos) != 2: 
        return await message.reply("⚠️ Usa: `/resultado ID Marcador` (Ej: `/resultado 1 2-1`)")
    prediccion_id, marcador = argumentos
    try:
        goles_l, goles_v = map(int, marcador.split("-"))
        if registrar_resultado_db(prediccion_id, goles_l, goles_v):
            await message.reply(f"✅ Marcador guardado: `{goles_l}-{goles_v}`.")
        else: 
            await message.reply("❌ ID inexistente.")
    except: 
        await message.reply("⚠️ Error de formato en el marcador.")

async def handles_ping_alive(request):
    return web.json_response({"status": "online", "version": VERSION_ACTUAL})

async def on_startup(bot: Bot): 
    inicializar_db()
    await bot.set_webhook(WEBHOOK_URL)

def main():
    dp.startup.register(on_startup)
    app = web.Application()
    app.router.add_get("/", handles_ping_alive)
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

if __name__ == "__main__": 
    main()
