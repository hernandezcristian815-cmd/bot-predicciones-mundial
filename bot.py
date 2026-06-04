import os
import datetime
import requests
import telebot
import google.generativeai as genai
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
from threading import Thread
from duckduckgo_search import DDGS

# 1. CONFIGURACIÓN DE SEGURIDAD (Cargando desde el Entorno de Render)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Inicialización estándar para evitar errores de metaclases en entornos Python modernos
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot de Predicciones por Categorías Activo", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

def obtener_cartelera_por_ligas():
    """Consulta la API y organiza los partidos en diccionarios por categorías importantes"""
    ahora_colombia = datetime.datetime.utcnow() - datetime.timedelta(hours=5)
    fecha_str = ahora_colombia.strftime('%Y-%m-%d')
    
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {
        'x-rapidapi-host': 'v3.football.api-sports.io',
        'x-rapidapi-key': API_FOOTBALL_KEY
    }
    
    categorias = {
        "🏆 SELECCIONES (Amistosos / Copas)": [],
        "🇪🇺 LIGAS TOP EUROPA (Champions/Premier/Liga)": [],
        "🇨🇴 FÚTBOL LATINOAMÉRICA (Colombia/Argentina/Brasil)": [],
        "⚽ OTRAS LIGAS Y COPAS": []
    }
    
    try:
        response = requests.get(url, headers=headers, params={'date': fecha_str}, timeout=12).json()
        if "response" in response and response["response"]:
            for item in response["response"]:
                info = {
                    "home": item["teams"]["home"]["name"],
                    "home_id": item["teams"]["home"]["id"],
                    "away": item["teams"]["away"]["name"],
                    "away_id": item["teams"]["away"]["id"],
                    "league": item["league"]["name"],
                    "pais": item["league"]["country"]
                }
                
                liga_lower = info["league"].lower()
                pais_lower = info["pais"].lower()
                
                if "friendlies" in liga_lower or "international" in liga_lower or "cup" in liga_lower and pais_lower == "world":
                    categorias["🏆 SELECCIONES (Amistosos / Copas)"].append(info)
                elif any(x in liga_lower for x in ["premier", "la liga", "primera division", "serie a", "bundesliga", "champions", "europa league"]) and any(p in pais_lower for p in ["england", "spain", "italy", "germany", "france"]):
                    categorias["🇪🇺 LIGAS TOP EUROPA (Champions/Premier/Liga)"].append(info)
                elif any(x in liga_lower or x in pais_lower for x in ["colombia", "betplay", "argentina", "brazil", "mexico", "libertadores", "sudamericana"]):
                    categorias["🇨🇴 FÚTBOL LATINOAMÉRICA (Colombia/Argentina/Brasil)"].append(info)
                else:
                    if not any(v in liga_lower for v in ["u19", "u21", "oberliga", "regionalliga", "amateur", "reserves"]):
                        categorias["⚽ OTRAS LIGAS Y COPAS"].append(info)
                        
    except Exception as e:
        print(f"Error estructurando la cartelera: {e}")
        
    return categorias, fecha_str

@bot.message_handler(commands=['start', 'ayuda', 'help', 'comandos'])
def enviar_lista_comandos(message):
    texto_ayuda = (
        "🤖 *Menú de Comandos - Bot de Predicciones*\n\n"
        "⚽ `/polla` o `/partidos` — Despliega los partidos del día clasificados por categorías.\n"
        "📊 *Buscar Equipo* — Escribe `datos de [Nombre del equipo]` para ver su historial analítico con rastreo web.\n"
        "ℹ️ `/ayuda` — Muestra este panel informativo."
    )
    bot.send_message(message.chat.id, texto_ayuda, parse_mode="Markdown")

