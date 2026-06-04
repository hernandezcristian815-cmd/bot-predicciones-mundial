import os
import datetime
import telebot
import requests
import google.generativeai as genai
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
from threading import Thread

# 1. CONFIGURACIÓN DE SEGURIDAD (Variables de Entorno)
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
    return "Bot Analítico de Apuestas Global Operando", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

def obtener_cartelera_inteligente(fecha_str):
    """Trae todos los partidos del calendario y prioriza los torneos comerciales"""
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {
        'x-rapidapi-host': 'v3.football.api-sports.io',
        'x-rapidapi-key': API_FOOTBALL_KEY
    }
    params = {'date': fecha_str}
    partidos_ordenados = []
    
    # Filtro visual para priorizar ligas y selecciones importantes arriba
    prioritarias = ["friendlies", "international", "cup", "champions", "euro", "america", "premier", "division", "liga", "serie a"]
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=12).json()
        if "response" in response and response["response"]:
            partidos_alta = []
            partidos_baja = []
            
            for item in response["response"]:
                info_partido = {
                    "id": item["fixture"]["id"],
                    "home": item["teams"]["home"]["name"],
                    "home_id": item["teams"]["home"]["id"],
                    "away": item["teams"]["away"]["name"],
                    "away_id": item["teams"]["away"]["id"],
                    "league": item["league"]["name"]
                }
                
                nombre_liga = item["league"]["name"].lower()
                if any(p in nombre_liga for p in prioritarias):
                    partidos_alta.append(info_partido)
                else:
                    partidos_baja.append(info_partido)
            
            partidos_ordenados = partidos_alta + partidos_baja
            
    except Exception as e:
        print(f"Error consultando cartelera: {e}")
        
    return partidos_ordenados

@bot.message_handler(commands=['start', 'ayuda', 'help'])
def enviar_lista_comandos(message):
    texto_ayuda = (
        "🤖 *Centro de Análisis Estadístico Real*\n\n"
        "Comandos disponibles:\n"
        "⚽ `/polla` o `/partidos` \- Muestra los partidos del día ordenados por importancia mundial\.\n"
        "ℹ️ `/ayuda` \- Muestra este menú de asistencia\."
    )
    bot.send_message(message.chat.id, texto_ayuda, parse_mode="MarkdownV2")

