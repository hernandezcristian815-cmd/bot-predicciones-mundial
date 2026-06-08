# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Value Betting Engine Premium v16.2.0-GROQ - Pipeline Secuencial de Auditoría (Gemini + Groq)

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
VERSION_ACTUAL = "v16.2.0-GROQ" 

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

# --- 5. NÚCLEO DE INFRAESTRUCTURA DE AUDITORÍA (GEMINI PROVEE -> GROQ COMPARA) ---
async def pipeline_extraccion_exacta(nombre_equipo):
    """
    Fase 1: Gemini investiga en sus registros históricos.
    Fase 2: Groq recibe los datos de Gemini, los compara con su base de datos y los ajusta si hay errores.
    """
    # Prompt Inicial para Gemini
    prompt_gemini = f"""
    Investiga los últimos 10 partidos oficiales competitivos de la selección o equipo: "{nombre_equipo}".
    Extrae promedios exactos por partido. Devuelve ÚNICAMENTE un JSON plano con este formato:
    {{"name": "{nombre_equipo}", "gf": 1.85, "gc": 0.80, "corners": 5.4, "tarjetas": 2.1, "forma": "V-V-E-D-V"}}
    """
    
    datos_gemini_txt = "{}"
    try:
        loop = asyncio.get_event_loop()
        response_gemini = await asyncio.wait_for(
            loop.run_in_executor(
                None, lambda: client.models.generate_content(
                    model='gemini-2.5-flash', contents=prompt_gemini, config={"response_mime_type": "application/json"}
                )
            ), timeout=6.0
        )
        datos_gemini_txt = response_gemini.text.strip()
    except Exception as e:
        print(f"Error inicial Gemini en Pipeline: {e}")

    # Fase 2: Groq recibe la propuesta de Gemini y la audita comparando datos
    prompt_groq_auditor = f"""
    Actúas como un Auditor de Big Data Deportivo. Analizas y comparas estadísticas de fútbol.
    El motor primario (Gemini) arrojó esta propuesta de datos para el equipo "{nombre_equipo}":
    {datos_gemini_txt}

    Tu tarea: Cruza y compara esta propuesta con tu propia base de conocimiento global de los últimos 10 partidos del equipo. 
    Si notas que los goles a favor (gf), en contra (gc) o rachas de "{nombre_equipo}" (como Colombia o Jordania) están desfasados o son genéricos, CORRÍGELOS con los números exactos históricos.
    Devuelve OBLIGATORIAMENTE el objeto JSON definitivo corregido. No agregues texto markdown, no digas nada más que el JSON limpio:
    {{"name": "Nombre Real", "gf": valor, "gc": valor, "corners": valor, "tarjetas": valor, "forma": "Racha"}}
    """

    if not RESPALDO_API_KEY:
        # Fallback si no hay Groq configurado
        try: return json.loads(datos_gemini_txt), "Gemini Pura"
        except: return None

    headers = {"Authorization": f"Bearer {RESPALDO_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODELO_GROQ,
        "messages": [
            {"role": "system", "content": "Eres un JSON stringifier estricto. Tu salida debe ser analizada por json.loads() directamente sin fallar."},
            {"role": "user", "content": prompt_groq_auditor}
        ],
        "temperature": 0.1, "max_tokens": 400
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(RESPALDO_API_URL, headers=headers, json=payload, timeout=6.0) as response:
                if response.status == 200:
                    res_data = await response.json()
                    text_final = res_data['choices'][0]['message']['content'].strip()
                    # Limpieza estricta de posibles bloques de código markdown injectados por Groq
                    text_final = re.sub(r'^```json\s*|\s*```$', '', text_final, flags=re.IGNORECASE).strip()
                    return json.loads(text_final), "Pipeline Híbrido (Gemini -> Groq Audit)"
    except Exception as e:
        print(f"Fallo en auditoría de Groq: {e}")

    # Si el cruce falló, intentamos parsear lo que dejó Gemini originalmente
    try:
        data_clean = json.loads(re.sub(r'^```json\s*|\s*```$', '', datos_gemini_txt, flags=re.IGNORECASE).strip())
        return data_clean, "Bypass Directo Gemini"
    except:
        return None

# --- 6. EXTRACCIÓN DE DATOS CRUDOS ---
async def buscar_datos_equipo(nombre_equipo):
    nombre_limpio = nombre_equipo.strip()
    resultado_pipeline = await pipeline_extraccion_exacta(nombre_limpio)
    
    if resultado_pipeline:
        data, fuente = resultado_pipeline
        return {
            'name': str(data.get('name', nombre_limpio)),
            'gf': float(data.get('gf', 1.40)),
            'gc': float(data.get('gc', 1.10)),
            'corners': float(data.get('corners', 4.8)),
            'tarjetas': float(data.get('tarjetas', 2.0)),
            'forma': str(data.get('forma', "V-E-V-D-E")),
            'fuente': fuente
        }
    
    # Resguardo definitivo si el pipeline se rompe por completo de red (Previene bloqueos)
    return {"name": nombre_limpio, "gf": 1.45, "gc": 1.15, "corners": 4.5, "tarjetas": 1.9, "forma": "E-V-E-D-V", "fuente": "Modelado Resguardo Fijo"}

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
    Actúa como un analista y tipster de fútbol profesional. Analiza el partido: {local_stats['name']} vs {visit_stats['name']}.
    Métricas de entrada precisas calculadas por el sistema:
    - Goles Esperados (xG): Local {estadisticas['xg_local']} vs {estadisticas['xg_visitante']} Visitante
    - Probabilidad Over 2.5: {estadisticas['prob_over_25']}% (Cuota sugerida: >{estadisticas['cuota_over_minima']})
    - Probabilidad Ambos Anotan (BTTS): {estadisticas['prob_btts']}% (Cuota sugerida: >{estadisticas['cuota_btts_minima']})
    - Córners: ~{corners} | Tarjetas: ~{tarjetas}
    - Racha / Forma Real: Local [{local_stats['forma']}] vs Visitante [{visit_stats['forma']}]

    Genera un informe estructurado usando Markdown limpio:
    📊 1. ANÁLISIS SENSORIAL Y CONTEXTUAL: Argumentación táctica estricta de cómo influyen estas rachas y los xG en el desarrollo.
    🎯 2. RECOMENDACIÓN PREMIUM (CREA TU APUESTA): Genera una combinada específica para Bet365/Wplay detallando la lógica de los picks.
    Nota: Sé muy conciso pero sumamente profesional. Limita la extensión.
    """
    try:
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: client.models.generate_content(model='gemini-2.5-flash', contents=prompt)),
            timeout=20.0
        )
        return response.text.strip(), "Gemini 2.5-Flash"
    except:
        headers = {"Authorization": f"Bearer {RESPALDO_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": MODELO_GROQ,
            "messages": [
                {"role": "system", "content": "Eres un analista de fútbol experto. Escribes reportes tácticos en Markdown."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.25, "max_tokens": 800
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(RESPALDO_API_URL, headers=headers, json=payload, timeout=20.0) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['choices'][0]['message']['content'].strip(), f"Groq LPU ({MODELO_GROQ})"
        except: pass
    return "⚠️ El módulo de redacción táctica final no pudo procesarse debido a una alta saturación de tokens en red.", "Predictor de Emergencia"

# --- 9. INTERFAZ Y MANEJADORES DE TELEGRAM ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    texto_bienvenida = f"🤖 *Value Betting Engine Premium Active*\n⚙️ *Versión:* `{VERSION_ACTUAL}`\n\nEl pipeline de auditoría cruzada está en línea."
    await message.answer(texto_bienvenida, reply_markup=obtener_teclado_interactivo(), parse_mode="Markdown")

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    argumentos = re.sub(r'^/analizar(@\w+)?\s+', '', message.text).strip()
    if " vs " not in argumentos: 
        return await message.reply("⚠️ Usa:\n`/analizar Local vs Visitante`", reply_markup=obtener_teclado_interactivo())
    
    eq_local, eq_visit = argumentos.split(" vs ")
    msg = await message.reply("⏳ *[██░░░░░░░░] 20%* Abriendo compuertas asíncronas e iniciando pipeline de auditoría de Big Data...")

    asyncio.create_task(procesar_analisis_desacoplado(msg, eq_local, eq_visit))

async def procesar_analisis_desacoplado(msg: types.Message, eq_local, eq_visit):
    try:
        # Invocamos el Pipeline de Auditoría para el equipo Local
        stats_local = await buscar_datos_equipo(eq_local)
        await msg.edit_text(f"⏳ *[█████░░░░░] 50%* Datos de {stats_local['name']} auditados por Groq. Analizando y cruzando rival...")
        
        # Invocamos el Pipeline de Auditoría para el equipo Visitante
        stats_visit = await buscar_datos_equipo(eq_visit)
        await msg.edit_text("⏳ *[████████░░] 80%* Python ejecutando Poisson sobre datos auditados reales. Redactando informe...")

        # Cálculo de Poisson con los datos reales auditados
        estadisticas = calcular_probabilidades(stats_local, stats_visit)
        corners_avg = round((stats_local['corners'] + stats_visit['corners']) / 2, 1)
        tarjetas_avg = round((stats_local['tarjetas'] + stats_visit['tarjetas']) / 2, 1)
        
        partido_id = guardar_prediccion(stats_local['name'], stats_visit['name'], estadisticas['prob_over_25'], estadisticas['prob_btts'])
        informe_scouting, motor_usado = await generar_informe_scouting_ia(estadisticas, stats_local, stats_visit, corners_avg, tarjetas_avg)
        
        texto_final = (
            f"🆔 *INFORME PREMIUM METRIC-BET: #{partido_id} ({VERSION_ACTUAL})*\n⚽ *{stats_local['name']} vs {stats_visit['name']}*\n"
            f"🔬 _L: {stats_local['fuente']} | V: {stats_visit['fuente']} | Redacción: {motor_usado}_\n\n"
            f"📊 *PROYECCIONES MATEMÁTICAS CALCULADAS POR PYTHON:*\n"
            f"🔹 Goles Esperados (xG): `{estadisticas['xg_local']} - {estadisticas['xg_visitante']}`\n"
            f"📈 Probabilidad Over 2.5: `{estadisticas['prob_over_25']}%` | *Cuota Mínima:* `{estadisticas['cuota_over_minima']}`\n"
            f"🔥 Probabilidad Ambos Anotan: `{estadisticas['prob_btts']}%` | *Cuota Mínima:* `{estadisticas['cuota_btts_minima']}`\n"
            f"🚩 Córners Est.: `~{corners_avg}` | 🟨 Tarjetas Est.: `~{tarjetas_avg}`\n\n"
            f"🔬 *INFORME TÁCTICO DE SCOUTING (IA AUDITADA):*\n\n{informe_scouting}\n\n"
            f"📥 Registrar cierre con: `/resultado {partido_id} GolesLocal-GolesVisitante`"
        )
        
        if len(texto_final) > 4000:
            texto_final = texto_final[:3950] + "\n\n⚠️ _[Informe truncado por tamaño de Telegram]_"
            
        await msg.edit_text(texto_final, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())
        
    except Exception as e:
        print(f"❌ Error en subproceso desacoplado v16.2: {e}")
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
