# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Value Betting Engine Premium v9 - Migración Completa a Aiohttp (Asincronía Real)

import os
import json
import sqlite3
import re
import asyncio
import aiohttp
import numpy as np
from scipy.stats import poisson
from datetime import datetime
from google import genai
from google.genai import types as genai_types
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
CUOTAS_MONITOR = {"football_data": "Disponible", "api_sports": "Disponible", "gemini": 15}

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

# --- 4. CONSULTA ASÍNCRONA DE AGENDA ---
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
    except Exception as e:
        print(f"Error asíncrono en agenda: {e}")
    return partidos_detectados

# --- 5. AGENTE COGNITIVO IA ASÍNCRONO ---
async def investigar_equipo_con_ia(nombre_equipo):
    prompt = f"Investiga el rendimiento de: {nombre_equipo}. Devuelve estrictamente este JSON: {{\"name\": \"{nombre_equipo}\", \"gf\": 1.45, \"gc\": 1.15, \"corners\": 4.8, \"tarjetas\": 2.2, \"informacion_historica\": true}}"
    try:
        # Correr la llamada síncrona de Gemini en un hilo separado para no bloquear el bucle asíncrono
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=genai_types.GenerateContentConfig(response_mime_type="application/json")
            )
        )
        data = json.loads(response.text.strip())
        data['fuente'] = "Tendencia Histórica (Gemini IA)"
        return data
    except: 
        return None

# --- 6. EXTRACTOR EN CASCADA 100% ASÍNCRONO (LAS 3 APIS TRABAJANDO) ---
async def buscar_datos_equipo(nombre_equipo):
    nombre_limpio = nombre_equipo.strip()
    
    async with aiohttp.ClientSession() as session:
        # --- API 1: Football-Data ---
        headers_fd = {"X-Auth-Token": FOOTBALL_DATA_KEY}
        for liga in ["WC", "PL", "PD", "BSA"]:
            url_fd = f"https://api.football-data.org/v4/competitions/{liga}/standings"
            try:
                async with session.get(url_fd, headers=headers_fd, timeout=2.0) as res:
                    if res.status == 200:
                        data = await res.json()
                        tabla = next((t for t in data.get('standings', []) if t['type'] == 'TOTAL'), None)
                        if tabla:
                            for row in tabla['table']:
                                if nombre_limpio.lower() in row['team']['name'].lower() or row['team']['name'].lower() in nombre_limpio.lower():
                                    partidos = row['playedGames'] if row['playedGames'] > 0 else 1
                                    return {
                                        'name': row['team']['name'], 'gf': row['goalsFor'] / partidos, 'gc': row['goalsAgainst'] / partidos, 
                                        'corners': 5.0, 'tarjetas': 2.0, 'fuente': f"Football-Data ({liga})"
                                    }
            except:
                pass

        # --- API 2: API-Sports ---
        url_as = "https://v3.football.api-sports.io/teams"
        headers_as = {"x-apisports-key": API_SPORTS_KEY}
        try:
            async with session.get(url_as, headers=headers_as, params={"search": nombre_limpio}, timeout=2.5) as res_search:
                if res_search.status == 200:
                    search_data = await res_search.json()
                    teams = search_data.get("response", [])
                    if teams:
                        team_id = teams[0]["team"]["id"]
                        nombre_oficial = teams[0]["team"]["name"]
                        url_fix = f"https://v3.football.api-sports.io/fixtures?team={team_id}&last=5"
                        
                        async with session.get(url_fix, headers=headers_as, timeout=2.5) as res_fix:
                            if res_fix.status == 200:
                                fix_data = await res_fix.json()
                                fixtures = fix_data.get("response", [])
                                if fixtures:
                                    g_favor = sum([(f['goals']['home'] if f['teams']['home']['id'] == team_id else f['goals']['away']) for f in fixtures if f['goals']['home'] is not None])
                                    g_contra = sum([(f['goals']['away'] if f['teams']['home']['id'] == team_id else f['goals']['home']) for f in fixtures if f['goals']['home'] is not None])
                                    partidos = len(fixtures) if len(fixtures) > 0 else 1
                                    return {
                                        'name': nombre_oficial, 'gf': g_favor / partidos, 'gc': g_contra / partidos, 
                                        'corners': 4.8, 'tarjetas': 2.4, 'fuente': "Historial API-Sports"
                                    }
        except:
            pass

    # --- API 3: Respaldo de Gemini IA ---
    return await investigar_equipo_con_ia(nombre_limpio)

