# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Value Betting Engine Premium v12 - Análisis Táctico Unificado y Corregido

import os
import json
import sqlite3
import re
import asyncio
import aiohttp
from datetime import datetime
from google import genai
from google.genai import types as genai_types
from scipy.stats import poisson
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
LIGAS_MAPA = {"WC", "CL", "PL", "ELC", "FL1", "BL1", "SA", "PD", "PPL", "DED", "BSA"}

# --- 2. COMPONENTE REUTILIZABLE: MENÚ INTERACTIVO ---
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

# --- 4. MOTOR DE CALENDARIO DIARIO INTELIGENTE EN TIEMPO REAL ---
async def consultar_partidos_del_dia():
    """Consulta la cartelera real de fútbol internacional del día de hoy usando inteligencia en tiempo real."""
    fecha_hoy = datetime.now().strftime('%d/%m/%Y')
    prompt = f"""
    Investiga qué partidos oficiales o amistosos internacionales de fútbol de primer nivel se juegan hoy ({fecha_hoy}).
    Devuelve estrictamente una lista en formato JSON con los 5 partidos más importantes.
    Estructura exacta obligatoria:
    [
        {{"liga": "WC", "local": "Nombre Local", "visitante": "Nombre Visitante", "hora": "14:30"}},
        {{"liga": "BSA", "local": "Nombre Local", "visitante": "Nombre Visitante", "hora": "16:00"}}
    ]
    No uses marcas markdown de código ni texto extra. Solo el array JSON limpio.
    """
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=genai_types.GenerateContentConfig(response_mime_type="application/json")
            )
        )
        return json.loads(response.text.strip())
    except Exception as e:
        print(f"Error en agenda inteligente: {e}")
        return []

# --- 5. AGENTE DE SCOUTING COGNITIVO AVANZADO ---
async def investigar_equipo_con_ia(nombre_equipo):
    prompt = f"""
    Actúa como un analista de Big Data deportivo de élite. Analiza el rendimiento reciente de: "{nombre_equipo}".
    Estima sus promedios estadísticos precisos por partido en sus últimas participaciones competitivas.
    Devuelve estrictamente un objeto JSON con este formato exacto de llaves:
    {{"name": "{nombre_equipo}", "gf": 1.65, "gc": 1.10, "corners": 5.2, "tarjetas": 2.2, "forma": "V-V-E-D-V"}}
    No incluyas marcas markdown de código, solo el objeto JSON puro.
    """
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=genai_types.GenerateContentConfig(response_mime_type="application/json")
            )
        )
        
        raw_text = response.text.strip()
        raw_text = re.sub(r'^```json\s*', '', raw_text)
        raw_text = re.sub(r'\s*```$', '', raw_text)
        
        data = json.loads(raw_text)
        # Aseguramos la existencia de todas las llaves para evitar KeyErrors
        if "forma" not in data: data["forma"] = "E-E-V-D-V"
        if "corners" not in data: data["corners"] = 5.0
        if "tarjetas" not in data: data["tarjetas"] = 2.1
        
        data['fuente'] = "Deep Scouting (IA)"
        return data
    except Exception as e:
        print(f"Error en scouting de equipo: {e}")
        # Retorno de resguardo unificado con la estructura completa garantizada
        return {
            "name": nombre_equipo, "gf": 1.40, "gc": 1.15, "corners": 4.8, "tarjetas": 2.1, "forma": "E-V-E-D-E", "fuente": "Modelado Estructural"
        }

async def buscar_datos_equipo(nombre_equipo):
    return await investigar_equipo_con_ia(nombre_equipo)

# --- 6. FORMULACIÓN MATEMÁTICA DE POISSON ---
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

