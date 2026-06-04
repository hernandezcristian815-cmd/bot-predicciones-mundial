import os
import datetime
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
from threading import Thread
from duckduckgo_search import DDGS

# ==========================================
# 1. CONFIGURACIÓN Y SERVIDOR (Render)
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "Servidor Algorítmico Híbrido Activo", 200

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

# ==========================================
# 2. CALENDARIO DIARIO DE PARTIDOS
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
        response = requests.get(url, headers=headers, params={'date': fecha_str}, timeout=10).json()
        if "response" in response and response["response"]:
            for item in response["response"]:
                info = {
                    "home": item["teams"]["home"]["name"],
                    "home_id": item["teams"]["home"]["id"],
                    "away": item["teams"]["away"]["name"],
                    "away_id": item["teams"]["away"]["id"],
                    "league": item["league"]["name"]
                }
                
                liga = info["league"].lower()
                if any(x in liga for x in ["friendlies", "cup", "international"]):
                    categorias["🏆 SELECCIONES"].append(info)
                elif any(x in liga for x in ["premier league", "la liga", "primera division", "serie a", "bundesliga", "uefa"]):
                    categorias["🇪🇺 LIGAS TOP EUROPA"].append(info)
                elif any(x in liga for x in ["colombia", "betplay", "argentina", "brazil", "mexico", "libertadores"]):
                    categorias["🇨🇴 FÚTBOL LATINOAMÉRICA"].append(info)
                else:
                    categorias["⚽ OTRAS LIGAS Y COPAS"].append(info)
    except:
        pass
    return categorias, fecha_str

# ==========================================
# 3. INTERFAZ DE COMANDOS
# ==========================================
@bot.message_handler(commands=['start', 'ayuda'])
def enviar_ayuda(message):
    texto = "🤖 *Panel Estadístico Híbrido*\n\n⚽ `/polla` o `/partidos` - Agenda del día.\n🌐 Escribe `datos de [equipo]` para rastreo web."
    bot.reply_to(message, texto, parse_mode="Markdown")

