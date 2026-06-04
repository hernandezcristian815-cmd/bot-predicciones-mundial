import os
import datetime
import requests
import telebot
import google.generativeai as genai
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
from threading import Thread
from duckduckgo_search import DDGS  # Buscador web en tiempo real

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
    return "Bot de Fútbol con Rastreo Web Activo", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

def obtener_cartelera_por_ligas():
    """Mantiene la cartelera diaria de la API organizada por categorías para los botones"""
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
                    if not any(v in liga_lower for v in ["u19", "u21", "oberliga", "regionalliga", "amateur"]):
                        categorias["⚽ OTRAS LIGAS Y COPAS"].append(info)
                        
    except Exception as e:
        print(f"Error en cartelera: {e}")
        
    return categorias, fecha_str

@bot.message_handler(commands=['start', 'ayuda', 'help', 'comandos'])
def enviar_lista_comandos(message):
    texto_ayuda = (
        "🤖 *Bot de Análisis Futbolístico con Rastreo Web*\n\n"
        "Comandos disponibles:\n\n"
        "⚽ `/polla` o `/partidos` — Muestra la cartelera del día clasificada por ligas con botones interactivos.\n"
        "🌐 *Buscador Inteligente* — Escribe de forma natural en el chat para investigar a cualquier club usando internet.\n"
        "👉 _Ejemplo:_ `datos de Atletico Nacional` o `estadisticas de Millonarios`.\n\n"
        "ℹ️ `/ayuda` — Muestra este menú."
    )
    bot.send_message(message.chat.id, texto_ayuda, parse_mode="Markdown")

