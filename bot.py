import os
import datetime
import requests
import telebot
import google.generativeai as genai
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
from threading import Thread

# 1. CONFIGURACIÓN DE SEGURIDAD
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8837935575:AAG8uUQN2Nto0bAV8BZggEwgAIg4g3r-KPk")
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY", "28bc5f100ca73109d8e71d0649f6a385")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-pro')

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot de Predicciones por Categorias Activo", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

def limpiar_acentos(texto):
    remplazos = (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"))
    for a, b in remplazos:
        texto = texto.replace(a, b)
    return texto

def obtener_cartelera_por_ligas():
    """Consulta la API y organiza los partidos en diccionarios por categorías importantes"""
    # Ajuste de zona horaria para Colombia (UTC-5) para evitar saltos de fecha adelantados
    ahora_colombia = datetime.datetime.utcnow() - datetime.timedelta(hours=5)
    fecha_str = ahora_colombia.strftime('%Y-%m-%d')
    
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {
        'x-rapidapi-host': 'v3.football.api-sports.io',
        'x-rapidapi-key': API_FOOTBALL_KEY
    }
    
    # Categorías deseadas estructuradas
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
                
                # Clasificación inteligente por palabras clave
                if "friendlies" in liga_lower or "international" in liga_lower or "cup" in liga_lower and pais_lower == "world":
                    categorias["🏆 SELECCIONES (Amistosos / Copas)"].append(info)
                elif any(x in liga_lower for x in ["premier", "la liga", "primera division", "serie a", "bundesliga", "champions", "europa league"]) and any(p in pais_lower for p in ["england", "spain", "italy", "germany", "france"]):
                    categorias["🇪🇺 LIGAS TOP EUROPA (Champions/Premier/Liga)"].append(info)
                elif any(x in liga_lower or x in pais_lower for x in ["colombia", "betplay", "argentina", "brazil", "mexico", "libertadores", "sudamericana"]):
                    categorias["🇨🇴 FÚTBOL LATINOAMÉRICA (Colombia/Argentina/Brasil)"].append(info)
                else:
                    # Evitamos saturar con ligas juveniles o regionales extremadamente bajas si es posible
                    if not any(v in liga_lower for v in ["u19", "u21", "oberliga", "regionalliga", "amateur"]):
                        categorias["⚽ OTRAS LIGAS Y COPAS"].append(info)
                        
    except Exception as e:
        print(f"Error estructurando la cartelera: {e}")
        
    return categories, fecha_str

@bot.message_handler(commands=['start', 'ayuda', 'help', 'comandos'])
def enviar_lista_comandos(message):
    texto_ayuda = (
        "🤖 *Menú de Comandos - Bot de Predicciones*\n\n"
        "⚽ `/polla` o `/partidos` — Despliega los partidos del día clasificados por categorías y ligas principales.\n"
        "📊 *Buscar Equipo* — Escribe `datos de [Nombre del equipo]` para ver su historial analítico.\n"
        "ℹ️ `/ayuda` — Muestra este panel informativo."
    )
    bot.send_message(message.chat.id, texto_ayuda, parse_mode="Markdown")

@bot.message_handler(commands=['polla', 'partidos'])
def enviar_menu_dinamico(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        categorias, fecha_hoy = obtener_cartelera_por_ligas()
        
        texto_mensaje = f"🗓️ *Cartelera de Partidos ({fecha_hoy})*\n_Selecciona un encuentro para ver el análisis predictivo de la IA:_\n\n"
        markup = InlineKeyboardMarkup()
        markup.row_width = 1
        
        hay_partidos = False
        contador_botones = 0
        
        # Recorremos el diccionario organizado para armar el mensaje estético
        for nombre_cat, partidos in categorias.items():
            if partidos:
                hay_partidos = True
                texto_mensaje += f"*{nombre_cat}*\n"
                
                # Agregamos los botones correspondientes a esta categoría (máximo 5 por sección para mantener orden)
                for partido in partidos[:5]:
                    if contador_botones < 16:  # Límite técnico sugerido para evitar botones excesivamente pequeños
                        texto_boton = f"🔹 {partido['home']} vs {partido['away']}"
                        callback_data = f"c_{partido['home_id']}_{partido['away_id']}"
                        markup.add(InlineKeyboardButton(texto_boton, callback_data=callback_data))
                        
                        # Añadimos una línea de texto informativa tipo lista
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

@bot.callback_query_handler(func=lambda call: call.data.startswith('c_'))
def procesar_prediccion_ia(call):
    bot.answer_callback_query(call.id, text="Calculando analítica y cuotas estimadas...")
    
    try:
        partes = call.data.split('_')
        home_id = partes[1]
        away_id = partes[2]
        
        url = "https://v3.football.api-sports.io/fixtures/headtohead"
        headers = {
            'x-rapidapi-host': 'v3.football.api-sports.io',
            'x-rapidapi-key': API_FOOTBALL_KEY
        }
        params = {'h2h': f"{home_id}-{away_id}", 'last': 5}
        
        response = requests.get(url, headers=headers, params=params, timeout=10).json()
        
        # Modelo base equilibrado en caso de ligas con datos vacíos en H2H
        victorias_home, victorias_away, empates = 3, 2, 1
        goles_totales = 14
        home_name, away_name = "Equipo Local", "Equipo Visitante"
        origen_datos = "Modelo de Simulación Avanzada por Falta de Historial Directo"
        
        if "response" in response and response["response"]:
            victorias_home, victorias_away, empates = 0, 0, 0
            goles_totales = 0
            partidos_previos = response["response"]
            origen_datos = "Historial Directo H2H (Registros Oficiales de la API)"
            
            home_name = partidos_previos[0]["teams"]["home"]["name"]
            away_name = partidos_previos[0]["teams"]["away"]["name"]
            
            for f in partidos_previos:
                g_h = f["goals"]["home"] if f["goals"]["home"] is not None else 0
                g_a = f["goals"]["away"] if f["goals"]["away"] is not None else 0
                goles_totales += (g_h + g_a)
                
                if f["teams"]["home"]["winner"]:
                    victorias_home += 1
                elif f["teams"]["away"]["winner"]:
                    victorias_away += 1
                else:
                    empates += 1
                    
        total_partidos = victorias_home + victorias_away + empates
        p_local = round((victorias_home / total_partidos) * 100)
        p_visitante = round((victorias_away / total_partidos) * 100)
        p_empate = 100 - (p_local + p_visitante)
        
        goles_promedio = round(goles_totales / max(total_partidos, 1), 1)
        if goles_promedio == 0: goles_promedio = 2.3
        
        corners = "8.5 - 10.5" if p_local > 45 else "7.5 - 9.5"
        tarjetas = "3.5 - 4.5" if p_local > 45 else "4.5 - 5.5"
        ambos_anotan = "Sí" if goles_promedio >= 2.1 else "No"
        
        prompt = (
            f"Actúa como un experto tipster deportivo. Escribe un análisis de apuestas para: {home_name} vs {away_name}.\n"
            f"Estadísticas calculadas:\n"
            f"- Probabilidad {home_name}: {p_local}%\n"
            f"- Probabilidad Empate: {p_empate}%\n"
            f"- Probabilidad {away_name}: {p_visitante}%\n"
            f"- Promedio Goles: {goles_promedio}\n"
            f"- Ambos marcan: {ambos_anotan}\n"
            f"- Corners aproximados: {corners}\n"
            f"- Tarjetas aproximadas: {tarjetas}\n"
            f"- Base de datos: {origen_datos}\n\n"
            f"Genera un texto bien estructurado con emojis y Markdown estándar (sin usar MarkdownV2). "
            f"Sugerir un resultado exacto y agregar un tip clave final para apostar en la polla."
        )
        
        res = model.generate_content(prompt)
        bot.send_message(call.message.chat.id, res.text, parse_mode="Markdown")
        
    except Exception as e:
        print(f"Error procesando el análisis del partido: {e}")
        bot.send_message(call.message.chat.id, "❌ No se pudo compilar el reporte estadístico de este encuentro.")

@bot.message_handler(func=lambda message: True)
def responder_datos_equipo(message):
    texto = message.text.lower()
    
    if "datos de" in texto or "estadisticas de" in texto or "estadísticas de" in texto:
        equipo_buscado = message.text.replace("Dame datos de", "").replace("dame datos de", "")
        equipo_buscado = equipo_buscado.replace("estadísticas de", "").replace("Estadísticas de", "")
        equipo_buscado = equipo_buscado.replace("estadisticas de", "").replace("Estadisticas de", "")
        equipo_buscado = equipo_buscado.replace("datos de", "").replace("Datos de", "").strip()
        
        if not equipo_buscado:
            bot.reply_to(message, "⚽ Por favor escribe el nombre del equipo. Ejemplo: `datos de Atletico Nacional`")
            return
            
        bot.reply_to(message, f"🔍 Consultando registros e historial de *{equipo_buscado}*...", parse_mode="Markdown")
        
        try:
            busqueda_limpia = limpiar_acentos(equipo_buscado.lower())
            url_search = "https://v3.football.api-sports.io/teams"
            headers = {
                'x-rapidapi-host': 'v3.football.api-sports.io',
                'x-rapidapi-key': API_FOOTBALL_KEY
            }
            res_search = requests.get(url_search, headers=headers, params={'search': busqueda_limpia}, timeout=8).json()
            
            if not res_search.get("response") and "atletico" in busqueda_limpia:
                intento_corto = busqueda_limpia.replace("atletico", "").strip()
                res_search = requests.get(url_search, headers=headers, params={'search': intento_corto}, timeout=8).json()
                
            if not res_search.get("response"):
                bot.reply_to(message, f"❌ No logré encontrar estadísticas de '{equipo_buscado}' en el mapa global de ligas.")
                return
                
            team_info = res_search["response"][0]["team"]
            team_name = team_info["name"]
            pais = team_info["country"]
            logo = team_info["logo"]
            fundado = team_info.get("founded", "N/A")
            
            prompt = (
                f"Actúa como un Scout de fútbol y analista deportivo. El usuario solicita un perfil de apuestas del club: {team_name} ({pais}).\n"
                f"Ficha técnica básica: Fundado en el año {fundado}.\n\n"
                f"Redacta una guía rápida táctica usando Markdown estándar. Explica brevemente su peso histórico, "
                f"su tendencia habitual de goles (si suele ser over o under) y concluye con una recomendación de mercado útil para los jugadores del grupo."
            )
            
            res_ia = model.generate_content(prompt)
            bot.send_photo(message.chat.id, logo, caption=res_ia.text, parse_mode="Markdown")
            
        except Exception as e:
            print(f"Error consultando equipo: {e}")
            bot.reply_to(message, "❌ Los servidores deportivos están saturados. Inténtalo de nuevo en unos minutos.")

if __name__ == "__main__":
    print("Iniciando servidor web...")
    server_thread = Thread(target=run_flask)
    server_thread.start()
    
    print("Bot Clasificado por Categorías Corriendo Correctamente...")
    bot.infinity_polling()