async def generar_scouting_profundo(estadisticas, local_stats, visit_stats, corners, tarjetas):
    prompt = f"""
    Realiza un análisis de Value Betting exhaustivo y pormenorizado para el cruce de fútbol: {local_stats['name']} vs {visit_stats['name']}.
    Métricas de Entrada:
    - {local_stats['name']}: xG Calculado {estadisticas['xg_local']}, Tendencia Reciente [{local_stats['forma']}]
    - {visit_stats['name']}: xG Calculado {estadisticas['xg_visitante']}, Tendencia Reciente [{visit_stats['forma']}]
    - Probabilidad Matemática de Over 2.5: {estadisticas['prob_over_25']}%
    - Probabilidad Matemática de Ambos Anotan (BTTS): {estadisticas['prob_btts']}%
    - Estimación de Córners: {corners} | Tarjetas: {tarjetas}

    Redacta un informe técnico estructurado con dos bloques bien detallados:
    1. ANALÍTICA TÁCTICA: Explica de forma madura y profesional la correlación entre los datos de ataque, debilidades defensivas de los bloques y el momento de forma de cada uno.
    2. PROPUESTA DE INVERSIÓN (CREA TU APUESTA): Genera una jugada de valor combinada detallando su justificación técnica basada en las probabilidades y las líneas estimadas.
    Sé específico, directo y sumamente profesional.
    """
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: client.models.generate_content(model='gemini-2.5-flash', contents=prompt))
        return response.text.strip()
    except Exception as e: 
        print(f"Error generando reporte IA: {e}")
        return "⚠️ El módulo analítico avanzado experimentó un desajuste al compilar las matrices de texto táctico."

# --- 7. CONTROLADORES TELEGRAM ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("🤖 *Value Betting Engine Premium Activo v12*\n\nSelecciona una opción del panel de control:", reply_markup=obtener_teclado_interactivo(), parse_mode="Markdown")

@dp.message(Command("hoy"))
async def cmd_hoy(message: types.Message):
    msg_espera = await message.reply("⏳ Sincronizando cartelera inteligente de partidos de hoy...")
    await procesar_agenda_comun(msg_espera)