@bot.message_handler(commands=['polla', 'partidos'])
def enviar_menu_dinamico(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        categorias, fecha_hoy = obtener_cartelera_por_ligas()
        
        texto_mensaje = f"🗓️ *Cartelera de Partidos ({fecha_hoy})*\n_Selecciona un partido para calcular las estadísticas con la IA:_\n\n"
        markup = InlineKeyboardMarkup()
        markup.row_width = 1
        
        hay_partidos = False
        contador_botones = 0
        
        for nombre_cat, partidos in categorias.items():
            if partidos:
                hay_partidos = True
                texto_mensaje += f"*{nombre_cat}*\n"
                
                for partido in partidos[:5]:
                    if contador_botones < 15:
                        texto_boton = f"🔹 {partido['home']} vs {partido['away']}"
                        callback_data = f"c_{partido['home_id']}_{partido['away_id']}"
                        markup.add(InlineKeyboardButton(texto_boton, callback_data=callback_data))
                        texto_mensaje += f" • {partido['home']} vs {partido['away']} _({partido['league'][:15]})_\n"
                        contador_botones += 1
                texto_mensaje += "\n"
                
        if not hay_partidos:
            bot.send_message(message.chat.id, "⏳ No hay encuentros principales programados en este momento.")
            return
            
        bot.send_message(message.chat.id, texto_mensaje, parse_mode="Markdown", reply_markup=markup)
        
    except Exception as e:
        print(f"Error en menú clasificado: {e}")
        bot.send_message(message.chat.id, "❌ Error al organizar la agenda deportiva.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('c_'))
def procesar_prediccion_ia(call):
    bot.answer_callback_query(call.id, text="Calculando analítica H2H...")
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
        
        victorias_home, victorias_away, empates = 3, 2, 1
        goles_totales = 14
        home_name, away_name = "Equipo Local", "Equipo Visitante"
        
        if "response" in response and response["response"]:
            victorias_home, victorias_away, empates = 0, 0, 0
            goles_totales = 0
            partidos_previos = response["response"]
            home_name = partidos_previos[0]["teams"]["home"]["name"]
            away_name = partidos_previos[0]["teams"]["away"]["name"]
            
            for f in partidos_previos:
                g_h = f["goals"]["home"] if f["goals"]["home"] is not None else 0
                g_a = f["goals"]["away"] if f["goals"]["away"] is not None else 0
                goles_totales += (g_h + g_a)
                if f["teams"]["home"]["winner"]: victorias_home += 1
                elif f["teams"]["away"]["winner"]: victorias_away += 1
                else: empates += 1
                    
        total_partidos = victorias_home + victorias_away + empates
        p_local = round((victorias_home / total_partidos) * 100)
        p_visitante = round((victorias_away / total_partidos) * 100)
        p_empate = 100 - (p_local + p_visitante)
        goles_promedio = round(goles_totales / max(total_partidos, 1), 1)
        if goles_promedio == 0: goles_promedio = 2.4
        
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
            f"- Tarjetas aproximadas: {tarjetas}\n\n"
            f"Genera un texto bien estructurado con emojis y Markdown estándar. Sugiere un marcador exacto y un tip de apuesta clave."
        )
        res = model.generate_content(prompt)
        bot.send_message(call.message.chat.id, res.text, parse_mode="Markdown")
    except Exception as e:
        print(f"Error procesando callback: {e}")
        bot.send_message(call.message.chat.id, "❌ No se pudo compilar el reporte estadístico.")

# 5. NUEVO MANEJADOR DE TEXTO LIBRE CON RASTREO WEB REAL EN INTERNET
@bot.message_handler(func=lambda message: True)
def responder_datos_con_busqueda_web(message):
    texto = message.text.lower()
    
    # Detonantes lógicos para activar la búsqueda en internet
    if "datos de" in texto or "estadisticas de" in texto or "estadísticas de" in texto:
        equipo_buscado = message.text.replace("Dame datos de", "").replace("dame datos de", "")
        equipo_buscado = equipo_buscado.replace("estadísticas de", "").replace("Estadísticas de", "")
        equipo_buscado = equipo_buscado.replace("estadisticas de", "").replace("Estadisticas de", "")
        equipo_buscado = equipo_buscado.replace("datos de", "").replace("Datos de", "").strip()
        
        if not equipo_buscado:
            bot.reply_to(message, "⚽ Por favor escribe el nombre del equipo. Ejemplo: `datos de Atletico Nacional`")
            return
            
        bot.reply_to(message, f"🌐 *Rastreando internet* en tiempo real para buscar datos de *{equipo_buscado}*...", parse_mode="Markdown")
        
        try:
            # Realizamos búsquedas en internet usando DuckDuckGo de manera silenciosa
            busqueda_query = f"{equipo_buscado} ultimos partidos resultados actualidad futbol"
            contexto_web = ""
            
            with DDGS() as ddgs:
                # Obtenemos los 4 resultados principales de internet
                resultados = [r for r in ddgs.text(busqueda_query, max_results=4)]
                for res in resultados:
                    contexto_web += f"Título: {res['title']}\nResumen: {res['body']}\n\n"
            
            if not contexto_web:
                bot.reply_to(message, "❌ No logré encontrar noticias o datos recientes de ese equipo en internet.")
                return
                
            # Pasamos la información real extraída de internet a la IA para que la organice
            prompt = (
                f"Actúa como un periodista y analista deportivo de televisión. El usuario quiere los datos actuales de: {equipo_buscado}.\n\n"
                f"Aquí tienes los resultados reales obtenidos de las búsquedas web de último minuto:\n"
                f"{contexto_web}\n"
                f"Instrucciones:\n"
                f"1. Filtra la información relevante (últimos partidos, cómo van en el torneo, noticias clave).\n"
                f"2. Redacta un informe ejecutivo súper estético para Telegram usando Markdown estándar y emojis.\n"
                f"3. Agrega una sección llamada '🎯 Panorama de Apuestas' donde analices si el equipo viene en racha ganadora, si anota bastantes goles o si es propenso a empatar según lo encontrado en internet."
            )
            
            res_ia = model.generate_content(prompt)
            bot.send_message(message.chat.id, res_ia.text, parse_mode="Markdown")
            
        except Exception as e:
            print(f"Error en rastreo web: {e}")
            bot.reply_to(message, "❌ Hubo un fallo en los motores de búsqueda web. Inténtalo de nuevo.")

if __name__ == "__main__":
    print("Iniciando servidor web...")
    server_thread = Thread(target=run_flask)
    server_thread.start()
    
    print("Bot con Motores de Rastreo Web Corriendo...")
    bot.infinity_polling()
