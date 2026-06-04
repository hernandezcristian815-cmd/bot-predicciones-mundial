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
# 4. PROCESAMIENTO HÍBRIDO (BÚSQUEDA IA + MATEMÁTICA PYTHON)
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('c_'))
def procesar_prediccion_ia(call):
    bot.answer_callback_query(call.id, text="Buscando estadísticas con la IA...")
    
    try:
        partes = call.data.split('_')
        home_id = partes[1]
        away_id = partes[2]
        home_name = partes[3] if len(partes) > 3 else "Local"
        away_name = partes[4] if len(partes) > 4 else "Visitante"

        # Rastreo web del encuentro para alimentar el contexto histórico
        contexto_noticias = ""
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(f"{home_name} vs {away_name} pronostico ultimos partidos resultados", max_results=3):
                    contexto_noticias += f"{r['title']}: {r['body']}\n"
        except:
            contexto_noticias = "Sin noticias web recientes."

        # Prompt estructurado: La IA solo actúa como base de datos externa de números puros
        prompt_extraccion = f"""
        Analiza las noticias actuales y tu conocimiento sobre el partido de fútbol: {home_name} vs {away_name}.
        Noticias encontradas:
        {contexto_noticias}

        Extrae o estima los números del rendimiento de estos equipos y responde ÚNICAMENTE con el siguiente formato exacto de líneas (reemplaza X, Y, Z, W, V por números enteros puros, no escribas nada más de texto ni explicaciones):
        victorias_local: X
        victorias_visitante: Y
        empates: Z
        goles_totales: W
        partidos_totales: V
        """

        # VALORES POR DEFECTO BASE (Seguro de vida matemático)
        v_h, v_a, emp, g_t, p_t = 3, 2, 1, 15, 6

        # CONEXIÓN DIRECTA POR HTTP A GEMINI (Bypasa errores del SDK y bloqueos 404)
        try:
            url_gemini = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
            payload = {"contents": [{"parts": [{"text": prompt_extraccion}]}]}
            res = requests.post(url_gemini, json=payload, headers={"Content-Type": "application/json"}, timeout=10).json()
            
            if "candidates" in res:
                texto_ia = res["candidates"][0]["content"]["parts"][0]["text"]
                # Parseador de números automático en Python
                for linea in texto_ia.split("\n"):
                    if ":" in linea:
                        clave, valor = linea.split(":", 1)
                        clave = clave.strip().lower()
                        valor = "".join(filter(str.isdigit, valor.strip()))
                        if valor:
                            num = int(valor)
                            if "victorias_local" in clave: v_h = num
                            elif "victorias_visitante" in clave: v_a = num
                            elif "empates" in clave: emp = num
                            elif "goles_totales" in clave: g_t = num
                            elif "partidos_totales" in clave: p_t = max(num, 1)
        except Exception as err_api:
            print(f"Error llamando a la API de Google: {err_api}")

        # --- PROCESAMIENTO MATEMÁTICO REAL EN EL SERVIDOR PYTHON ---
        total_p = v_h + v_a + emp
        if total_p == 0: v_h, v_a, emp, total_p = 3, 2, 1, 6

        p_local = round((v_h / total_p) * 100)
        p_visitante = round((v_a / total_p) * 100)
        p_empate = 100 - (p_local + p_visitante)
        goles_prom = round(g_t / max(p_t, 1), 1)
        if goles_prom == 0: goles_prom = 2.4

        ambos_anotan = "Sí ⚽" if goles_prom >= 2.1 else "No 🚫"
        over_under = "Over 2.5 🔥" if goles_prom >= 2.5 else "Under 2.5 🧊"
        
        if p_local >= 45:
            marcador = "2-0 o 2-1"
            pick = f"Gana {home_name} (o ventaja Local)"
            confianza = "Alta 🟢"
        elif p_visitante >= 45:
            marcador = "0-1 o 1-2"
            pick = f"Gana {away_name} (o ventaja Visitante)"
            confianza = "Alta 🟢"
        else:
            marcador = "1-1 o 0-0"
            pick = "Empate o Menos de 2.5 goles"
            confianza = "Media 🟡"

        # --- CONSTRUCCIÓN DEL MENSAJE FINAL (Estructura fija perfecta) ---
        reporte = f"📊 **ANÁLISIS ESTADÍSTICO HÍBRIDO**\n"
        reporte += f"⚽ *{home_name} vs {away_name}*\n\n"
        reporte += f"📈 **Probabilidades Matemáticas (IA + Modelo):**\n"
        reporte += f"🏠 Local: {p_local}%\n"
        reporte += f"🤝 Empate: {p_empate}%\n"
        reporte += f"✈️ Visitante: {p_visitante}%\n\n"
        reporte += f"🎯 **Proyecciones del Encuentro:**\n"
        reporte += f"• Promedio goles: {goles_prom} por juego\n"
        reporte += f"• Ambos anotan: {ambos_anotan}\n"
        reporte += f"• Línea sugerida: {over_under}\n"
        reporte += f"• Marcador exacto: {marcador}\n\n"
        reporte += f"💰 **Mejor Apuesta:** {pick}\n"
        reporte += f"⚡ **Confianza:** {confianza}\n"

        bot.send_message(call.message.chat.id, reporte, parse_mode="Markdown")

    except Exception as e:
        print(f"Error general: {e}")
        bot.send_message(call.message.chat.id, "❌ Error al compilar los números del partido.")

# ==========================================
# 5. RASTREADOR DE TEXTO LIBRE (CONEXIÓN DIRECTA)
# ==========================================
@bot.message_handler(func=lambda message: True)
def buscar_equipo_libre(message):
    texto = message.text.lower()
    if "datos de" in texto or "estadisticas de" in texto:
        equipo = message.text.replace("datos de", "").replace("Datos de", "").replace("estadísticas de", "").strip()
        if not equipo:
            bot.reply_to(message, "Escribe el nombre del club. Ejemplo: `datos de Atletico Nacional`")
            return
            
        bot.reply_to(message, f"🌐 Rastreando internet en busca de *{equipo}*...", parse_mode="Markdown")
        try:
            contexto = ""
            with DDGS() as ddgs:
                for r in ddgs.text(f"{equipo} actualidad ultimos resultados futbol", max_results=3):
                    contexto += f"Titular: {r['title']}\nResumen: {r['body']}\n\n"
            
            prompt = f"Actúa como analista. Basado en esta info actual de internet:\n{contexto}\nDa un perfil táctico rápido para apuestas de {equipo} en Markdown."
            
            url_gemini = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            res = requests.post(url_gemini, json=payload, headers={"Content-Type": "application/json"}, timeout=10).json()
            
            if "candidates" in res:
                respuesta_texto = res["candidates"][0]["content"]["parts"][0]["text"]
                bot.send_message(message.chat.id, respuesta_texto, parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, "❌ No logré procesar el resumen táctico.")
        except:
            bot.reply_to(message, "❌ Fallo de conexión con los buscadores.")

if __name__ == "__main__":
    Thread(target=run_flask).start()
    print("Bot Híbrido Corriendo...")
    bot.infinity_polling()
