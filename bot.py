# Autor: Cristian Rafael Hernández Galvis
# Código Estudiantil: 20251025024
# Proyecto: Value Betting Engine Premium v16.2.2-MUNDIAL - Doble Oportunidad, Líneas +/- y Fechas

import os
import json
import sqlite3
import re
import asyncio
import aiohttp
import datetime

# --- OPTIMIZACIÓN DE INSTALACIÓN PARA RENDER ---
os.environ["PIP_NO_CACHE_DIR"] = "off"
os.environ["PIP_PREFER_BINARY"] = "1"

from google import genai
from scipy.stats import poisson
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- 1. CONFIGURACIÓN, CREDENCIALES Y CONSTANTES ---
VERSION_ACTUAL = "v16.2.2-MUNDIAL" 

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

# --- DATA MAESTRA: LAS 48 SELECCIONES DEL MUNDIAL 2026 CALIBRADAS ---
MUNDIAL_48_TEAMS = {
    # CONMEBOL
    "ARG": {"name": "Argentina", "attack": 2.30, "defense": 0.50, "ranking": 1, "corners": 6.2, "tarjetas": 1.5, "forma": "V-V-E-V-V"},
    "BRA": {"name": "Brasil", "attack": 1.90, "defense": 0.80, "ranking": 5, "corners": 5.8, "tarjetas": 2.1, "forma": "V-E-D-V-E"},
    "COL": {"name": "Colombia", "attack": 1.80, "defense": 0.70, "ranking": 12, "corners": 5.5, "tarjetas": 2.3, "forma": "V-V-E-V-V"},
    "URU": {"name": "Uruguay", "attack": 1.80, "defense": 0.80, "ranking": 11, "corners": 5.2, "tarjetas": 2.4, "forma": "E-V-D-V-V"},
    "ECU": {"name": "Ecuador", "attack": 1.20, "defense": 0.70, "ranking": 31, "corners": 4.8, "tarjetas": 2.0, "forma": "V-E-V-D-E"},
    "VEN": {"name": "Venezuela", "attack": 1.10, "defense": 1.00, "ranking": 54, "corners": 4.2, "tarjetas": 2.5, "forma": "E-D-V-E-E"},
    "CHI": {"name": "Chile", "attack": 1.00, "defense": 1.10, "ranking": 42, "corners": 4.5, "tarjetas": 2.6, "forma": "D-E-V-D-D"},
    # UEFA
    "FRA": {"name": "Francia", "attack": 2.10, "defense": 0.60, "ranking": 2, "corners": 6.0, "tarjetas": 1.4, "forma": "V-V-D-V-V"},
    "ESP": {"name": "España", "attack": 2.00, "defense": 0.70, "ranking": 3, "corners": 6.5, "tarjetas": 1.8, "forma": "V-V-E-V-V"},
    "ENG": {"name": "Inglaterra", "attack": 1.90, "defense": 0.70, "ranking": 4, "corners": 5.9, "tarjetas": 1.2, "forma": "E-V-V-D-V"},
    "POR": {"name": "Portugal", "attack": 2.20, "defense": 0.80, "ranking": 7, "corners": 6.1, "tarjetas": 1.9, "forma": "V-V-E-V-D"},
    "NED": {"name": "Países Bajos", "attack": 1.70, "defense": 0.80, "ranking": 8, "corners": 5.4, "tarjetas": 1.7, "forma": "V-D-V-E-V"},
    "ITA": {"name": "Italia", "attack": 1.50, "defense": 0.70, "ranking": 9, "corners": 5.0, "tarjetas": 2.2, "forma": "E-V-E-D-V"},
    "CRO": {"name": "Croacia", "attack": 1.40, "defense": 0.80, "ranking": 10, "corners": 4.8, "tarjetas": 1.6, "forma": "E-E-V-D-V"},
    "GER": {"name": "Alemania", "attack": 1.80, "defense": 0.90, "ranking": 16, "corners": 5.7, "tarjetas": 2.0, "forma": "V-E-V-V-D"},
    "SUI": {"name": "Suiza", "attack": 1.30, "defense": 1.00, "ranking": 19, "corners": 4.6, "tarjetas": 2.1, "forma": "E-V-D-E-V"},
    "DEN": {"name": "Dinamarca", "attack": 1.40, "defense": 1.00, "ranking": 21, "corners": 4.9, "tarjetas": 1.5, "forma": "D-V-E-V-E"},
    "UKR": {"name": "Ucrania", "attack": 1.30, "defense": 1.10, "ranking": 22, "corners": 4.7, "tarjetas": 2.2, "forma": "V-D-E-E-V"},
    "AUT": {"name": "Austria", "attack": 1.50, "defense": 1.00, "ranking": 25, "corners": 5.1, "tarjetas": 2.4, "forma": "V-E-V-D-V"},
    "SWE": {"name": "Suecia", "attack": 1.50, "defense": 1.20, "ranking": 28, "corners": 5.3, "tarjetas": 1.9, "forma": "E-V-D-V-D"},
    "HUN": {"name": "Hungría", "attack": 1.20, "defense": 1.10, "ranking": 27, "corners": 4.4, "tarjetas": 2.0, "forma": "D-E-V-V-E"},
    "TUR": {"name": "Turquía", "attack": 1.40, "defense": 1.20, "ranking": 40, "corners": 4.9, "tarjetas": 2.5, "forma": "V-D-D-E-V"},
    # CONCACAF
    "USA": {"name": "Estados Unidos", "attack": 1.40, "defense": 1.00, "ranking": 14, "corners": 5.0, "tarjetas": 1.8, "forma": "V-E-D-V-V"},
    "MEX": {"name": "México", "attack": 1.30, "defense": 1.10, "ranking": 15, "corners": 4.8, "tarjetas": 2.3, "forma": "E-V-D-E-V"},
    "CAN": {"name": "Canadá", "attack": 1.40, "defense": 1.10, "ranking": 49, "corners": 5.1, "tarjetas": 2.1, "forma": "V-V-D-E-D"},
    "PAN": {"name": "Panamá", "attack": 1.20, "defense": 1.20, "ranking": 45, "corners": 4.4, "tarjetas": 2.2, "forma": "E-V-D-V-D"},
    "CRC": {"name": "Costa Rica", "attack": 1.00, "defense": 1.30, "ranking": 52, "corners": 4.0, "tarjetas": 2.4, "forma": "D-E-E-V-D"},
    "JAM": {"name": "Jamaica", "attack": 1.10, "defense": 1.20, "ranking": 55, "corners": 4.2, "tarjetas": 2.5, "forma": "V-D-E-D-V"},
    # CAF (ÁFRICA)
    "MAR": {"name": "Marruecos", "attack": 1.60, "defense": 0.70, "ranking": 13, "corners": 5.4, "tarjetas": 1.9, "forma": "V-V-E-D-V"},
    "SEN": {"name": "Senegal", "attack": 1.50, "defense": 0.80, "ranking": 17, "corners": 5.1, "tarjetas": 2.0, "forma": "V-E-V-V-D"},
    "NGA": {"name": "Nigeria", "attack": 1.60, "defense": 1.10, "ranking": 28, "corners": 5.3, "tarjetas": 2.2, "forma": "E-D-V-V-D"},
    "EGY": {"name": "Egipto", "attack": 1.40, "defense": 0.90, "ranking": 36, "corners": 4.7, "tarjetas": 2.1, "forma": "V-V-E-D-E"},
    "CIV": {"name": "Costa de Marfil", "attack": 1.40, "defense": 1.00, "ranking": 39, "corners": 4.8, "tarjetas": 2.3, "forma": "V-E-D-V-V"},
    "TUN": {"name": "Túnez", "attack": 1.00, "defense": 0.90, "ranking": 41, "corners": 4.1, "tarjetas": 1.8, "forma": "E-E-V-D-E"},
    "ALG": {"name": "Argelia", "attack": 1.40, "defense": 1.00, "ranking": 43, "corners": 4.9, "tarjetas": 2.0, "forma": "V-D-E-V-D"},
    "CMR": {"name": "Camerún", "attack": 1.20, "defense": 1.10, "ranking": 46, "corners": 4.5, "tarjetas": 2.4, "forma": "D-V-E-E-D"},
    "MLI": {"name": "Malí", "attack": 1.10, "defense": 1.00, "ranking": 47, "corners": 4.3, "tarjetas": 2.1, "forma": "E-V-D-E-E"},
    "RSA": {"name": "Sudáfrica", "attack": 1.00, "defense": 1.20, "ranking": 59, "corners": 4.0, "tarjetas": 2.2, "forma": "D-E-V-D-V"},
    # AFC (ASIA)
    "JPN": {"name": "Japón", "attack": 1.80, "defense": 0.90, "ranking": 18, "corners": 5.6, "tarjetas": 1.3, "forma": "V-V-E-V-D"},
    "IRN": {"name": "Irán", "attack": 1.50, "defense": 1.00, "ranking": 20, "corners": 4.8, "tarjetas": 2.1, "forma": "V-E-V-D-V"},
    "KOR": {"name": "Corea del Sur", "attack": 1.60, "defense": 1.10, "ranking": 23, "corners": 5.1, "tarjetas": 1.6, "forma": "E-V-V-D-E"},
    "AUS": {"name": "Australia", "attack": 1.30, "defense": 0.90, "ranking": 24, "corners": 5.0, "tarjetas": 1.9, "forma": "V-D-E-V-E"},
    "QAT": {"name": "Catar", "attack": 1.20, "defense": 1.30, "ranking": 34, "corners": 4.3, "tarjetas": 2.0, "forma": "D-V-D-E-E"},
    "IRQ": {"name": "Irak", "attack": 1.20, "defense": 1.20, "ranking": 58, "corners": 4.4, "tarjetas": 2.4, "forma": "E-V-D-D-V"},
    "KSA": {"name": "Arabia Saudita", "attack": 1.10, "defense": 1.20, "ranking": 56, "corners": 4.2, "tarjetas": 2.2, "forma": "D-E-E-V-D"},
    "UZB": {"name": "Uzbekistán", "attack": 1.10, "defense": 1.10, "ranking": 64, "corners": 4.1, "tarjetas": 1.9, "forma": "E-V-D-E-V"},
    # OCEANÍA
    "NZL": {"name": "Nueva Zelanda", "attack": 0.90, "defense": 1.40, "ranking": 85, "corners": 3.8, "tarjetas": 2.0, "forma": "D-D-E-V-D"}
}

