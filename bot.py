import os
import asyncio
import requests
import numpy as np
from scipy.stats import poisson
import google.generativeai as genai
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command

# --- 1. CONFIGURACIÓN DE TUS APIS (VARIABLES DE ENTORNO) ---
# En Render, debes ir a "Environment" e ingresar estas tres variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Validar que las credenciales existan
if not all([TELEGRAM_TOKEN, FOOTBALL_API_KEY, GEMINI_API_KEY]):
    raise ValueError("Faltan variables de entorno. Verifica tu configuración en Render.")

# Configurar Gemini (Usamos el modelo flash por velocidad)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Inicializar Bot de Telegram
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# --- 2. EXTRACCIÓN DE DATOS EXACTOS (API-FOOTBALL) ---
def buscar_equipo(nombre_equipo):
    """Busca el ID del equipo en internet."""
    url = "https://v3.football.api-sports.io/teams"
    headers = {
        "x-rapidapi-key": FOOTBALL_API_KEY, 
        "x-rapidapi-host": "v3.football.api-sports.io"
    }
    response = requests.get(url, headers=headers, params={"search": nombre_equipo})
    data = response.json().get("response", [])
    if data:
        return data[0]["team"]["id"], data[0]["team"]["name"]
    return None, None

def obtener_goles_promedio(equipo_id, liga_id=140, season="2025"):
    """Trae la estadística pura de goles a favor y en contra."""
    url = "https://v3.football.api-sports.io/teams/statistics"
    headers = {
        "x-rapidapi-key": FOOTBALL_API_KEY, 
        "x-rapidapi-host": "v3.football.api-sports.io"
    }
    # Nota: liga_id=140 es La Liga (España). Ajusta si es necesario.
    response = requests.get(url, headers=headers, params={"team": equipo_id, "league": liga_id, "season": season})
    if response.status_code == 200:
        stats = response.json().get("response", {})
        try:
            gf_home = float(stats['goals']['for']['average']['home'])
            gc_home = float(stats['goals']['against']['average']['home'])
            gf_away = float(stats['goals']['for']['average']['away'])
            gc_away = float(stats['goals']['against']['average']['away'])
            return {"gf_home": gf_home, "gc_home": gc_home, "gf_away": gf_away, "gc_away": gc_away}
        except:
            return None
    return None

# --- 3. MOTOR ESTADÍSTICO MATEMÁTICO (PYTHON PURO) ---
def calcular_probabilidades(goles_local, goles_visitante):
    """Aplica la Distribución de Poisson para sacar porcentajes exactos."""
    promedio_liga = 1.3 # Promedio genérico de goles por equipo en ligas top
    
    # xG (Expected Goals / Goles Esperados)
    xg_local = (goles_local["gf_home"] / promedio_liga) * (goles_visitante["gc_away"] / promedio_liga) * promedio_liga
    xg_visit = (goles_visitante["gf_away"] / promedio_liga) * (goles_local["gc_home"] / promedio_liga) * promedio_liga

    # Probabilidades Poisson (De 0 a 5 goles)
    prob_local = [poisson.pmf(i, xg_local) for i in range(6)]
    prob_visit = [poisson.pmf(i, xg_visit) for i in range(6)]

    # Probabilidad de Over 2.5
    prob_under_25 = sum([prob_local[i] * prob_visit[j] for i in range(6) for j in range(6) if i+j < 3])
    prob_over_25 = 1 - prob_under_25

    # Probabilidad BTTS (Ambos anotan)
    prob_btts = (1 - prob_local[0]) * (1 - prob_visit[0])

    return {
        "xg_local": round(xg_local, 2),
        "xg_visitante": round(xg_visit, 2),
        "prob_over_25": round(prob_over_25 * 100, 2),
        "prob_btts": round(prob_btts * 100, 2)
    }