# --- 7. POISSON Y ANÁLISIS ---
def calcular_probabilidades(local_stats, visit_stats):
    promedio_goles = 1.25
    xg_local = (local_stats["gf"] / promedio_goles) * (visit_stats["gc"] / promedio_goles) * promedio_goles
    xg_visit = (visit_stats["gf"] / promedio_goles) * (local_stats["gc"] / promedio_goles) * promedio_goles

    prob_local = [poisson.pmf(i, xg_local) for i in range(6)]
    prob_visit = [poisson.pmf(i, xg_visit) for i in range(6)]
    
    prob_under_25 = sum([prob_local[i] * prob_visit[j] for i in range(6) for j in range(6) if i+j < 3])
    p_over = round((1 - prob_under_25) * 100, 2)
    p_btts = round(((1 - prob_local[0]) * (1 - prob_visit[0])) * 100, 2)
    
    return {
        "xg_local": round(xg_local, 2), "xg_visitante": round(xg_visit, 2), "prob_over_25": p_over, "prob_btts": p_btts,
        "cuota_over_minima": round(100 / (p_over if p_over > 0 else 1) * 1.05, 2), "cuota_btts_minima": round(100 / (p_btts if p_btts > 0 else 1) * 1.05, 2)
    }

async def consultar_gemini_analisis(estadisticas, local, visitante, corners, tarjetas):
    prompt = f"Analiza: {local} vs {visitante} | xG: {estadisticas['xg_local']}-{estadisticas['xg_visitante']} | Over 2.5: {estadisticas['prob_over_25']}% | BTTS: {estadisticas['prob_btts']}%. Da una recomendación corta para 'Crea tu apuesta' con córners promedio ({corners}) y tarjetas ({tarjetas}) en 2 líneas."
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: client.models.generate_content(model='gemini-2.5-flash', contents=prompt))
        return response.text.strip()
    except: 
        return "⚠️ Conclusión táctica de la IA temporalmente no disponible."

# --- 8. RECEPTOR DE COMANDOS Y CALLBACKS (PROCESAMIENTO PARALELO) ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("🤖 *Value Betting Engine Premium Activo*\n\nSelecciona una opción del tablero de control:", reply_markup=obtener_teclado_interactivo(), parse_mode="Markdown")

@dp.message(Command("hoy"))
async def cmd_hoy(message: types.Message):
    msg_espera = await message.reply("⏳ Sincronizando agenda de partidos de hoy...")
    await procesar_agenda_comun(msg_espera)

