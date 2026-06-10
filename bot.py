# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Value Betting Engine Premium v16.2.2-GROQ - Doble Oportunidad y Líneas Over/Under (+/-)

import os
import json
import sqlite3
import re
import asyncio
import aiohttp

# --- OPTIMIZACIÓN DE INSTALACIÓN PARA RENDER ---
os.environ["PIP_NO_CACHE_DIR"] = "off"
os.environ["PIP_PREFER_BINARY"] = "1"

from datetime import datetime
from google import genai
from scipy.stats import poisson
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- 1. CONFIGURACIÓN, CREDENCIALES Y CONSTANTES ---
VERSION_ACTUAL = "v16.2.2-GROQ" 

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

# --- DATA MAESTRA: LAS 48 SELECCIONES DEL MUNDIAL 2026 CALIBRADAS ---
MUNDIAL_48_TEAMS = {
    # CONMEBOL
    "argentina": {"name": "Argentina", "attack": 2.30, "defense": 0.50, "ranking": 1, "corners": 6.2, "tarjetas": 1.5, "forma": "V-V-E-V-V"},
    "brasil": {"name": "Brasil", "attack": 1.90, "defense": 0.80, "ranking": 5, "corners": 5.8, "tarjetas": 2.1, "forma": "V-E-D-V-E"},
    "colombia": {"name": "Colombia", "attack": 1.80, "defense": 0.70, "ranking": 12, "corners": 5.5, "tarjetas": 2.3, "forma": "V-V-E-V-V"},
    "uruguay": {"name": "Uruguay", "attack": 1.80, "defense": 0.80, "ranking": 11, "corners": 5.2, "tarjetas": 2.4, "forma": "E-V-D-V-V"},
    "ecuador": {"name": "Ecuador", "attack": 1.20, "defense": 0.70, "ranking": 31, "corners": 4.8, "tarjetas": 2.0, "forma": "V-E-V-D-E"},
    "venezuela": {"name": "Venezuela", "attack": 1.10, "defense": 1.00, "ranking": 54, "corners": 4.2, "tarjetas": 2.5, "forma": "E-D-V-E-E"},
    "chile": {"name": "Chile", "attack": 1.00, "defense": 1.10, "ranking": 42, "corners": 4.5, "tarjetas": 2.6, "forma": "D-E-V-D-D"},
    
    # UEFA
    "francia": {"name": "Francia", "attack": 2.10, "defense": 0.60, "ranking": 2, "corners": 6.0, "tarjetas": 1.4, "forma": "V-V-D-V-V"},
    "españa": {"name": "España", "attack": 2.00, "defense": 0.70, "ranking": 3, "corners": 6.5, "tarjetas": 1.8, "forma": "V-V-E-V-V"},
    "inglaterra": {"name": "Inglaterra", "attack": 1.90, "defense": 0.70, "ranking": 4, "corners": 5.9, "tarjetas": 1.2, "forma": "E-V-V-D-V"},
    "portugal": {"name": "Portugal", "attack": 2.20, "defense": 0.80, "ranking": 7, "corners": 6.1, "tarjetas": 1.9, "forma": "V-V-E-V-D"},
    "países bajos": {"name": "Países Bajos", "attack": 1.70, "defense": 0.80, "ranking": 8, "corners": 5.4, "tarjetas": 1.7, "forma": "V-D-V-E-V"},
    "italia": {"name": "Italia", "attack": 1.50, "defense": 0.70, "ranking": 9, "corners": 5.0, "tarjetas": 2.2, "forma": "E-V-E-D-V"},
    "croacia": {"name": "Croacia", "attack": 1.40, "defense": 0.80, "ranking": 10, "corners": 4.8, "tarjetas": 1.6, "forma": "E-E-V-D-V"},
    "alemania": {"name": "Alemania", "attack": 1.80, "defense": 0.90, "ranking": 16, "corners": 5.7, "tarjetas": 2.0, "forma": "V-E-V-V-D"},
    "suiza": {"name": "Suiza", "attack": 1.30, "defense": 1.00, "ranking": 19, "corners": 4.6, "tarjetas": 2.1, "forma": "E-V-D-E-V"},
    "dinamarca": {"name": "Dinamarca", "attack": 1.40, "defense": 1.00, "ranking": 21, "corners": 4.9, "tarjetas": 1.5, "forma": "D-V-E-V-E"},
    "ucrania": {"name": "Ucrania", "attack": 1.30, "defense": 1.10, "ranking": 22, "corners": 4.7, "tarjetas": 2.2, "forma": "V-D-E-E-V"},
    "austria": {"name": "Austria", "attack": 1.50, "defense": 1.00, "ranking": 25, "corners": 5.1, "tarjetas": 2.4, "forma": "V-E-V-D-V"},
    "suecia": {"name": "Suecia", "attack": 1.50, "defense": 1.20, "ranking": 28, "corners": 5.3, "tarjetas": 1.9, "forma": "E-V-D-V-D"},
    "hungría": {"name": "Hungría", "attack": 1.20, "defense": 1.10, "ranking": 27, "corners": 4.4, "tarjetas": 2.0, "forma": "D-E-V-V-E"},
    "turquía": {"name": "Turquía", "attack": 1.40, "defense": 1.20, "ranking": 40, "corners": 4.9, "tarjetas": 2.5, "forma": "V-D-D-E-V"},
    
    # CONCACAF
    "estados unidos": {"name": "Estados Unidos", "attack": 1.40, "defense": 1.00, "ranking": 14, "corners": 5.0, "tarjetas": 1.8, "forma": "V-E-D-V-V"},
    "méxico": {"name": "México", "attack": 1.30, "defense": 1.10, "ranking": 15, "corners": 4.8, "tarjetas": 2.3, "forma": "E-V-D-E-V"},
    "canadá": {"name": "Canadá", "attack": 1.40, "defense": 1.10, "ranking": 49, "corners": 5.1, "tarjetas": 2.1, "forma": "V-V-D-E-D"},
    "panamá": {"name": "Panamá", "attack": 1.20, "defense": 1.20, "ranking": 45, "corners": 4.4, "tarjetas": 2.2, "forma": "E-V-D-V-D"},
    "costa rica": {"name": "Costa Rica", "attack": 1.00, "defense": 1.30, "ranking": 52, "corners": 4.0, "tarjetas": 2.4, "forma": "D-E-E-V-D"},
    "jamaica": {"name": "Jamaica", "attack": 1.10, "defense": 1.20, "ranking": 55, "corners": 4.2, "tarjetas": 2.5, "forma": "V-D-E-D-V"},
    
    # CAF (ÁFRICA)
    "marruecos": {"name": "Marruecos", "attack": 1.60, "defense": 0.70, "ranking": 13, "corners": 5.4, "tarjetas": 1.9, "forma": "V-V-E-D-V"},
    "senegal": {"name": "Senegal", "attack": 1.50, "defense": 0.80, "ranking": 17, "corners": 5.1, "tarjetas": 2.0, "forma": "V-E-V-V-D"},
    "nigeria": {"name": "Nigeria", "attack": 1.60, "defense": 1.10, "ranking": 28, "corners": 5.3, "tarjetas": 2.2, "forma": "E-D-V-V-D"},
    "egipto": {"name": "Egipto", "attack": 1.40, "defense": 0.90, "ranking": 36, "corners": 4.7, "tarjetas": 2.1, "forma": "V-V-E-D-E"},
    "costa de marfil": {"name": "Costa de Marfil", "attack": 1.40, "defense": 1.00, "ranking": 39, "corners": 4.8, "tarjetas": 2.3, "forma": "V-E-D-V-V"},
    "túnez": {"name": "Túnez", "attack": 1.00, "defense": 0.90, "ranking": 41, "corners": 4.1, "tarjetas": 1.8, "forma": "E-E-V-D-E"},
    "argelia": {"name": "Argelia", "attack": 1.40, "defense": 1.00, "ranking": 43, "corners": 4.9, "tarjetas": 2.0, "forma": "V-D-E-V-D"},
    "camerún": {"name": "Camerún", "attack": 1.20, "defense": 1.10, "ranking": 46, "corners": 4.5, "tarjetas": 2.4, "forma": "D-V-E-E-D"},
    "malí": {"name": "Malí", "attack": 1.10, "defense": 1.00, "ranking": 47, "corners": 4.3, "tarjetas": 2.1, "forma": "E-V-D-E-E"},
    "sudáfrica": {"name": "Sudáfrica", "attack": 1.00, "defense": 1.20, "ranking": 59, "corners": 4.0, "tarjetas": 2.2, "forma": "D-E-V-D-V"},
    
    # AFC (ASIA)
    "japón": {"name": "Japón", "attack": 1.80, "defense": 0.90, "ranking": 18, "corners": 5.6, "tarjetas": 1.3, "forma": "V-V-E-V-D"},
    "irán": {"name": "Irán", "attack": 1.50, "defense": 1.00, "ranking": 20, "corners": 4.8, "tarjetas": 2.1, "forma": "V-E-V-D-V"},
    "corea del sur": {"name": "Corea del Sur", "attack": 1.60, "defense": 1.10, "ranking": 23, "corners": 5.1, "tarjetas": 1.6, "forma": "E-V-V-D-E"},
    "australia": {"name": "Australia", "attack": 1.30, "defense": 0.90, "ranking": 24, "corners": 5.0, "tarjetas": 1.9, "forma": "V-D-E-V-E"},
    "catar": {"name": "Catar", "attack": 1.20, "defense": 1.30, "ranking": 34, "corners": 4.3, "tarjetas": 2.0, "forma": "D-V-D-E-E"},
    "irak": {"name": "Irak", "attack": 1.20, "defense": 1.20, "ranking": 58, "corners": 4.4, "tarjetas": 2.4, "forma": "E-V-D-D-V"},
    "arabia saudita": {"name": "Arabia Saudita", "attack": 1.10, "defense": 1.20, "ranking": 56, "corners": 4.2, "tarjetas": 2.2, "forma": "D-E-E-V-D"},
    "uzbekistán": {"name": "Uzbekistán", "attack": 1.10, "defense": 1.10, "ranking": 64, "corners": 4.1, "tarjetas": 1.9, "forma": "E-V-D-E-V"},
    
    # OFC (OCEANÍA)
    "nueva zelanda": {"name": "Nueva Zelanda", "attack": 0.90, "defense": 1.40, "ranking": 85, "corners": 3.8, "tarjetas": 2.0, "forma": "D-D-E-V-D"}
}

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

