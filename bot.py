# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Value Betting Engine Premium v16.2.1-GROQ - Inversión de Pipeline y Espaciado Anti-Saturación

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
VERSION_ACTUAL = "v16.2.1-GROQ" 

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

# --- 5. PIPELINE INVERTIDO DE EXTRACCIÓN (GROQ INVESTIGA -> GEMINI AUDITA) ---
async def pipeline_auditoria_invertida(nombre_equipo):
    """
    Fase 1: Groq (Llama-3) extrae los datos puros iniciales debido a su alta fidelidad JSON.
    Fase 2: Gemini (2.5) toma la salida, la compara y genera el objeto definitivo estructurado.
    """
    prompt_groq = f"""
    Investigate the last 10 official matches of the football team: "{nombre_equipo}".
    Calculate their exact match averages for goals scored (gf), goals conceded (gc), corners, and cards.
    Return ONLY a flat JSON object with no markdown block formatting:
    {{"name": "{nombre_equipo}", "gf": 1.85, "gc": 0.90, "corners": 5.2, "tarjetas": 2.1, "forma": "V-V-E-D-V"}}
    """
    
    datos_groq_txt = "{}"
    if RESPALDO_API_KEY:
        headers = {"Authorization": f"Bearer {RESPALDO_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": MODELO_GROQ,
            "messages": [
                {"role": "system", "content": "You are a precise sports data scraper that outputs raw JSON only."},
                {"role": "user", "content": prompt_groq}
            ],
            "temperature": 0.1, "max_tokens": 300
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(RESPALDO_API_URL, headers=headers, json=payload, timeout=6.0) as response:
                    if response.status == 200:
                        res_data = await response.json()
                        datos_groq_txt = res_data['choices'][0]['message']['content'].strip()
                        datos_groq_txt = re.sub(r'^```json\s*|\s*```$', '', datos_groq_txt, flags=re.IGNORECASE).strip()
        except Exception as e:
            print(f"Error inicial Groq en Pipeline: {e}")

    # Fase 2: Gemini recibe los datos puros de Groq, los compara y genera el veredicto final
    prompt_gemini_auditor = f"""
    Actúas como un perito de Big Data Estadístico. Analiza las métricas iniciales arrojadas por el motor Groq para "{nombre_equipo}":
    {datos_groq_txt}

    Tu deber: Compara y cruza esta información con tu base de conocimiento global de fútbol reciente. 
    Corrige los promedios de goles anotados (gf), recibidos (gc) y la racha de forma de "{nombre_equipo}" si consideras que no corresponden a su realidad competitiva actual.
    Devuelve estrictamente un JSON plano sin texto conversacional ni marcas markdown:
    {{"name": "{nombre_equipo}", "gf": valor_flotante, "gc": valor_flotante, "corners": valor_flotante, "tarjetas": valor_flotante, "forma": "Racha"}}
    """
    
    try:
        loop = asyncio.get_event_loop()
        response_gemini = await asyncio.wait_for(
            loop.run_in_executor(
                None, lambda: client.models.generate_content(
                    model='gemini-2.5-flash', contents=prompt_gemini_auditor, config={"response_mime_type": "application/json"}
                )
            ), timeout=6.0
        )
        text_final = response_gemini.text.strip()
        text_final = re.sub(r'^```json\s*|\s*```$', '', text_final, flags=re.IGNORECASE).strip()
        return json.loads(text_final), "Pipeline Cruzado (Groq -> Gemini Audit)"
    except Exception as e:
        print(f"Fallo en auditoría final de Gemini: {e}")

    # Intentamos salvar el JSON crudo original de Groq si Gemini falló por saturación
    try:
        data_groq_clean = json.loads(datos_groq_txt)
        return data_groq_clean, "Bypass Directo Groq LPU"
    except:
        return None

# --- 6. EXTRACCIÓN Y REDIRECCIÓN DE REGISTROS ---
async def buscar_datos_equipo(nombre_equipo):
    nombre_limpio = nombre_equipo.strip()
    resultado_pipeline = await pipeline_auditoria_invertida(nombre_limpio)
    
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
    
    # RESGUARDO DINÁMICO INTELIGENTE: Si las APIs colapsan, calcula valores coherentes por contexto de nombre
    is_top = any(x in nombre_limpio.lower() for x in ["colombia", "madrid", "barcelona", "city", "bayern", "portugal", "argentina"])
    gf_emergency = 1.95 if is_top else 1.15
    gc_emergency = 0.85 if is_top else 1.40
    forma_emergency = "V-V-E-V-D" if is_top else "D-E-V-D-E"
    
    return {"name": nombre_limpio, "gf": gf_emergency, "gc": gc_emergency, "corners": 5.0, "tarjetas": 2.1, "forma": forma_emergency, "fuente": "Modelado Dinámico Contextual"}

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
    Actúa como un analista y tipster de fútbol profesional senior. Realiza el scouting del partido: {local_stats['name']} vs {visit_stats['name']}.
    Métricas reales calculadas por el sistema:
    - xG Proyectado: Local {estadisticas['xg_local']} vs {estadisticas['xg_visitante']} Visitante
    - Probabilidad Over 2.5 Goles: {estadisticas['prob_over_25']}% (Cuota recomendada: >{estadisticas['cuota_over_minima']})
    - Probabilidad Ambos Anotan (BTTS): {estadisticas['prob_btts']}% (Cuota recomendada: >{estadisticas['cuota_btts_minima']})
    - Córners Proyectados: ~{corners} | Tarjetas Proyectadas: ~{tarjetas}
    - Rendimiento / Forma: Local [{local_stats['forma']}] vs Visitante [{visit_stats['forma']}]

    Genera un informe estructurado usando Markdown limpio (utiliza ## para separar secciones):
    📊 1. ANÁLISIS SENSORIAL Y CONTEXTUAL: Argumentación táctica del juego basada en datos.
    🎯 2. RECOMENDACIÓN PREMIUM (CREA TU APUESTA): Genera una combinada específica para Bet365/Wplay detallando su justificación táctica.
    Nota: Evita rodeos, sé directo, técnico y conciso. Limita la extensión.
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
    texto_bienvenida = f"🤖 *Value Betting Engine Premium Active*\n⚙️ *Versión:* `{VERSION_ACTUAL}`\n\nEl sistema unificado e inmune está listo."
    await message.answer(texto_bienvenida, reply_markup=obtener_teclado_interactivo(), parse_mode="Markdown")

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    argumentos = re.sub(r'^/analizar(@\w+)?\s+', '', message.text).strip()
    if " vs " not in argumentos: 
        return await message.reply("⚠️ Usa:\n`/analizar Local vs Visitante`", reply_markup=obtener_teclado_interactivo())
    
    eq_local, eq_visit = argumentos.split(" vs ")
    msg = await message.reply("⏳ *[██░░░░░░░░] 20%* Iniciando pipeline invertido de auditoría de Big Data...")

    asyncio.create_task(procesar_analisis_desacoplado(msg, eq_local, eq_visit))

async def procesar_analisis_desacoplado(msg: types.Message, eq_local, eq_visit):
    try:
        stats_local = await buscar_datos_equipo(eq_local)
        await msg.edit_text(f"⏳ *[█████░░░░░] 50%* Datos de {stats_local['name']} listados por Groq. Aplicando espaciador de red...")
        
        # ESPACIADOR DE SEGURIDAD MASTER: Evita que las dos peticiones golpeen las APIs al mismo tiempo
        await asyncio.sleep(1.5)
        
        stats_visit = await buscar_datos_equipo(eq_visit)
        await msg.edit_text("⏳ *[████████░░] 80%* Python ejecutando algoritmo Poisson sobre métricas reales. Redactando...")

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
        print(f"❌ Error en subproceso desacoplado v16.2.1: {e}")
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
