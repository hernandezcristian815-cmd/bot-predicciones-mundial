import os
import datetime
import telebot
import requests
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
    return "Bot Estadistico Matematico Operando", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# ID exactos de torneos comerciales premium (Evita ligas desconocidas)
# 2: Champions, 3: Europa League, 10: Amistosos Selecciones, 39: Premier, 140: LaLiga, 135: Serie A, 239: Colombia
LEAGUE_IDS = [2, 3, 10, 39, 140, 135, 239]

def obtener_cartelera_premium(fecha_str):
    """Filtra partidos estrictamente importantes usando IDs de ligas comerciales"""
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {
        'x-rapidapi-host': 'v3.football.api-sports.io',
        'x-rapidapi-key': API_FOOTBALL_KEY
    }
    partidos = []
    
    for league_id in LEAGUE_IDS:
        params = {'date': fecha_str, 'league': league_id}
        try:
            response = requests.get(url, headers=headers, params=params, timeout=8).json()
            if "response" in response:
                for item in response["response"]:
                    partidos.append({
                        "id": item["fixture"]["id"],
                        "home": item["teams"]["home"]["name"],
                        "home_id": item["teams"]["home"]["id"],
                        "away": item["teams"]["away"]["name"],
                        "away_id": item["teams"]["away"]["id"],
                        "league": item["league"]["name"]
                    })
        except Exception as e:
            print(f"Error consultando liga {league_id}: {e}")
    return partidos

@bot.message_handler(commands=['start', 'ayuda', 'help'])
def enviar_lista_comandos(message):
    texto_ayuda = (
        "🤖 *Centro Estadístico de Apuestas en Vivo*\n\n"
        "Comandos disponibles:\n"
        "⚽ `/polla` o `/partidos` \- Despliega los encuentros del día procesados por la API\.\n"
        "ℹ️ `/ayuda` \- Muestra este menú de asistencia\."
    )
    bot.send_message(message.chat.id, texto_ayuda, parse_mode="MarkdownV2")