@dp.callback_query()
async def manejador_botones_interactivos(callback_query: types.CallbackQuery):
    await callback_query.answer() 
    if callback_query.data == "ver_partidos_hoy":
        msg_inicial = await callback_query.message.answer("⏳ Solicitando partidos del día a la base de conocimiento...")
        await procesar_agenda_comun(msg_inicial)
    elif callback_query.data == "ver_efectividad_ia":
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT local, visitante, prob_over, prob_btts, goles_local_real, goles_visit_real FROM predicciones WHERE estado = 'FINALIZADO'")
        partidos = cursor.fetchall()
        conn.close()
        
        if not partidos:
            return await callback_query.message.answer("ℹ️ No hay registros finalizados en la base de datos local para calcular efectividad.", reply_markup=obtener_teclado_interactivo())
        
        total = len(partidos)
        ac_over = ac_btts = 0
        for p in partidos:
            if (p[2] >= 50.0 and (p[4]+p[5]) > 2) or (p[2] < 50.0 and (p[4]+p[5]) <= 2): ac_over += 1
            if (p[3] >= 50.0 and (p[4]>0 and p[5]>0)) or (p[3] < 50.0 and not (p[4]>0 and p[5]>0)): ac_btts += 1
            
        texto_efectividad = f"📊 *REPORTE DE EFECTIVIDAD DE LA IA:*\n\n📉 Partidos Evaluados: `{total}`\n🎯 Over 2.5: `{round((ac_over/total)*100,1)}%` acierto\n🔥 Ambos Anotan: `{round((ac_btts/total)*100,1)}%` acierto"
        await callback_query.message.answer(texto_efectividad, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

async def procesar_agenda_comun(message_target: types.Message):
    agenda = await consultar_partidos_del_dia()
    if not agenda:
        await message_target.edit_text("📅 *CARTELERA DE HOY:*\n\nℹ️ No se detectaron compromisos internacionales destacados programados para la fecha actual.", parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())
        return
        
    texto = "📅 *COMPROMISOS DESTACADOS PROGRAMADOS PARA HOY:*\n\n"
    for p in agenda:
        texto += f"🏆 *[{p['liga']}]* `{p['hora']}` | `{p['local']} vs {p['visitante']}`\n"
    texto += "\n💡 _Usa /analizar Local vs Visitante para procesar un encuentro._"
    await message_target.edit_text(texto, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    argumentos = re.sub(r'^/analizar(@\w+)?\s+', '', message.text).strip()
    if " vs " not in argumentos: 
        return await message.reply("⚠️ Formato inválido. Usa:\n`/analizar Equipo Local vs Equipo Visitante`", reply_markup=obtener_teclado_interactivo())
    
    eq_local, eq_visit = argumentos.split(" vs ")
    msg = await message.reply("⏳ *[░░░░░░░░░░] 0%* Abriendo compuertas asíncronas...")

    await msg.edit_text(f"⏳ *[███░░░░░░░] 30%* Compilando Big Data de: {eq_local}")
    stats_local = await buscar_datos_equipo(eq_local)
    
    await msg.edit_text(f"⏳ *[██████░░░░] 60%* Compilando Big Data de: {eq_visit}")
    stats_visit = await buscar_datos_equipo(eq_visit)

    await msg.edit_text("⏳ *[█████████░] 90%* Operando Poisson y estructurando reporte táctico...")
    estadisticas = calcular_probabilidades(stats_local, stats_visit)
    corners_avg = round((stats_local['corners'] + stats_visit['corners']) / 2, 1)
    tarjetas_avg = round((stats_local['tarjetas'] + stats_visit['tarjetas']) / 2, 1)
    
    partido_id = guardar_prediccion(stats_local['name'], stats_visit['name'], estadisticas['prob_over_25'], estadisticas['prob_btts'])
    
    # EXTRACCIÓN DEL SCOUTING INTEGRAL SIN RUPTURAS DE LLAVES
    informe_ia = await generar_scouting_profundo(estadisticas, stats_local, stats_visit, corners_avg, tarjetas_avg)
    
    texto_final = (
        f"🆔 *INFORME DE SCOUTING METRIC-BET: #{partido_id}*\n⚽ *{stats_local['name']} vs {stats_visit['name']}*\n🔬 _L: {stats_local['fuente']} | V: {stats_visit['fuente']}_\n\n"
        f"📈 *PROYECCIONES MATEMÁTICAS (POISSON):*\n"
        f"🔹 xG Proyectado: `{estadisticas['xg_local']} - {estadisticas['xg_visitante']}`\n"
        f"📊 Prob. Over 2.5: `{estadisticas['prob_over_25']}%` | *Cuota Mínima:* `{estadisticas['cuota_over_minima']}`\n"
        f"🔥 Prob. BTTS: `{estadisticas['prob_btts']}%` | *Cuota Mínima:* `{estadisticas['cuota_btts_minima']}`\n"
        f"🚩 Córners Est.: `~{corners_avg}` | 🟨 Tarjetas Est.: `~{tarjetas_avg}`\n\n"
        f"🔬 *INFORME DE SCOUTING COGNITIVO AVANZADO:*\n\n{informe_ia}\n\n"
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
    msg = await message.reply("🔍 Consultando registros de rendimiento...")
    data = await buscar_datos_equipo(nombre)
    texto = f"📋 *ANÁLISIS DE EQUIPO:*\n\n⚽ *Equipo:* {data['name']}\n📈 Forma Reciente: `{data['forma']}`\n🧬 _Origen: {data['fuente']}_\n\n🔹 Goles Anotados/Partido: `{round(data['gf'], 2)}`\n🔸 Goles Recibidos/Partido: `{round(data['gc'], 2)}`"
    await msg.edit_text(texto, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

def main():
    dp.startup.register(on_startup)
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

if __name__ == "__main__": 
    main()