@bot.message_handler(commands=['polla', 'partidos'])
def enviar_menu_dinamico(message):
    bot.send_message(message.chat.id, "📊 Conectando con la API... Analizando partidos del calendario global...")
    
    ahora = datetime.datetime.now()
    fecha_hoy = ahora.strftime('%Y-%m-%d')
    fecha_manana = (ahora + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    
    lista_partidos = obtener_cartelera_inteligente(fecha_hoy)
    titulo_menu = "⚽ *¡Partidos del Calendario de HOY\!*"
    
    if not lista_partidos:
        lista_partidos = obtener_cartelera_inteligente(fecha_manana)
        titulo_menu = "🗓️ *Partidos del Calendario de MAÑANA\!*"
        
    if not lista_partidos:
        bot.send_message(message.chat.id, "⏳ No se detectan partidos programados en la API para hoy ni mañana.")
        return
        
    markup = InlineKeyboardMarkup()
    markup.row_width = 1
    
    # Mostramos los primeros 18 encuentros (los más relevantes/internacionales quedan arriba)
    for i, partido in enumerate(lista_partidos[:18]):
        texto_boton = f"{partido['home']} vs. {partido['away']} ({partido['league'][:14]})"
        home_c = partido['home'][:15].replace("_", "").replace(" ", "")
        away_c = partido['away'][:15].replace("_", "").replace(" ", "")
        callback_data = f"c_{partido['home_id']}_{partido['away_id']}_{home_c}_{away_c}"[:64]
        
        markup.add(InlineKeyboardButton(texto_boton, callback_data=callback_data))
        
    bot.send_message(message.chat.id, f"{titulo_menu}\nSelecciona un encuentro para procesar estadísticas de partidos jugados (H2H):", parse_mode="MarkdownV2", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('c_'))
def procesar_prediccion_ia(call):
    bot.answer_callback_query(call.id, text="Consultando historial real H2H en la API...")
    
    try:
        partes = call.data.split('_')
        home_id = partes[1]
        away_id = partes[2]
        home_name = partes[3] if len(partes) > 3 else "Local"
        away_name = partes[4] if len(partes) > 4 else "Visitante"
        
        # CONSULTA DIRECTA DE PARTIDOS JUGADOS CARA A CARA (H2H)
        url = "https://v3.football.api-sports.io/fixtures/headtohead"
        headers = {
            'x-rapidapi-host': 'v3.football.api-sports.io',
            'x-rapidapi-key': API_FOOTBALL_KEY
        }
        params = {'h2h': f"{home_id}-{away_id}", 'last': 5}
        
        response = requests.get(url, headers=headers, params=params, timeout=10).json()
        
        # Modelo matemático base por si son selecciones que nunca han jugado antes entre sí (Historial limpio)
        victorias_home, victorias_away, empates = 2, 2, 1
        goles_totales = 12
        hubo_datos_reales = False
        
        # Si la API tiene registros de sus partidos jugados, extraemos los datos numéricos puros
        if "response" in response and response["response"]:
            victorias_home, victorias_away, empates = 0, 0, 0
            goles_totales = 0
            partidos_previos = response["response"]
            hubo_datos_reales = True
            
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
                    
        # --- PROCESAMIENTO MATEMÁTICO REAL EN TU SERVIDOR ---
        total_partidos = victorias_home + victorias_away + empates
        p_local = round((victorias_home / total_partidos) * 100)
        p_visitante = round((victorias_away / total_partidos) * 100)
        p_empate = 100 - (p_local + p_visitante)
        
        goles_promedio = round(goles_totales / max(total_partidos, 1), 1)
        if goles_promedio == 0: goles_promedio = 2.4
        
        # Fórmulas lógicas predictivas para mercados secundarios basándonos en el rendimiento
        if p_local > 45:
            corners_estimados = "8.5 - 10.5"
            tarjetas_estimadas = "3.5 - 4.5"
            control_juego = home_name
        elif p_visitante > 45:
            corners_estimados = "8.0 - 10.0"
            tarjetas_estimadas = "4.0 - 5.0"
            control_juego = away_name
        else:
            corners_estimados = "7.5 - 9.5"
            tarjetas_estimadas = "4.5 - 5.5"
            control_juego = "Medio campo disputado"
            
        ambos_anotan = "Sí" if goles_promedio >= 2.1 else "No"
        origen_datos = "Historial directo H2H (API)" if hubo_datos_reales else "Algoritmo de rendimiento estimado"
        
        # Pasamos los datos puros y exactos calculados a la IA para que redacte el informe formal
        prompt = (
            f"Escribe un reporte premium de analítica deportiva para el partido de fútbol: {home_name} vs {away_name}.\n"
            f"Es obligatorio que uses estos datos matemáticos exactos en tu texto para que sea real:\n"
            f"- Probabilidad de Victoria de {home_name}: {p_local}%\n"
            f"- Probabilidad de Empate: {p_empate}%\n"
            f"- Probabilidad de Victoria de {away_name}: {p_visitante}%\n"
            f"- Promedio de goles por partido: {goles_promedio}\n"
            f"- Ambos equipos anotan: {ambos_anotan}\n"
            f"- Córners totales estimados: {corners_estimados}\n"
            f"- Tarjetas totales estimadas: {tarjetas_estimadas}\n"
            f"- Mayor posesión/control esperado: {control_juego}\n"
            f"- Base de cálculo: {origen_datos}\n\n"
            f"Estructura la información de manera muy organizada usando Markdown para Telegram con títulos en negrita y emojis. "
            f"Sujeta tus recomendaciones a estos números y propón un marcador exacto lógico (ej. 2-1 o 1-1) acompañado de un Tip de Apuesta clave."
        )
        
        res = model.generate_content(prompt)
        bot.send_message(call.message.chat.id, res.text, parse_mode="Markdown")
        
    except Exception as e:
        print(f"Error general en el procesamiento matemático: {e}")
        bot.send_message(call.message.chat.id, "❌ No se pudieron calcular las fórmulas de este encuentro. Inténtalo con otro de la lista.")

if __name__ == "__main__":
    print("Iniciando servidor web...")
    server_thread = Thread(target=run_flask)
    server_thread.start()
    
    print("Bot Predictivo Matemático de Datos Reales corriendo...")
    bot.infinity_polling()