@bot.message_handler(commands=['polla', 'partidos'])
def enviar_menu_dinamico(message):
    bot.send_message(message.chat.id, "📊 Consultando la agenda de partidos comerciales importantes...")
    
    ahora = datetime.datetime.now()
    fecha_hoy = ahora.strftime('%Y-%m-%d')
    fecha_manana = (ahora + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    
    # Intenta hoy, si no hay pasa a mañana
    lista_partidos = obtener_cartelera_premium(fecha_hoy)
    titulo_menu = "⚽ *¡Cartelera Premium de HOY\!*"
    
    if not lista_partidos:
        lista_partidos = obtener_cartelera_premium(fecha_manana)
        titulo_menu = "🗓️ *Cartelera Premium de MAÑANA\!*"
        
    if not lista_partidos:
        bot.send_message(message.chat.id, "⏳ Sin partidos comerciales programados para hoy ni mañana en las ligas principales.")
        return
        
    markup = InlineKeyboardMarkup()
    markup.row_width = 1
    
    for i, partido in enumerate(lista_partidos[:15]):
        texto_boton = f"{partido['home']} vs. {partido['away']} ({partido['league'][:12]})"
        # Empaquetamos los IDs numéricos en el callback para buscar el historial real (H2H)
        callback_data = f"c_{partido['home_id']}_{partido['away_id']}"
        markup.add(InlineKeyboardButton(texto_boton, callback_data=callback_data))
        
    bot.send_message(message.chat.id, f"{titulo_menu}\nSelecciona un partido para calcular las cuotas estimadas:", parse_mode="MarkdownV2", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('c_'))
def procesar_prediccion_ia(call):
    bot.answer_callback_query(call.id, text="Procesando datos del H2H histórico...")
    
    try:
        _, home_id, away_id = call.data.split('_')
        
        # 1. Consultar el historial de enfrentamientos directos (H2H) en la API
        url = "https://v3.football.api-sports.io/fixtures/headtohead"
        headers = {
            'x-rapidapi-host': 'v3.football.api-sports.io',
            'x-rapidapi-key': API_FOOTBALL_KEY
        }
        params = {'h2h': f"{home_id}-{away_id}", 'last': 5}
        
        response = requests.get(url, headers=headers, params=params, timeout=10).json()
        
        # Valores base por defecto por si el historial es limpio (sin partidos previos registrados)
        victorias_home, victorias_away, empates = 2, 2, 1
        goles_totales = 12
        home_name, away_name = "Equipo Local", "Equipo Visitante"
        
        if "response" in response and response["response"]:
            victorias_home, victorias_away, empates = 0, 0, 0
            goles_totales = 0
            
            # Analizamos los últimos partidos para sacar la estadística real
            partidos_previos = response["response"]
            home_name = partidos_previos[0]["teams"]["home"]["name"]
            away_name = partidos_previos[0]["teams"]["away"]["name"]
            
            for f in partidos_previos:
                goles_totales += (f["goals"]["home"] if f["goals"]["home"] is not None else 0) + (f["goals"]["away"] if f["goals"]["away"] is not None else 0)
                if f["teams"]["home"]["winner"]:
                    victorias_home += 1
                elif f["teams"]["away"]["winner"]:
                    victorias_away += 1
                else:
                    empates += 1
        
        # 2. FÓRMULAS MATEMÁTICAS EN TU SERVIDOR (Garantiza que siempre haya porcentajes exactos)
        total_partidos = victorias_home + victorias_away + empates
        p_local = round((victorias_home / total_partidos) * 100)
        p_visitante = round((victorias_away / total_partidos) * 100)
        p_empate = 100 - (p_local + p_visitante)
        
        # Estimaciones basadas en promedios estadísticos de ligas de alto nivel
        goles_promedio = round(goles_totales / max(total_partidos, 1), 1)
        if goles_promedio == 0: goles_promedio = 2.4
        
        corners_estimados = "8.5 - 10.5" if p_local > 40 else "7.5 - 9.5"
        tarjetas_estimadas = "3.5 - 5.5" if p_empate > 30 else "3.5 - 4.5"
        ambos_anotan = "Sí" if goles_promedio >= 2.2 else "No"
        
        # 3. LA IA ENTRA A REDACTAR EL REPORTE FINAL CON LOS DATOS REALES YA CALCULADOS
        prompt = (
            f"Escribe un reporte de apuestas atractivo para el partido {home_name} vs {away_name}.\n"
            f"Usa obligatoriamente estos datos matemáticos exactos que ya calculé en el servidor:\n"
            f"- Probabilidad Local: {p_local}%\n"
            f"- Probabilidad Empate: {p_empate}%\n"
            f"- Probabilidad Visitante: {p_visitante}%\n"
            f"- Promedio de goles históricos: {goles_promedio}\n"
            f"- Ambos anotan: {ambos_anotan}\n"
            f"- Córners sugeridos: {corners_estimados}\n"
            f"- Tarjetas sugeridas: {tarjetas_estimadas}\n\n"
            f"Entrega el reporte formateado de forma limpia con Markdown para Telegram, agregando emojis y "
            f"proponiendo un marcador exacto lógico (ej: 2-1) junto a un Tip de Valor basado en esos números."
        )
        
        res = model.generate_content(prompt)
        bot.send_message(call.message.chat.id, res.text, parse_mode="Markdown")
        
    except Exception as e:
        print(f"Error procesando el cálculo matemático: {e}")
        bot.send_message(call.message.chat.id, "❌ Error al procesar los datos de este partido. Elige otro de la lista.")

if __name__ == "__main__":
    print("Iniciando servidor web...")
    server_thread = Thread(target=run_flask)
    server_thread.start()
    
    print("Bot Predictivo Matemático corriendo...")
    bot.infinity_polling()
