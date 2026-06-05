import os
import asyncio
import logging
import requests
import numpy as np
from scipy.stats import poisson
from google import genai
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command

# ─────────────────────────────────────────────
# 1. CONFIGURACIÓN Y VALIDACIÓN
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
FOOTBALL_API_KEY  = os.getenv("API_FOOTBALL_KEY")
GEMINI_API_KEY    = os.getenv("GEMINI_KEY")

if not all([TELEGRAM_TOKEN, FOOTBALL_API_KEY, GEMINI_API_KEY]):
    raise ValueError(
        "Faltan variables de entorno. "
        "Verifica TELEGRAM_TOKEN, API_FOOTBALL_KEY y GEMINI_KEY."
    )

client = genai.Client(api_key=GEMINI_API_KEY)
bot    = Bot(token=TELEGRAM_TOKEN)
dp     = Dispatcher()

# ─────────────────────────────────────────────
# 2. LIGAS SOPORTADAS
# ─────────────────────────────────────────────
LIGAS = {
    "la liga":        {"id": 140, "nombre": "La Liga 🇪🇸"},
    "premier":        {"id": 39,  "nombre": "Premier League 🏴󠁧󠁢󠁥󠁮󠁧󠁿"},
    "champions":      {"id": 2,   "nombre": "Champions League 🌍"},
    "serie a":        {"id": 135, "nombre": "Serie A 🇮🇹"},
    "bundesliga":     {"id": 78,  "nombre": "Bundesliga 🇩🇪"},
    "ligue 1":        {"id": 61,  "nombre": "Ligue 1 🇫🇷"},
    "liga mx":        {"id": 262, "nombre": "Liga MX 🇲🇽"},
    "mls":            {"id": 253, "nombre": "MLS 🇺🇸"},
    "eredivisie":     {"id": 88,  "nombre": "Eredivisie 🇳🇱"},
    "primera division": {"id": 140, "nombre": "La Liga 🇪🇸"},
}

TEMPORADA_ACTUAL = "2024"

API_HEADERS = {
    "x-rapidapi-key":  FOOTBALL_API_KEY,
    "x-rapidapi-host": "v3.football.api-sports.io"
}

# ─────────────────────────────────────────────
# 3. FUNCIONES DE API (con manejo de errores)
# ─────────────────────────────────────────────
def buscar_equipo(nombre_equipo: str) -> tuple[int | None, str | None]:
    """Busca el ID y nombre oficial del equipo en API-Football."""
    try:
        url = "https://v3.football.api-sports.io/teams"
        response = requests.get(
            url,
            headers=API_HEADERS,
            params={"search": nombre_equipo},
            timeout=10
        )
        response.raise_for_status()
        data = response.json().get("response", [])
        if data:
            return data[0]["team"]["id"], data[0]["team"]["name"]
        logger.warning(f"No se encontró equipo: {nombre_equipo}")
        return None, None
    except requests.exceptions.Timeout:
        logger.error(f"Timeout al buscar equipo: {nombre_equipo}")
        return None, None
    except Exception as e:
        logger.error(f"Error buscando equipo '{nombre_equipo}': {e}")
        return None, None


def detectar_liga(equipo_id: int) -> tuple[int, str]:
    """Detecta automáticamente la liga del equipo en la temporada actual."""
    try:
        url = "https://v3.football.api-sports.io/leagues"
        response = requests.get(
            url,
            headers=API_HEADERS,
            params={"team": equipo_id, "season": TEMPORADA_ACTUAL},
            timeout=10
        )
        response.raise_for_status()
        ligas_data = response.json().get("response", [])

        # Ligas prioritarias (más populares primero)
        prioridad = [2, 39, 140, 135, 78, 61, 253, 262, 88]
        for liga_id in prioridad:
            for l in ligas_data:
                if l["league"]["id"] == liga_id:
                    return liga_id, l["league"]["name"]

        # Si no está en las prioritarias, usa la primera disponible
        if ligas_data:
            l = ligas_data[0]
            return l["league"]["id"], l["league"]["name"]
    except Exception as e:
        logger.error(f"Error detectando liga para equipo {equipo_id}: {e}")

    return 140, "La Liga"  # Fallback


