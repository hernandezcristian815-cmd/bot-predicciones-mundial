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
# 4. MOTOR ESTADÍSTICO MATEMÁTICO AVANZADO (5 PARTIDOS + DEEP STATS)
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('c_'))
def procesar_prediccion_ia(call):
    bot.answer_callback_query(call.id, text="Procesando 5 partidos y estadísticas profundas...")
    
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

        # 1. EXTRACCIÓN DE 5 PARTIDOS REALES (API DE FÚTBOL)
        try:
            local_data = requests.get("https://v3.football.api-sports.io/fixtures", headers=headers, params={"team": home_id, "last": 5}, timeout=8).json()
            visit_data = requests.get("https://v3.football.api-sports.io/fixtures", headers=headers, params={"team": away_id, "last": 5}, timeout=8).json()
        except:
            local_data, visit_data = {}, {}

        goles_recientes = 0
        partidos_contados = 0

        def formatear_resultados(data):
            nonlocal goles_recientes, partidos_contados
            res_str = ""
            if data and data.get("response"):
                for f in data["response"]:
                    h_team = f["teams"]["home"]["name"]
                    a_team = f["teams"]["away"]["name"]
                    g_h = f["goals"]["home"] if f["goals"]["home"] is not None else 0
                    g_a = f["goals"]["away"] if f["goals"]["away"] is not None else 0
                    
                    goles_recientes += (g_h + g_a)
                    partidos_contados += 1
                    res_str += f"▫️ {h_team} {g_h}-{g_a} {a_team}\n"
            return res_str if res_str else "Sin datos."

        historial_local = formatear_resultados(local_data)
        historial_visit = formatear_resultados(visit_data)

        # 2. DATA MINING CON IA (Promedios profundos sin gastar cuota de API)
        prompt = f"""
        Actúa como base de datos deportiva. Analiza el estilo de juego general de {home_name} y {away_name}.
        Devuelve ÚNICAMENTE los siguientes valores puros basados en promedios y conocimientos tácticos.
        PROHIBIDO usar texto, Markdown o explicaciones. Solo el formato exacto clave:valor.
        
        corners: [numero decimal promedio del partido]
        tarjetas: [numero decimal promedio del partido]
        atajadas: [numero decimal promedio de atajadas por partido]
        prob_local: [numero entero 0-100]
        prob_visit: [numero entero 0-100]
        prob_empate: [numero entero 0-100]
        goleador_local: [Apellido del mejor jugador/goleador]
        goleador_visitante: [Apellido del mejor jugador/goleador]
        """

        # Variables por defecto (Seguro matemático)
        corners, tarjetas, atajadas = 9.5, 4.5, 6.0
        p_loc, p_vis, p_emp = 40, 35, 25
        goleador_loc, goleador_vis = "Delantero", "Delantero"

        url_gemini = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        try:
            res = requests.post(url_gemini, json=payload, headers={"Content-Type": "application/json"}, timeout=12).json()
            if "candidates" in res:
                texto_ia = res["candidates"][0]["content"]["parts"][0]["text"].strip()
                
                # Parseador avanzado de Python
                for linea in texto_ia.split('\n'):
                    if ':' in linea:
                        clave, valor = linea.split(':', 1)
                        clave = clave.strip().lower()
                        valor_str = valor.strip()
                        
                        if 'goleador_local' in clave: goleador_loc = valor_str.title()
                        elif 'goleador_visitante' in clave: goleador_vis = valor_str.title()
                        else:
                            try:
                                num = float("".join(c for c in valor_str if c.isdigit() or c == '.'))
                                if 'corners' in clave: corners = num
                                elif 'tarjetas' in clave: tarjetas = num
                                elif 'atajadas' in clave: atajadas = num
                                elif 'prob_local' in clave: p_loc = num
                                elif 'prob_visit' in clave: p_vis = num
                                elif 'prob_empate' in clave: p_emp = num
                            except:
                                pass
        except Exception as e:
            print(f"Error en Data-Mining: {e}")

        # 3. LÓGICA MATEMÁTICA PURA
        total_prob = p_loc + p_vis + p_emp
        if total_prob > 0:
            p_loc = round((p_loc / total_prob) * 100)
            p_vis = round((p_vis / total_prob) * 100)
            p_emp = 100 - (p_loc + p_vis)

        promedio_goles = round(goles_recientes / partidos_contados, 1) if partidos_contados > 0 else 2.5
        linea_goles = "Over 2.5 🔥" if promedio_goles > 2.2 else "Under 2.5 🧊"
        ambos_anotan = "Sí ⚽" if promedio_goles >= 2.0 and p_emp > 20 else "No 🚫"

        if p_loc >= 45:
            pick = f"Gana {home_name}"
            confianza = "Alta 🟢"
            marcador = "2-0 o 2-1"
        elif p_vis >= 45:
            pick = f"Gana {away_name}"
            confianza = "Alta 🟢"
            marcador = "0-1 o 1-2"
        else:
            pick = "Doble Oportunidad o Empate"
            confianza = "Media 🟡"
            marcador = "1-1 o 0-0"

        # 4. CONSTRUCCIÓN DEL REPORTE PRO
        reporte = f"📊 **ANÁLISIS ESTADÍSTICO PRO (5 PARTIDOS)**\n"
        reporte += f"⚽ *{home_name} vs {away_name}*\n\n"
        
        reporte += f"📈 **Probabilidades Matemáticas:**\n"
        reporte += f"🏠 Local: {p_loc}% | 🤝 Empate: {p_emp}% | ✈️ Visit: {p_vis}%\n\n"

        reporte += f"🔄 **Forma Reciente (Últimos 5 del Local):**\n{historial_local}\n"
        reporte += f"🔄 **Forma Reciente (Últimos 5 del Visitante):**\n{historial_visit}\n"
        
        reporte += f"🎯 **Líneas Calculadas para Apuestas:**\n"
        reporte += f"• Promedio Goles: {promedio_goles}\n"
        reporte += f"• Ambos Anotan: {ambos_anotan}\n"
        reporte += f"• Tiros de Esquina: Más de {corners}\n"
        reporte += f"• Tarjetas Totales: Más de {tarjetas}\n"
        reporte += f"• Atajadas (Porteros): Más de {atajadas}\n\n"

        reporte += f"⭐ **Jugadores a seguir (Posibles Goleadores):**\n"
        reporte += f"• {home_name}: {goleador_loc}\n"
        reporte += f"• {away_name}: {goleador_vis}\n\n"
        
        reporte += f"💰 **PICK DEL ALGORITMO:** {pick}\n"
        reporte += f"⚡ **Confianza:** {confianza}"

        bot.send_message(call.message.chat.id, reporte, parse_mode="Markdown")

    except Exception as e:
        print(f"Error crítico: {e}")
        bot.send_message(call.message.chat.id, f"❌ Error interno procesando estadísticas: {str(e)}")
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