# --- 4. PIPELINE DE EXTRACCIÓN ESTADÍSTICA (GROQ INVESTIGA -> GEMINI AUDITA) ---
async def pipeline_auditoria_invertida(nombre_equipo):
    prompt_groq = f"""
    Investigate the last 10 official competitive matches of the football team: "{nombre_equipo}".
    Calculate match averages for goals scored (gf), goals conceded (gc), corners, and cards.
    Return ONLY a flat JSON object, no conversational text, no markdown tags:
    {{"name": "{nombre_equipo}", "gf": 1.90, "gc": 0.85, "corners": 5.5, "tarjetas": 1.9, "forma": "V-V-E-D-V"}}
    """
    datos_groq_txt = "{}"
    if RESPALDO_API_KEY:
        headers = {"Authorization": f"Bearer {RESPALDO_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": MODELO_GROQ,
            "messages": [
                {"role": "system", "content": "You are a precise database router that only outputs raw JSON. No markdown."},
                {"role": "user", "content": prompt_groq}
            ],
            "temperature": 0.1, "max_tokens": 250
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(RESPALDO_API_URL, headers=headers, json=payload, timeout=6.0) as response:
                    if response.status == 200:
                        res_data = await response.json()
                        datos_groq_txt = res_data['choices'][0]['message']['content'].strip()
                        datos_groq_txt = re.sub(r'^```json\s*|\s*```$', '', datos_groq_txt, flags=re.IGNORECASE).strip()
        except: pass

    prompt_gemini_auditor = f"""
    Analiza las métricas iniciales arrojadas por Groq para el equipo "{nombre_equipo}": {datos_groq_txt}
    Compara con tu conocimiento global y corrige los promedios de goles anotados (gf), recibidos (gc), córners y tarjetas si difieren de la realidad reciente.
    Devuelve estrictamente un JSON plano sin texto conversacional ni bloques markdown:
    {{"name": "{nombre_equipo}", "gf": valor, "gc": valor, "corners": valor, "tarjetas": valor, "forma": "Racha"}}
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
    except:
        try:
            data_groq_clean = json.loads(datos_groq_txt)
            return data_groq_clean, "Bypass Directo Groq LPU"
        except:
            return None

# --- 5. BUSCADOR INTEGRADO CON MUNDIAL 48 Y ASIGNADOR DE CONTEXTO ---
async def buscar_datos_equipo(nombre_equipo):
    nombre_limpio = nombre_equipo.strip()
    key_busqueda = nombre_limpio.lower()
    
    # 1. Comprobación de contingencia en la Base de Datos Maestra Local de 48 selecciones
    if key_busqueda in MUNDIAL_48_TEAMS:
        team_data = MUNDIAL_48_TEAMS[key_busqueda]
        return {
            'name': team_data['name'],
            'gf': team_data['attack'],
            'gc': team_data['defense'],
            'corners': team_data['corners'],
            'tarjetas': team_data['tarjetas'],
            'forma': team_data['forma'],
            'fuente': "Engine Base Mundial 48 Calibrado"
        }
        
    # 2. Si no es selección del mundial, corre el flujo normal del pipeline de red
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
    
    # 3. Resguardo de emergencia por contexto amplio general
    es_elite = any(x in key_busqueda for x in ["madrid", "city", "barcelona", "bayern"])
    es_debil = any(x in key_busqueda for x in ["islandia", "jordania", "bolivia", "andorra", "malta"])
    
    gf_emergency = 2.10 if es_elite else (0.80 if es_debil else 1.40)
    gc_emergency = 0.65 if es_elite else (1.80 if es_debil else 1.20)
    corners_emergency = 5.8 if es_elite else (3.5 if es_debil else 4.5)
    forma_emergency = "V-V-E-V-V" if es_elite else ("D-D-E-D-V" if es_debil else "E-V-E-D-V")
    
    return {"name": nombre_limpio, "gf": gf_emergency, "gc": gc_emergency, "corners": corners_emergency, "tarjetas": 2.0, "forma": forma_emergency, "fuente": "Modelado Dinámico Contextual"}

# --- 6. PROCESAMIENTO MATEMÁTICO PURO (POISSON) ---
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
        "cuota_over_minima": round(100 / (p_over if p_over > 0 else 1) * 1.05, 2)
    }

# --- 7. REDACCIÓN COGNITIVA ORIENTADA A DOBLE OPORTUNIDAD, CÓRNERS Y TARJETAS (+/-) ---
async def generar_informe_scouting_ia(estadisticas, local_stats, visit_stats, corners, tarjetas):
    favorito = local_stats['name'] if estadisticas['xg_local'] >= estadisticas['xg_visitante'] else visit_stats['name']
    
    prompt = f"""
    Actúa como analista senior de fútbol. Genera un reporte resumido para el partido {local_stats['name']} vs {visit_stats['name']}.
    Datos calculados:
    - xG Proyectado: Local {estadisticas['xg_local']} vs {estadisticas['xg_visitante']} Visitante
    - Línea Base Córners: {corners} | Línea Base Tarjetas: {tarjetas}
    - Racha: Local [{local_stats['forma']}] vs Visitante [{visit_stats['forma']}]

    Formatea la salida estrictamente en Markdown limpio usando ## para los títulos:
    ## 📊 1. ANÁLISIS SENSORIAL Y CONTEXTUAL: Explica la ventaja táctica del favorito ({favorito}) basándote en los xG y la racha.
    ## 🎯 2. RECOMENDACIÓN PREMIUM (CREA TU APUESTA): Estructura exactamente estos tres picks explicados de manera concisa:
       - Mercado 1 (Doble Oportunidad): {favorito} o Empate (Explicar el porqué).
       - Mercado 2 (Córners / Tiros de esquina): Definir si apostar "Más de" o "Menos de" evaluando la línea base de {corners}.
       - Mercado 3 (Tarjetas): Definir si apostar "Más de" o "Menos de" evaluando la línea base de {tarjetas}.
    Nota: Sé ultra conciso. No saludes, no uses introducciones largas. Ve directo a las secciones.
    """
    try:
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: client.models.generate_content(model='gemini-2.5-flash', contents=prompt)),
            timeout=12.0
        )
        return response.text.strip(), "Gemini 2.5-Flash"
    except:
        headers = {"Authorization": f"Bearer {RESPALDO_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": MODELO_GROQ,
            "messages": [
                {"role": "system", "content": f"Eres un analista de fútbol directo. Ecribes en Markdown estructurando Doble Oportunidad para {favorito} y líneas de +/- para córners y tarjetas."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2, "max_tokens": 500
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(RESPALDO_API_URL, headers=headers, json=payload, timeout=12.0) as response:
                    if response.status == 200:
                        res_data = await response.json()
                        return res_data['choices'][0]['message']['content'].strip(), f"Groq LPU ({MODELO_GROQ})"
        except: pass
    return "⚠️ El módulo de redacción táctica final no pudo procesarse debido a restricciones temporales de tokens en los servidores externos.", "Predictor de Emergencia"

# --- 8. MANEJADORES DE TELEGRAM ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    texto_bienvenida = f"🤖 *Value Betting Engine Premium Active*\n⚙️ *Versión:* `{VERSION_ACTUAL}`\n\nPipeline calibrado para Doble Oportunidad, +/- Córners y Tarjetas de forma inmune con base de datos del Mundial 2026."
    await message.answer(texto_bienvenida, reply_markup=obtener_teclado_interactivo(), parse_mode="Markdown")

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    argumentos = re.sub(r'^/analizar(@\w+)?\s+', '', message.text).strip()
    if " vs " not in argumentos: 
        return await message.reply("⚠️ Usa:\n`/analizar Local vs Visitante`", 