def obtener_estadisticas(equipo_id: int, liga_id: int = 140) -> dict | None:
    """Obtiene estadísticas completas: goles, corners, tarjetas."""
    try:
        url = "https://v3.football.api-sports.io/teams/statistics"
        response = requests.get(
            url,
            headers=API_HEADERS,
            params={"team": equipo_id, "league": liga_id, "season": TEMPORADA_ACTUAL},
            timeout=10
        )
        response.raise_for_status()
        stats = response.json().get("response", {})

        if not stats:
            logger.warning(f"Sin estadísticas para equipo {equipo_id} en liga {liga_id}")
            return None

        goles  = stats.get("goals", {})
        faltas = stats.get("cards", {})
        partidos = stats.get("fixtures", {})

        def safe_float(val, default=0.0) -> float:
            try:
                return float(val) if val is not None else default
            except (ValueError, TypeError):
                return default

        jugados_casa  = partidos.get("played", {}).get("home", 1) or 1
        jugados_fuera = partidos.get("played", {}).get("away", 1) or 1

        # Tarjetas totales → promedio por partido
        amarillas = faltas.get("yellow", {})
        rojas     = faltas.get("red", {})
        total_amarillas = sum(
            int(v.get("total", 0) or 0)
            for v in amarillas.values() if isinstance(v, dict)
        )
        total_rojas = sum(
            int(v.get("total", 0) or 0)
            for v in rojas.values() if isinstance(v, dict)
        )
        total_partidos = (jugados_casa + jugados_fuera) or 1

        return {
            "gf_home": safe_float(goles.get("for",     {}).get("average", {}).get("home")),
            "gc_home": safe_float(goles.get("against", {}).get("average", {}).get("home")),
            "gf_away": safe_float(goles.get("for",     {}).get("average", {}).get("away")),
            "gc_away": safe_float(goles.get("against", {}).get("average", {}).get("away")),
            "amarillas_pg": round(total_amarillas / total_partidos, 2),
            "rojas_pg":     round(total_rojas     / total_partidos, 2),
            "partidos_jugados": total_partidos,
        }
    except Exception as e:
        logger.error(f"Error obteniendo estadísticas del equipo {equipo_id}: {e}")
        return None

# ─────────────────────────────────────────────
# 4. MOTOR ESTADÍSTICO (POISSON)
# ─────────────────────────────────────────────
def calcular_probabilidades(stats_local: dict, stats_visit: dict) -> dict:
    """
    Aplica la Distribución de Poisson para calcular:
    - xG por equipo
    - Resultado 1X2
    - Over/Under 2.5
    - BTTS
    - Tarjetas estimadas
    """
    PROMEDIO_LIGA = 1.35  # Media de goles en las principales ligas europeas

    # xG esperados con ajuste de ataque/defensa
    xg_local = max(0.1, (stats_local["gf_home"] / PROMEDIO_LIGA) *
                        (stats_visit["gc_away"] / PROMEDIO_LIGA) * PROMEDIO_LIGA)
    xg_visit = max(0.1, (stats_visit["gf_away"] / PROMEDIO_LIGA) *
                        (stats_local["gc_home"] / PROMEDIO_LIGA) * PROMEDIO_LIGA)

    MAX_GOLES = 7
    prob_local = np.array([poisson.pmf(i, xg_local) for i in range(MAX_GOLES)])
    prob_visit = np.array([poisson.pmf(i, xg_visit) for i in range(MAX_GOLES)])

    # Matriz de resultados (goles_local x goles_visit)
    matriz = np.outer(prob_local, prob_visit)

    prob_victoria_local = float(np.sum(np.tril(matriz, -1)))
    prob_empate         = float(np.trace(matriz))
    prob_victoria_visit = float(np.sum(np.triu(matriz, 1)))

    # Over/Under
    prob_over_15 = float(1 - sum(matriz[i][j] for i in range(MAX_GOLES) for j in range(MAX_GOLES) if i+j < 2))
    prob_over_25 = float(1 - sum(matriz[i][j] for i in range(MAX_GOLES) for j in range(MAX_GOLES) if i+j < 3))
    prob_over_35 = float(1 - sum(matriz[i][j] for i in range(MAX_GOLES) for j in range(MAX_GOLES) if i+j < 4))

    # BTTS
    prob_btts = float((1 - prob_local[0]) * (1 - prob_visit[0]))

    # Resultado más probable
    idx = np.unravel_index(np.argmax(matriz), matriz.shape)
    resultado_mas_probable = f"{idx[0]}-{idx[1]} ({round(float(matriz[idx]) * 100, 1)}%)"

    # Tarjetas estimadas (suma de ambos equipos)
    tarjetas_estimadas = round(
        stats_local.get("amarillas_pg", 0) + stats_visit.get("amarillas_pg", 0), 1
    )

    return {
        "xg_local":               round(xg_local, 2),
        "xg_visitante":           round(xg_visit, 2),
        "prob_victoria_local":    round(prob_victoria_local * 100, 1),
        "prob_empate":            round(prob_empate * 100, 1),
        "prob_victoria_visitante":round(prob_victoria_visit * 100, 1),
        "prob_over_15":           round(prob_over_15 * 100, 1),
        "prob_over_25":           round(prob_over_25 * 100, 1),
        "prob_over_35":           round(prob_over_35 * 100, 1),
        "prob_btts":              round(prob_btts * 100, 1),
        "resultado_mas_probable": resultado_mas_probable,
        "tarjetas_estimadas":     tarjetas_estimadas,
    }