@dp.callback_query()
async def manejador_botones_interactivos(callback_query: types.CallbackQuery):
    await callback_query.answer() # Desbloquea la UI de Telegram al instante
    
    if callback_query.data == "ver_partidos_hoy":
        msg_inicial = await callback_query.message.answer("⏳ Solicitando partidos del día a las APIs...")
        await procesar_agenda_comun(msg_inicial)
        
    elif callback_query.data == "ver_efectividad_ia":
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT local, visitante, prob_over, prob_btts, goles_local_real, goles_visit_real FROM predicciones WHERE estado = 'FINALIZADO'")
        partidos = cursor.fetchall()
        conn.close()
        
        if not partidos:
            return await callback_query.message.answer("ℹ️ No hay registros finalizados en la base de datos para calcular efectividad.", reply_markup=obtener_teclado_interactivo())
        
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
        await message_target.edit_text("📅 *AGENDA DE HOY:*\n\nℹ️ No se detectaron partidos programados para hoy en las ligas de tu plan.", parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())
        return
        
    texto = "📅 *PARTIDOS PROGRAMADOS PARA HOY:*\n\n"
    for p in agenda:
        texto += f"🏆 *[{p['liga']}]* `{p['hora']}` | `{p['local']} vs {p['visitante']}`\n"
    texto += "\n💡 _Usa /analizar Local vs Visitante para procesar un partido._"
    await message_target.edit_text(texto, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    argumentos = re.sub(r'^/analizar(@\w+)?\s+', '', message.text).strip()
    if " vs " not in argumentos: 
        return await message.reply("⚠️ Formato inválido. Usa:\n`/analizar Equipo Local vs Equipo Visitante`", reply_markup=obtener_teclado_interactivo())
    
    eq_local, eq_visit = argumentos.split(" vs ")
    msg = await message.reply("⏳ *[░░░░░░░░░░] 0%* Abriendo compuertas asíncronas...")

    await msg.edit_text(f"⏳ *[███░░░░░░░] 30%* Analizando local sin bloqueo: {eq_local}")
    stats_local = await buscar_datos_equipo(eq_local)
    
    await msg.edit_text(f"⏳ *[██████░░░░] 60%* Analizando visitante sin bloqueo: {eq_visit}")
    stats_visit = await buscar_datos_equipo(eq_visit)

    if not stats_local or not stats_visit:
        return await msg.edit_text("❌ Error: Datos insuficientes en el ecosistema de APIs para computar este cruce.", reply_markup=obtener_teclado_interactivo())

    await msg.edit_text("⏳ *[█████████░] 90%* Calculando Poisson asíncrono...")
    estadisticas = calcular_probabilidades(stats_local, stats_visit)
    corners_avg = round((stats_local['corners'] + stats_visit['corners']) / 2, 1)
    tarjetas_avg = round((stats_local['tarjetas'] + stats_visit['tarjetas']) / 2, 1)
    
    partido_id = guardar_prediccion(stats_local['name'], stats_visit['name'], estadisticas['prob_over_25'], estadisticas['prob_btts'])
    idea_apuesta = await consultar_gemini_analisis(estadisticas, stats_local['name'], stats_visit['name'], corners_avg, tarjetas_avg)
    
    texto_final = (
        f"🆔 *ANÁLISIS DE VALOR METRIC-BET: #{partido_id}*\n⚽ *{stats_local['name']} vs {stats_visit['name']}*\n🔬 _L: {stats_local['fuente']} | V: {stats_visit['fuente']}_\n\n"
        f"📊 *PROYECCIÓN MATEMÁTICA POISSON:*\n🔹 xG Proyectado: {estadisticas['xg_local']} - {estadisticas['xg_visitante']}\n"
        f"📈 Prob. Over 2.5: {estadisticas['prob_over_25']}% | *Cuota Mínima:* `{estadisticas['cuota_over_minima']}+`\n"
        f"🔥 Prob. BTTS: {estadisticas['prob_btts']}% | *Cuota Mínima:* `{estadisticas['cuota_btts_minima']}+`\n"
        f"🚩 Córners: ~{corners_avg} | 🟨 Tarjetas: ~{tarjetas_avg}\n\n"
        f"🛠️ *CREA TU APUESTA SUGERIDO (IA):*\n`{idea_apuesta}`\n\n"
        f"📥 Para cerrar evento usa: `/resultado {partido_id} GolesLocal-GolesVisitante`"
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
    msg = await message.reply("🔍 Buscando en bases de datos asíncronas...")
    data = await buscar_datos_equipo(nombre)
    if not data: 
        return await msg.edit_text("❌ No se hallaron registros deportivos recientes para ese equipo.", reply_markup=obtener_teclado_interactivo())
    texto = f"📋 *MÉTRICAS DEL EQUIPO:*\n\n⚽ *Equipo:* {data['name']}\n🧬 _Origen: {data['fuente']}_\n\n🔹 Goles Anotados/Partido: `{round(data['gf'], 2)}`\n🔸 Goles Recibidos/Partido: `{round(data['gc'], 2)}`"
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