@bot.message_handler(commands=['polla', 'partidos'])
def enviar_menu_dinamico(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        categorias, fecha_hoy = obtener_cartelera_por_ligas()
        
        texto_mensaje = f"🗓️ *Cartelera de Partidos ({fecha_hoy})*\n_Selecciona un encuentro para ver el análisis predictivo profundo:_\n\n"
        markup = InlineKeyboardMarkup()
        markup.row_width = 1
        
        hay_partidos = False
        contador_botones = 0
        
        for nombre_cat, partidos in categorias.items():
            if partidos:
                hay_partidos = True
                texto_mensaje += f"*{nombre_cat}*\n"
                
                for partido in partidos[:4]:
                    if contador_botones < 12:
                        texto_boton = f"🔹 {partid['home']} vs {partid['away']}"
                        callback_data = f"c_{partid['home_id']}_{partid['away_id']}"
                        markup.add(InlineKeyboardButton(texto_boton, callback_data=callback_data))
                        
                        texto_mensaje += f" • {partido['home']} vs {partido['away']} _({partido['league'][:15]})_\n"
                        contador_botones += 1
                texto_mensaje += "\n"
                
        if not hay_partidos:
            bot.send_message(message.chat.id, "⏳ Por el momento no se reportan encuentros comerciales importantes en las listas principales para hoy.")
            return
            
        bot.send_message(message.chat.id, texto_mensaje, parse_mode="Markdown", reply_markup=markup)
        
    except Exception as e:
        print(f"Error al enviar menú clasificado: {e}")
        bot.send_message(message.chat.id, "❌ Ocurrió un error al organizar la agenda deportiva.")


# 2. TU BLOQUE DE ANÁLISIS OPTIMIZADO Y BLINDADO CONTRA CAÍDAS
@bot.callback_query_handler(func=lambda call: call.data.startswith('c_'))
def procesar_prediccion_ia(call):
    bot.answer_callback_query(call.id, text="Analizando partido con Big Data...")

    try:
        partes = call.data.split('_')
        home_id = partes[1]
        away_id = partes[2]

        headers = {
            'x-rapidapi-host': 'v3.football.api-sports.io',
            'x-rapidapi-key': API_FOOTBALL_KEY
        }

        # Consultas completas de tu bloque
        h2h = requests.get(
            "https://v3.football.api-sports.io/fixtures/headtohead",
            headers=headers,
            params={"h2h": f"{home_id}-{away_id}", "last": 5},
            timeout=10
        ).json()

        local = requests.get(
            "https://v3.football.api-sports.io/fixtures",
            headers=headers,
            params={"team": home_id, "last": 10},
            timeout=10
        ).json()

        visitante = requests.get(
            "https://v3.football.api-sports.io/fixtures",
            headers=headers,
            params={"team": away_id, "last": 10},
            timeout=10
        ).json()

        # Rescate de nombres dinámico (Evita que tire IndexError si el h2h viene vacío)
        home_name = "Equipo Local"
        away_name = "Equipo Visitante"

        if h2h.get("response") and len(h2h["response"]) > 0:
            home_name = h2h["response"][0]["teams"]["home"]["name"]
            away_name = h2h["response"][0]["teams"]["away"]["name"]
        else:
            if local.get("response") and len(local["response"]) > 0:
                fixture_local = local["response"][0]["teams"]
                home_name = fixture_local["home"]["name"] if str(fixture_local["home"]["id"]) == str(home_id) else fixture_local["away"]["name"]
            if visitante.get("response") and len(visitante["response"]) > 0:
                fixture_vis = visitante["response"][0]["teams"]
                away_name = fixture_vis["home"]["name"] if str(fixture_vis["home"]["id"]) == str(away_id) else fixture_vis["away"]["name"]

        # Formateador interno para limpiar la basura del JSON y no saturar de tokens a Gemini
        def purificar_contexto(json_data):
            if not json_data.get("response"): 
                return "Sin registros históricos directos previos en la base de datos."
            resumen = []
            for f in json_data["response"]:
                g_h = f.get("goals", {}).get("home", 0)
                g_a = f.get("goals", {}).get("away", 0)
                resumen.append(f"{f['teams']['home']['name']} {g_h} - {g_a} {f['teams']['away']['name']} ({f['fixture']['date'][:10]})")
            return "\n".join(resumen)

        h2h_txt = purificar_contexto(h2h)
        local_txt = purificar_contexto(local)
        visitante_txt = purificar_contexto(visitante)

        prompt = f"""
Analiza profesionalmente este partido basándote en los datos estadísticos reales provistos.

PARTIDO:
{home_name} vs {away_name}

ENFRENTAMIENTOS DIRECTOS (H2H):
{h2h_txt}

ÚLTIMOS 10 PARTIDOS DEL LOCAL ({home_name}):
{local_txt}

ÚLTIMOS 10 PARTIDOS DEL VISITANTE ({away_name}):
{visitante_txt}

Genera un reporte perfectamente formateado con el siguiente orden exacto (usa emojis y negritas):

📊 **Probabilidad de victoria local:** [X]%
📊 **Probabilidad de empate:** [X]%
📊 **Probabilidad de victoria visitante:** [X]%

⚽ **Ambos anotan:** [Sí/No]
🔥 **Over/Under 2.5 goles:** [Detalle]
🎯 **Marcador exacto probable:** [X - X]
💰 **Mejor apuesta / Pick Recomendado:** [Detalle del mercado]
📈 **Nivel de confianza:** [Bajo / Medio / Alto]

Usa exclusivamente Markdown estándar y emojis atractivos para Telegram.
"""

        respuesta = model.generate_content(prompt)

        bot.send_message(
            call.message.chat.id,
            respuesta.text,
            parse_mode="Markdown"
        )

    except Exception as e:
        print(f"Error procesando analítica completa: {e}")
        bot.send_message(
            call.message.chat.id,
            "❌ No pude analizar el partido debido a inconsistencias en las planillas de los equipos."
        )


# 3. BUSCADOR INTEGRAL EN INTERNET (TEXTO LIBRE)
@bot.message_handler(func=lambda message: True)
def responder_datos_con_busqueda_web(message):
    texto = message.text.lower()
    
    if "datos de" in texto or "estadisticas de" in texto or "estadísticas de" in texto:
        equipo_buscado = message.text.replace("Dame datos de", "").replace("dame datos de", "")
        equipo_buscado = equipo_buscado.replace("estadísticas de", "").replace("Estadísticas de", "")
        equipo_buscado = equipo_buscado.replace("estadisticas de", "").replace("Estadisticas de", "")
        equipo_buscado = equipo_buscado.replace("datos de", "").replace("Datos de", "").strip()
        
        if not equipo_buscado:
            bot.reply_to(message, "⚽ Por favor escribe el nombre del equipo. Ejemplo: `datos de Atletico Nacional`")
            return
            
        bot.reply_to(message, f"🌐 *Rastreando la web* en tiempo real para buscar datos de *{equipo_buscado}*...", parse_mode="Markdown")
        
        try:
            busqueda_query = f"{equipo_buscado} ultimos partidos resultados actualidad futbol"
            contexto_web = ""
            
            with DDGS() as ddgs:
                resultados = [r for r in ddgs.text(busqueda_query, max_results=3)]
                for res in resultados:
                    contexto_web += f"Título: {res['title']}\nResumen: {res['body']}\n\n"
            
            if not contexto_web:
                bot.reply_to(message, "❌ No logré encontrar noticias o datos recientes de ese equipo en internet.")
                return
                
            prompt = (
                f"Actúa como un periodista y analista deportivo. El usuario quiere los datos actuales de: {equipo_buscado}.\n\n"
                f"Aquí tienes los resultados reales obtenidos de internet:\n"
                f"{contexto_web}\n"
                f"Redacta un informe ejecutivo estético para Telegram usando Markdown y emojis. "
                f"Agrega una sección llamada '🎯 Panorama de Apuestas' con tendencias de valor."
            )
            
            res_ia = model.generate_content(prompt)
            bot.send_message(message.chat.id, res_ia.text, parse_mode="Markdown")
            
        except Exception as e:
            print(f"Error en rastreo web: {e}")
            bot.reply_to(message, "❌ Hubo un fallo en los motores de búsqueda web.")

if __name__ == "__main__":
    server_thread = Thread(target=run_flask)
    server_thread.start()
    
    print("Bot Unificado y Blindado Corriendo Correctamente...")
    bot.infinity_polling()