# ─────────────────────────────────────────────
# 5. ANÁLISIS CON GEMINI
# ─────────────────────────────────────────────
def consultar_gemini(estadisticas: dict, local: str, visitante: str) -> str:
    """Genera una conclusión de apuesta basada SOLO en los datos calculados."""
    prompt = f"""
Actúa como un analista deportivo experto en estadísticas. Se han calculado mediante el modelo de Poisson los siguientes datos EXACTOS y REALES del partido {local} vs {visitante}.

DATOS CALCULADOS (NO INVENTES INFORMACIÓN ADICIONAL):
- xG {local}: {estadisticas['xg_local']}
- xG {visitante}: {estadisticas['xg_visitante']}
- Victoria {local}: {estadisticas['prob_victoria_local']}%
- Empate: {estadisticas['prob_empate']}%
- Victoria {visitante}: {estadisticas['prob_victoria_visitante']}%
- Over 1.5: {estadisticas['prob_over_15']}%
- Over 2.5: {estadisticas['prob_over_25']}%
- Over 3.5: {estadisticas['prob_over_35']}%
- Ambos Anotan (BTTS): {estadisticas['prob_btts']}%
- Resultado más probable: {estadisticas['resultado_mas_probable']}
- Tarjetas amarillas estimadas (total): {estadisticas['tarjetas_estimadas']}

TAREA:
Escribe una conclusión de 3-4 líneas identificando los 2 mercados con mayor valor estadístico. 
Sé directo, usa los porcentajes exactos y justifica brevemente cada elección.
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        logger.error(f"Error consultando Gemini: {e}")
        return "⚠️ Error consultando la IA. Los datos estadísticos siguen siendo válidos."

# ─────────────────────────────────────────────
# 6. HANDLERS DEL BOT
# ─────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    texto = (
        "⚽ *Bot de Análisis Estadístico de Fútbol*\n\n"
        "Calculo probabilidades reales con el modelo de *Poisson* "
        "usando datos en vivo de la API, sin inventar nada.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📌 *COMANDOS:*\n\n"
        "`/analizar Real Madrid vs Barcelona`\n"
        "_Detecta la liga automáticamente_\n\n"
        "`/analizar Liverpool vs Arsenal | premier`\n"
        "_Especifica la liga manualmente_\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🏆 *LIGAS DISPONIBLES:*\n"
        "`la liga` · `premier` · `champions`\n"
        "`serie a` · `bundesliga` · `ligue 1`\n"
        "`liga mx` · `mls` · `eredivisie`\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 *MÉTRICAS QUE CALCULO:*\n"
        "• xG por equipo\n"
        "• Resultado 1X2\n"
        "• Over 1.5 / 2.5 / 3.5\n"
        "• Ambos Anotan (BTTS)\n"
        "• Resultado más probable\n"
        "• Tarjetas estimadas\n"
        "• Conclusión IA"
    )
    await message.answer(texto, parse_mode="Markdown")


@dp.message(Command("analizar"))
async def analizar_partido(message: types.Message):
    texto = message.text.replace("/analizar", "").strip()

    # Parsear liga opcional con separador "|"
    liga_id_override  = None
    liga_nombre_extra = ""
    if "|" in texto:
        partes         = texto.split("|", 1)
        texto          = partes[0].strip()
        clave_liga     = partes[1].strip().lower()
        liga_info      = LIGAS.get(clave_liga)
        if liga_info:
            liga_id_override  = liga_info["id"]
            liga_nombre_extra = f" ({liga_info['nombre']})"
        else:
            await message.reply(
                f"⚠️ Liga *{clave_liga}* no reconocida.\n"
                "Usa `/start` para ver las ligas disponibles.",
                parse_mode="Markdown"
            )
            return

    if " vs " not in texto.lower():
        await message.reply(
            "⚠️ Formato incorrecto. Usa:\n"
            "`/analizar Equipo A vs Equipo B`\n"
            "o con liga:\n"
            "`/analizar Equipo A vs Equipo B | premier`",
            parse_mode="Markdown"
        )
        return

    eq_local_str, eq_visit_str = texto.split(" vs ", 1)
    eq_local_str = eq_local_str.strip()
    eq_visit_str = eq_visit_str.strip()

    msg = await message.reply("⏳ *[1/4]* Buscando equipos...", parse_mode="Markdown")

    # Buscar equipos
    id_local,  nombre_local  = buscar_equipo(eq_local_str)
    id_visit,  nombre_visit  = buscar_equipo(eq_visit_str)

    if not id_local or not id_visit:
        equipos_no_encontrados = []
        if not id_local:  equipos_no_encontrados.append(f"*{eq_local_str}*")
        if not id_visit:  equipos_no_encontrados.append(f"*{eq_visit_str}*")
        await msg.edit_text(
            f"❌ No encontré: {' y '.join(equipos_no_encontrados)}.\n"
            "Intenta con el nombre oficial en inglés o español.",
            parse_mode="Markdown"
        )
        return

    # Detectar o usar liga especificada
    await msg.edit_text("⏳ *[2/4]* Detectando liga y obteniendo estadísticas...", parse_mode="Markdown")

    if liga_id_override:
        liga_id    = liga_id_override
        liga_nombre = liga_nombre_extra.strip(" ()")
    else:
        liga_id, liga_nombre = detectar_liga(id_local)

    stats_local = obtener_estadisticas(id_local, liga_id)
    stats_visit = obtener_estadisticas(id_visit, liga_id)

    if not stats_local or not stats_visit:
        await msg.edit_text(
            "❌ Sin datos estadísticos suficientes para esta temporada.\n"
            "Prueba especificando la liga: `/analizar Equipo A vs Equipo B | premier`",
            parse_mode="Markdown"
        )
        return

    # Calcular probabilidades
    await msg.edit_text("⏳ *[3/4]* Calculando modelo de Poisson...", parse_mode="Markdown")
    e = calcular_probabilidades(stats_local, stats_visit)

    texto_stats = (
        f"📊 *ANÁLISIS ESTADÍSTICO — {liga_nombre}*\n"
        f"⚽ *{nombre_local}* vs *{nombre_visit}*\n\n"
        f"🔬 *xG (Goles Esperados)*\n"
        f"  ├ {nombre_local}: `{e['xg_local']}`\n"
        f"  └ {nombre_visit}: `{e['xg_visitante']}`\n\n"
        f"🎯 *Resultado más probable:* `{e['resultado_mas_probable']}`\n\n"
        f"📈 *Resultado 1X2*\n"
        f"  ├ Victoria {nombre_local}: `{e['prob_victoria_local']}%`\n"
        f"  ├ Empate: `{e['prob_empate']}%`\n"
        f"  └ Victoria {nombre_visit}: `{e['prob_victoria_visitante']}%`\n\n"
        f"⚡ *Over/Under*\n"
        f"  ├ Over 1.5: `{e['prob_over_15']}%`\n"
        f"  ├ Over 2.5: `{e['prob_over_25']}%`\n"
        f"  └ Over 3.5: `{e['prob_over_35']}%`\n\n"
        f"🔥 *Ambos Anotan (BTTS):* `{e['prob_btts']}%`\n"
        f"🟨 *Tarjetas estimadas:* `{e['tarjetas_estimadas']}`\n\n"
        f"🤖 *[4/4]* Consultando IA para conclusión..."
    )
    await msg.edit_text(texto_stats, parse_mode="Markdown")

    # Conclusión IA
    conclusion = consultar_gemini(e, nombre_local, nombre_visit)
    texto_final = texto_stats.replace(
        "🤖 *[4/4]* Consultando IA para conclusión...",
        f"━━━━━━━━━━━━━━━━━━━━\n💡 *CONCLUSIÓN IA:*\n{conclusion}"
    )
    await msg.edit_text(texto_final, parse_mode="Markdown")


# ─────────────────────────────────────────────
# 7. PUNTO DE ENTRADA
# ─────────────────────────────────────────────
async def main():
    logger.info("Bot estadístico iniciado correctamente.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