# --- 4. PRUEBA DE MODELOS E IDEAS CON GEMINI ---
def consultar_gemini(estadisticas, local, visitante):
    """Obliga a Gemini a usar SOLO los datos de Python."""
    prompt = f"""
    Actúa como un estadista deportivo. Se han calculado mediante el modelo de Poisson los datos EXACTOS del partido {local} vs {visitante}.
    
    DATOS REALES (NO INVENTES NADA MÁS):
    - xG (Goles esperados) {local}: {estadisticas['xg_local']}
    - xG (Goles esperados) {visitante}: {estadisticas['xg_visitante']}
    - Probabilidad Over 2.5 goles: {estadisticas['prob_over_25']}%
    - Probabilidad Ambos Anotan: {estadisticas['prob_btts']}%
    
    TAREA:
    Escribe una breve "idea de apuesta" (máximo 4 líneas) basada ESTRICTAMENTE en estos porcentajes. 
    Da una conclusión directa sobre qué mercado estadístico tiene más valor.
    """
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Error Gemini: {e}")
        return "⚠️ Error consultando a la Inteligencia Artificial."

# --- 5. LÓGICA DEL BOT DE TELEGRAM ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Manejador del comando de inicio."""
    welcome_text = (
        "¡Hola! Soy tu bot de análisis estadístico de fútbol. ⚽\n\n"
        "Proceso datos reales en internet y utilizo modelos matemáticos (Poisson) "
        "combinados con IA para darte probabilidades exactas y sin invenciones.\n\n"
        "👇 *CÓMO USARME:*\n"
        "Usa el comando seguido de los equipos que quieres analizar:\n\n"
        "`/analizar Real Madrid vs Barcelona`\n"
        "`/analizar Liverpool vs Arsenal`\n\n"
        "Asegúrate de escribir el 'vs' entre los nombres."
    )
    await message.answer(welcome_text, parse_mode="Markdown")

@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    """Manejador del análisis estadístico."""
    texto = message.text.replace("/analizar", "").strip()
    
    if " vs " not in texto:
        await message.reply("⚠️ Formato incorrecto. Por favor usa: `/analizar Equipo A vs Equipo B`", parse_mode="Markdown")
        return
        
    eq_local_str, eq_visit_str = texto.split(" vs ")
    msg = await message.reply("⏳ *1/3* Buscando información de los equipos...", parse_mode="Markdown")

    id_local, nombre_local = buscar_equipo(eq_local_str.strip())
    id_visit, nombre_visit = buscar_equipo(eq_visit_str.strip())

    if not id_local or not id_visit:
        await msg.edit_text("❌ No logré encontrar uno o ambos equipos en la base de datos oficial. Intenta con un nombre más específico.")
        return

    await msg.edit_text("⏳ *2/3* Procesando estadísticas puras y matemáticas...", parse_mode="Markdown")
    # Para ligas diferentes a La Liga (140), deberás ajustar el id_liga dinámicamente en el futuro.
    stats_local = obtener_goles_promedio(id_local) 
    stats_visit = obtener_goles_promedio(id_visit)

    if not stats_local or not stats_visit:
         await msg.edit_text("❌ No hay datos suficientes de goles para esta temporada en la API.")
         return

    estadisticas = calcular_probabilidades(stats_local, stats_visit)
    
    texto_base = (
        f"📊 *ANÁLISIS ESTADÍSTICO PURO*\n"
        f"⚽ {nombre_local} vs {nombre_visit}\n\n"
        f"🔹 *xG {nombre_local}:* {estadisticas['xg_local']}\n"
        f"🔹 *xG {nombre_visit}:* {estadisticas['xg_visitante']}\n"
        f"📈 *Prob. Over 2.5:* {estadisticas['prob_over_25']}%\n"
        f"🔥 *Prob. Ambos Anotan:* {estadisticas['prob_btts']}%\n\n"
        f"🤖 *3/3* Consultando motor de Inteligencia Artificial..."
    )
    await msg.edit_text(texto_base, parse_mode="Markdown")

    # Inyección a Gemini
    idea_apuesta = consultar_gemini(estadisticas, nombre_local, nombre_visit)
    
    texto_final = texto_base.replace("🤖 *3/3* Consultando motor de Inteligencia Artificial...", f"💡 *CONCLUSIÓN IA:*\n{idea_apuesta}")
    await msg.edit_text(texto_final, parse_mode="Markdown")

async def main():
    print("Iniciando servicio del bot estadístico...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