# --- CALENDARIO DEL MUNDIAL MAQUETADO POR FECHAS ---
FIXTURES_BY_DATE = {
    "2026-06-11": [
        {"id": "M01", "home": "USA", "away": "MEX", "time": "15:00", "stage": "Grupo A (Inaugural)"},
        {"id": "M02", "home": "CAN", "away": "PAN", "time": "19:00", "stage": "Grupo B"}
    ],
    "2026-06-12": [
        {"id": "M03", "home": "ARG", "away": "GER", "time": "13:00", "stage": "Grupo C"},
        {"id": "M04", "home": "COL", "away": "ITA", "time": "17:00", "stage": "Grupo C"}
    ],
    "2026-06-13": [
        {"id": "M05", "home": "BRA", "away": "JPN", "time": "14:00", "stage": "Grupo E"},
        {"id": "M06", "home": "ESP", "away": "MAR", "time": "18:00", "stage": "Grupo F"}
    ]
}

def make_visual_bar(percentage: float, emoji="🟩", length=14) -> str:
    filled = int((percentage / 100) * length)
    filled = max(1, min(filled, length))
    empty = length - filled
    return f"{emoji * filled}{'⬛' * empty}"

# --- 2. GENERADOR DE TECLADO INTERACTIVO BASE ---
def obtener_teclado_interactivo():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="📅 Partidos del Mundial", callback_data="ver_calendario_fechas"),
        types.InlineKeyboardButton(text="📊 Analizar Libre", switch_inline_query_current_chat="/analizar ")
    )
    builder.row(
        types.InlineKeyboardButton(text="🔍 Buscar Equipo", switch_inline_query_current_chat="/equipo "),
        types.InlineKeyboardButton(text="⚙️ Engine", callback_data="info_version")
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

# --- 4. PIPELINE DE EXTRACCIÓN ESTADÍSTICA EXTERNA ---
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

# --- 5. BUSCADOR INTELIGENTE CON PRIORIDAD MUNDIALISTA ---
async def buscar_datos_equipo(nombre_equipo):
    nombre_limpio = nombre_equipo.strip()
    
    # Verificación de abreviaturas del mundial (Ej: ARG, COL) o coincidencia por nombre completo
    for key, value in MUNDIAL_48_TEAMS.items():
        if nombre_limpio.upper() == key or nombre_limpio.lower() == value['name'].lower():
            return {
                'name': value['name'],
                'gf': value['attack'],
                'gc': value['defense'],
                'corners': value['corners'],
                'tarjetas': value['tarjetas'],
                'forma': value['forma'],
                'fuente': "Engine Base Mundial 28 Calibrado"
            }
            
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
    
    return {"name": nombre_limpio, "gf": 1.40, "gc": 1.10, "corners": 4.5, "tarjetas": 2.0, "forma": "E-V-D-E-V", "fuente": "Modelado Contextual"}

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

# --- 7. REDACCIÓN COGNITIVA ASÍNCRONA ---
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
       - Mercado 1 (Doble Oportunidad): {favorito} o Empate.
       - Mercado 2 (Córners / Tiros de esquina): Definir si apostar "Más de" o "Menos de" evaluando la línea base de {corners}.
       - Mercado 3 (Tarjetas): Definir si apostar "Más de" o "Menos de" evaluando la línea base de {tarjetas}.
    Nota: Sé ultra conciso. Ve directo a las secciones.
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
    return "⚠️ El módulo de redacción táctica final no pudo procesarse debido a restricciones temporales de tokens.", "Predictor de Emergencia"

# --- 8. MANEJADORES DE TELEGRAM (COMANDOS Y BOTONES) ---
@dp.message(Command("start", "menu"))
async def cmd_start(message: types.Message):
    texto_bienvenida = f"🤖 *Value Betting Engine Premium Active*\n⚙️ *Versión:* `{VERSION_ACTUAL}`\n\nPipeline calibrado para Doble Oportunidad, +/- Córners y Tarjetas del Mundial."
    await message.answer(texto_bienvenida, reply_markup=obtener_teclado_interactivo(), parse_mode="Markdown")

@dp.callback_query(F.data == "ver_calendario_fechas")
@dp.callback_query(F.data == "back_cal")
async def show_dates_menu(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for date_key in FIXTURES_BY_DATE.keys():
        dt = datetime.datetime.strptime(date_key, "%Y-%m-%d")
        nice_date = dt.strftime("%A, %d de %B").upper()
        builder.row(types.InlineKeyboardButton(text=f"📅 {nice_date}", callback_data=f"date_{date_key}"))
    
    await callback.message.edit_text(
        text="🤖 *MUNDIAL IA PREDICTOR — SELECCIÓN DE JORNADA*\n\nElige una fecha para listar los compromisos del día:",
        parse_mode="Markdown", reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("date_"))
async def list_matches_by_date(callback: types.CallbackQuery):
    selected_date = callback.data.split('_')[1]
    matches = FIXTURES_BY_DATE.get(selected_date, [])
    
    builder = InlineKeyboardBuilder()
    for m in matches:
        home_name = MUNDIAL_48_TEAMS[m["home"]]["name"]
        away_name = MUNDIAL_48_TEAMS[m["away"]]["name"]
        btn_text = f"⚽ [{m['time']}] {home_name} vs {away_name}"
        builder.row(types.InlineKeyboardButton(text=btn_text, callback_data=f"proc_{selected_date}_{m['id']}"))
        
    builder.row(types.InlineKeyboardButton(text="⬅️ JORNADAS", callback_data="back_cal"))
    
    await callback.message.edit_text(
        text=f"👇 *PARTIDOS PROGRAMADOS PARA EL {selected_date}:*\nSelecciona un encuentro para correr el motor de Poisson:",
        parse_mode="Markdown", reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("proc_"))
async def process_match_callback(callback: types.CallbackQuery):
    _, date_key, match_id = callback.data.split('_')
    match = next((m for m in FIXTURES_BY_DATE[date_key] if m["id"] == match_id), None)
    await callback.message.edit_text("⏳ *[████░░░░░░] 40%* Corriendo simulación matemática mediante distribución de Poisson...")
    
    h_stats = MUNDIAL_48_TEAMS[match["home"]]
    a_stats = MUNDIAL_48_TEAMS[match["away"]]
    
    await process_and_send_final_report(callback.message, h_stats, a_stats)

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    argumentos = re.sub(r'^/analizar(@\w+)?\s+', '', message.text).strip()
    if " vs " not in argumentos: 
        return await message.reply("⚠️ Usa:\n`/analizar Local vs Visitante` (o selecciona un partido del menú)")
    
    eq_local, eq_visit = argumentos.split(" vs ")
    msg = await message.reply("⏳ *[██░░░░░░░░] 20%* Extrayendo promedios numéricos mediante pipeline cruzado...")
    
    try:
        stats_local = await buscar_datos_equipo(eq_local)
        await asyncio.sleep(1.0)
        stats_visit = await buscar_datos_equipo(eq_visit)
        await process_and_send_final_report(msg, stats_local, stats_visit, is_edit=False)
    except Exception as e:
        await msg.answer(f"❌ Error en subproceso: {e}", reply_markup=obtener_teclado_interactivo())

async def process_and_send_final_report(msg_obj: types.Message, stats_local, stats_visit, is_edit=True):
    estadisticas = calcular_probabilidades(stats_local, stats_visit)
    corners_avg = round((stats_local['corners'] + stats_visit['corners']) / 2, 1)
    tarjetas_avg = round((stats_local['tarjetas'] + stats_visit['tarjetas']) / 2, 1)
    
    partido_id = guardar_prediccion(stats_local['name'], stats_visit['name'], estadisticas['prob_over_25'], estadisticas['prob_btts'])
    informe_scouting, motor_usado = await generar_informe_scouting_ia(estadisticas, stats_local, stats_visit, corners_avg, tarjetas_avg)
    
    opta_terminal_view = (
        f"📊 *TERMINAL IA — PROYECCIÓN ESTADÍSTICA*\n"
        f"`------------------------------------------`\n"
        f"🆔 *INFORME METRIC-BET: #{partido_id} ({VERSION_ACTUAL})*\n"
        f"⚽ *{stats_local['name'].upper()} vs {stats_visit['name'].upper()}*\n"
        f"🔬 _L: {stats_local['fuente']} | V: {stats_visit['fuente']}_\n"
        f"`------------------------------------------`\n\n"
        f"📈 *PROBABILIDADES MATEMÁTICAS (POISSON)*\n"
        f" Local xG: `{estadisticas['xg_local']}` | Visita xG: `{estadisticas['xg_visitante']}`\n"
        f" Prob Over 2.5: *{estadisticas['prob_over_25']}%* {make_visual_bar(estadisticas['prob_over_25'], '🟦')}\n"
        f" Prob BTTS:     *{estadisticas['prob_btts']}%* {make_visual_bar(estadisticas['prob_btts'], '🟨')}\n\n"
        f"🚩 *LÍNEAS BASE DE APUESTA PROYECTADAS*\n"
        f" Tiros de Esquina:  `~{corners_avg}` \n"
        f" Tarjetas Totales:  `~{tarjetas_avg}` \n\n"
        f"🔬 *INFORME TÁCTICO DE SCOUTING ({motor_usado}):*\n\n{informe_scouting}\n\n"
        f"`------------------------------------------`\n"
        f"📥 Registrar cierre con: `/resultado {partido_id} GolesLocal-GolesVisitante`"
    )
    
    if is_edit:
        await msg_obj.edit_text(opta_terminal_view, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())
    else:
        await msg_obj.answer(opta_terminal_view, parse_mode="Markdown", reply_markup=obtener_teclado_interactivo())

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
