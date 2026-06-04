import os
import datetime
import requests
import telebot
import google.generativeai as genai
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
from threading import Thread
from duckduckgo_search import DDGS

# ==========================================
# 1. CONFIGURACIÓN Y SEGURIDAD
# ==========================================
# 1. CONFIGURACIÓN Y SEGURIDAD
TTELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

# Usamos el modelo flash oficial
model = genai.GenerativeModel('gemini-1.5-flash')
app = Flask(__name__)

@app.route('/')
def home():
    return "Servidor Blindado Activo", 200

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

# ==========================================
# 2. CALENDARIO POR LIGAS
# ==========================================
def obtener_cartelera_por_ligas():
    ahora_colombia = datetime.datetime.utcnow() - datetime.timedelta(hours=5)
    fecha_str = ahora_colombia.strftime('%Y-%m-%d')
    
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {
        'x-rapidapi-host': 'v3.football.api-sports.io',
        'x-rapidapi-key': API_FOOTBALL_KEY
    }
    
    categorias = {
        "🏆 SELECCIONES": [],
        "🇪🇺 LIGAS TOP EUROPA": [],
        "🇨🇴 FÚTBOL LATINOAMÉRICA": [],
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
                
                liga = info["league"].lower()
                pais = info["pais"].lower()
                
                if any(x in liga for x in ["friendlies", "cup", "international"]) and pais == "world":
                    categorias["🏆 SELECCIONES"].append(info)
                elif any(x in liga for x in ["premier league", "la liga", "primera division", "serie a", "bundesliga", "uefa champions", "uefa europa"]):
                    categorias["🇪🇺 LIGAS TOP EUROPA"].append(info)
                elif any(x in liga or x in pais for x in ["colombia", "betplay", "argentina", "brazil", "mexico", "libertadores", "sudamericana"]):
                    categorias["🇨🇴 FÚTBOL LATINOAMÉRICA"].append(info)
                else:
                    categorias["⚽ OTRAS LIGAS Y COPAS"].append(info)
                        
    except Exception as e:
        print(f"Error cargando agenda: {e}")
        
    return categorias, fecha_str

# ==========================================
# 3. INTERFAZ (MENÚ)
# ==========================================
@bot.message_handler(commands=['start', 'ayuda'])
def enviar_ayuda(message):
    texto = "🤖 *Panel de Análisis Deportivo*\n\n⚽ `/polla` o `/partidos` - Agenda del día.\n🌐 Escribe `datos de [equipo]` para rastreo web."
    bot.reply_to(message, texto, parse_mode="Markdown")

@bot.message_handler(commands=['polla', 'partidos'])
def enviar_menu_dinamico(message):
    bot.send_chat_action(message.chat.id, 'typing')
    categorias, fecha_hoy = obtener_cartelera_por_ligas()
    
    markup = InlineKeyboardMarkup()
    markup.row_width = 1
    texto_mensaje = f"🗓️ *Cartelera de Partidos ({fecha_hoy})*\n_Elige un encuentro para extraer sus estadísticas:_\n\n"
    
    hay_partidos = False
    for nombre_cat, partidos in categorias.items():
        if partidos:
            hay_partidos = True
            texto_mensaje += f"\n*{nombre_cat}*\n"
            for p in partidos[:5]: # Máximo 5 por categoría
                # Rescatamos nombres cortos garantizados para el botón
                h_name = p['home'][:12].replace('_', '').replace(' ', '')
                a_name = p['away'][:12].replace('_', '').replace(' ', '')
                callback_data = f"c_{p['home_id']}_{p['away_id']}_{h_name}_{a_name}"
                
                markup.add(InlineKeyboardButton(f"🔹 {p['home']} vs {p['away']}", callback_data=callback_data))
                texto_mensaje += f" • {p['home']} vs {p['away']} _({p['league'][:15]})_\n"
                
    if not hay_partidos:
        bot.send_message(message.chat.id, "⏳ No hay partidos relevantes programados para hoy.")
        return
        
    bot.send_message(message.chat.id, texto_mensaje, parse_mode="Markdown", reply_markup=markup)

# ==========================================
# 4. MOTOR ESTADÍSTICO A PRUEBA DE FALLOS
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('c_'))
def procesar_prediccion_ia(call):
    bot.answer_callback_query(call.id, text="Consultando IA y simulando...")
    
    try:
        partes = call.data.split('_')
        home_id = partes[1]
        away_id = partes[2]
        home_name = partes[3] if len(partes) > 3 else "Equipo Local"
        away_name = partes[4] if len(partes) > 4 else "Equipo Visitante"

        headers = {
            'x-rapidapi-host': 'v3.football.api-sports.io',
            'x-rapidapi-key': API_FOOTBALL_KEY
        }

        try:
            h2h = requests.get("https://v3.football.api-sports.io/fixtures/headtohead", headers=headers, params={"h2h": f"{home_id}-{away_id}", "last": 5}, timeout=8).json()
            local = requests.get("https://v3.football.api-sports.io/fixtures", headers=headers, params={"team": home_id, "last": 10}, timeout=8).json()
            visitante = requests.get("https://v3.football.api-sports.io/fixtures", headers=headers, params={"team": away_id, "last": 10}, timeout=8).json()
        except:
            h2h, local, visitante = {}, {}, {}

        def limpiar_resultados(json_data):
            if not json_data or not json_data.get("response"): return "Sin registros."
            lineas = []
            for f in json_data["response"]:
                h_team = f["teams"]["home"]["name"]
                a_team = f["teams"]["away"]["name"]
                g_h = f["goals"]["home"] if f["goals"]["home"] is not None else "-"
                g_a = f["goals"]["away"] if f["goals"]["away"] is not None else "-"
                lineas.append(f"{h_team} {g_h} - {g_a} {a_team}")
            return "\n".join(lineas)

        historial_h2h = limpiar_resultados(h2h)
        historial_local = limpiar_resultados(local)
        historial_visit = limpiar_resultados(visitante)

        prompt = f"""
        Actúa como un analista experto en apuestas deportivas.
        Partido: {home_name} vs {away_name}.

        Datos de la API:
        - H2H: {historial_h2h}
        - Últimos de {home_name}: {historial_local}
        - Últimos de {away_name}: {historial_visit}

        REGLA DE ORO: Si no hay datos, usa tu propia base de conocimiento y lógica de localía para dar una predicción certera de todos modos.
        EVITA usar asteriscos sueltos (*). Usa un formato súper limpio para Telegram.

        Formato:
        📊 Probabilidades: Local %, Empate %, Visitante %
        ⚽ Ambos anotan: Sí/No
        🔥 Over/Under 2.5: Detalle
        🎯 Marcador exacto:
        💰 Mejor apuesta:
        """

        respuesta = model.generate_content(prompt)
        
        # SALVAVIDAS: Si Telegram crashea por el Markdown, lo mandamos en texto plano
        try:
            bot.send_message(call.message.chat.id, respuesta.text, parse_mode="Markdown")
        except Exception as tg_error:
            print(f"Telegram rechazó el Markdown: {tg_error}")
            bot.send_message(call.message.chat.id, respuesta.text)

    except Exception as e:
        print(f"Error crítico en proceso IA: {e}")
        # Ahora el bot te dirá EXACTAMENTE qué falló en tu grupo
        bot.send_message(call.message.chat.id, f"❌ Ocurrió un error técnico:\n`{str(e)}`\n_Si dice API Key not valid, revisa la llave de Gemini en Render._", parse_mode="Markdown")

# ==========================================
# 5. RASTREADOR WEB (TEXTO LIBRE)
# ==========================================
@bot.message_handler(func=lambda message: True)
def buscar_equipo_libre(message):
    texto = message.text.lower()
    if "datos de" in texto or "estadisticas de" in texto:
        equipo = message.text.replace("datos de", "").replace("Datos de", "").replace("estadísticas de", "").strip()
        if not equipo:
            bot.reply_to(message, "Escribe el nombre del club.")
            return
            
        bot.reply_to(message, f"🌐 Rastreando internet en busca de *{equipo}*...", parse_mode="Markdown")
        try:
            contexto = ""
            with DDGS() as ddgs:
                for r in ddgs.text(f"{equipo} actualidad ultimos resultados futbol", max_results=3):
                    contexto += f"Titular: {r['title']}\nResumen: {r['body']}\n\n"
            
            prompt = f"Crea un perfil de apuestas para {equipo} basado en esta info actual:\n{contexto}\nUsa Markdown y emojis."
            res = model.generate_content(prompt)
            bot.send_message(message.chat.id, res.text, parse_mode="Markdown")
        except:
            bot.reply_to(message, "❌ Fallo de conexión con los buscadores.")

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling()