@bot.message_handler(commands=['polla', 'partidos'])
def enviar_menu_dinamico(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        categorias, fecha_hoy = obtener_cartelera_por_ligas()
        
        markup = InlineKeyboardMarkup()
        markup.row_width = 1
        texto_mensaje = f"🗓️ *Cartelera de Partidos ({fecha_hoy})*\n_Elige un encuentro para calcular las cuotas con el modelo matemático:_\n\n"
        
        hay_partidos = False
        for nombre_cat, partidos in categorias.items():
            if partidos:
                hay_partidos = True
                texto_mensaje += f"\n*{nombre_cat}*\n"
                for p in partidos[:4]:
                    h_name = p['home'][:12].replace('_', '').replace(' ', '')
                    a_name = p['away'][:12].replace('_', '').replace(' ', '')
                    callback_data = f"c_{p['home_id']}_{p['away_id']}_{h_name}_{a_name}"
                    markup.add(InlineKeyboardButton(f"🔹 {p['home']} vs {p['away']}", callback_data=callback_data))
                    texto_mensaje += f" • {p['home']} vs {p['away']}\n"
                    
        if not hay_partidos:
            bot.send_message(message.chat.id, "⏳ No hay partidos comerciales programados para hoy.")
            return
            
        bot.send_message(message.chat.id, texto_mensaje, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"Error en menú: {e}")

# ==========================================
# 4. PROCESAMIENTO HÍBRIDO (APUESTAS COMPLETAS)
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('c_'))
def procesar_prediccion_ia(call):
    bot.answer_callback_query(call.id, text="Extrayendo últimos resultados y corners...")
    
    try:
        partes = call.data.split('_')
        home_id = partes[1]
        away_id = partes[2]
        home_name = partes[3] if len(partes) > 3 else "Local"
        away_name = partes[4] if len(partes) > 4 else "Visitante"

        headers = {
            'x-rapidapi-host': 'v3.football.api-sports.io',
            'x-rapidapi-key': API_FOOTBALL_KEY
        }

        # EXTRAER LOS ÚLTIMOS 3 RESULTADOS REALES DE LA API
        try:
            local_data = requests.get("https://v3.football.api-sports.io/fixtures", headers=headers, params={"team": home_id, "last": 3}, timeout=8).json()
            visit_data = requests.get("https://v3.football.api-sports.io/fixtures", headers=headers, params={"team": away_id, "last": 3}, timeout=8).json()
        except:
            local_data, visit_data = {}, {}

        def formatear_resultados(data):
            res_str = ""
            if data and data.get("response"):
                for f in data["response"]:
                    h_team = f["teams"]["home"]["name"]
                    a_team = f["teams"]["away"]["name"]
                    g_h = f["goals"]["home"] if f["goals"]["home"] is not None else "-"
                    g_a = f["goals"]["away"] if f["goals"]["away"] is not None else "-"
                    res_str += f"▫️ {h_team} {g_h}-{g_a} {a_team}\n"
            return res_str if res_str else "Sin datos recientes."

        historial_local = formatear_resultados(local_data)
        historial_visit = formatear_resultados(visit_data)

        # PROMPT PARA LA IA
        prompt = f"""
        Actúa como un tipster y analista experto en apuestas de fútbol.
        Partido: {home_name} vs {away_name}.

        Resultados REALES de los últimos 3 partidos (Local):
        {historial_local}
        Resultados REALES de los últimos 3 partidos (Visitante):
        {historial_visit}

        Genera un reporte de apuestas estructurado basándote en estos resultados y en el estilo de juego histórico de estos equipos.
        Debes calcular y sugerir líneas para: Tiros de Esquina, Tarjetas y Tiros a Puerta.
        
        Responde EXACTAMENTE con este formato (no agregues asteriscos sueltos ni texto extra al inicio o final):

        📊 **ANÁLISIS DE APUESTAS PRO**
        ⚽ *{home_name} vs {away_name}*

        🔄 **Fiabilidad (Últimos 3 del Local):**
        {historial_local}
        🔄 **Fiabilidad (Últimos 3 del Visitante):**
        {historial_visit}
        📈 **Probabilidades de Victoria:**
        🏠 Local: % | 🤝 Empate: % | ✈️ Visitante: %

        🎯 **Mercado de Goles:**
        • Ambos anotan: (Sí/No y por qué brevemente)
        • Línea de Goles: (Sugerencia Over/Under)
        • Marcador Exacto Probable: X-X

        🚩 **Mercados Especiales (Estimación táctica):**
        • Tiros de Esquina (Corners): (Ej: Más de 8.5)
        • Tarjetas Totales: (Ej: Más de 4.5 amarillas)
        • Faltas / Tiros al arco: (Breve pronóstico)

        💰 **MEJOR APUESTA (PICK DEL DÍA):** (Tu recomendación más segura)
        ⚡ **Nivel de Confianza:** (Baja/Media/Alta)
        """

        url_gemini = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        res = requests.post(url_gemini, json=payload, headers={"Content-Type": "application/json"}, timeout=15).json()
        
        if "candidates" in res:
            reporte_final = res["candidates"][0]["content"]["parts"][0]["text"]
            try:
                bot.send_message(call.message.chat.id, reporte_final, parse_mode="Markdown")
            except Exception as tg_err:
                # Seguro de vida por si Telegram rechaza el Markdown
                bot.send_message(call.message.chat.id, f"⚠️ Error de formato en Telegram. Te lo envío en texto plano:\n\n{reporte_final}")
        else:
            # AHORA SÍ VEREMOS EL ERROR REAL DE GOOGLE
            error_oculto = str(res.get("error", res))
            bot.send_message(call.message.chat.id, f"❌ API de Google rechazó la consulta. Motivo exacto:\n\n{error_oculto}")

    except Exception as e:
        print(f"Error crítico procesando apuesta: {e}")
        bot.send_message(call.message.chat.id, f"❌ Hubo un fallo en el servidor: {str(e)}")

# ==========================================
# 5. RASTREADOR DE TEXTO LIBRE (REPARADO)
# ==========================================
@bot.message_handler(func=lambda message: True)
def buscar_equipo_libre(message):
    texto = message.text.lower()
    if "datos de" in texto or "estadisticas de" in texto:
        equipo = message.text.replace("datos de", "").replace("datos de", "").replace("estadísticas de", "").strip()
        if not equipo:
            bot.reply_to(message, "Escribe el nombre del club. Ejemplo: `datos de Boca Juniors`")
            return
            
        bot.reply_to(message, f"🌐 Rastreando internet y analizando a *{equipo}*...", parse_mode="Markdown")
        
        try:
            contexto = ""
            try:
                with DDGS() as ddgs:
                    for r in ddgs.text(f"{equipo} actualidad ultimos resultados futbol apuestas", max_results=3):
                        contexto += f"{r['title']}: {r['body']}\n"
            except:
                contexto = "No se pudo acceder a noticias en vivo por límite de búsquedas, usa tu conocimiento general del equipo."
            
            prompt = f"Actúa como un analista deportivo. Basado en tu base de datos y esta info reciente si la hay: {contexto}. Escribe un resumen táctico de apuestas para {equipo}. Incluye promedios típicos de córners, estilo de juego, y si son un equipo tarjetero o limpio. Usa Markdown y emojis."
            
            url_gemini = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            res = requests.post(url_gemini, json=payload, headers={"Content-Type": "application/json"}, timeout=12).json()
            
            if "candidates" in res:
                respuesta_texto = res["candidates"][0]["content"]["parts"][0]["text"]
                bot.send_message(message.chat.id, respuesta_texto, parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, f"❌ Google IA bloqueó la respuesta o no hay datos para {equipo}.")
        except Exception as e:
            bot.reply_to(message, "❌ Error de conexión al procesar el resumen de este equipo.")

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling()
