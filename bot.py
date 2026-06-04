import os
import json
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
# 4. MOTOR ESTADÍSTICO MATEMÁTICO (EXTRACCIÓN JSON ESTRICTA)
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('c_'))
def procesar_prediccion_ia(call):
    bot.answer_callback_query(call.id, text="Procesando datos estadísticos reales...")
    
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

        # 1. EXTRACCIÓN DE 5 PARTIDOS REALES DE LA API
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
            return res_str if res_str else "⚠️ La API no tiene historial reciente."

        historial_local = formatear_resultados(local_data)
        historial_visit = formatear_resultados(visit_data)

        # 2. IA COMO MINERO DE DATOS (FORMATO JSON OBLIGATORIO)
        prompt = f"""
        Actúa como analista de datos. Analiza estadísticamente a {home_name} y {away_name}.
        Debes responder ÚNICAMENTE con un objeto JSON válido, sin texto adicional ni bloques de código markdown.
        Si no conoces un dato exacto, estima el promedio realista de ese equipo.
        
        Formato estricto a usar:
        {{
            "corners": 9.2,
            "tarjetas": 4.5,
            "atajadas": 5.8,
            "prob_local": 45,
            "prob_visit": 30,
            "prob_empate": 25,
            "goleador_local": "Apellido Jugador",
            "goleador_visitante": "Apellido Jugador"
        }}
        """

        # Variables por defecto en caso de caída total del servidor de Google
        datos_ia = {
            "corners": 8.5, "tarjetas": 4.0, "atajadas": 5.0,
            "prob_local": 35, "prob_visit": 35, "prob_empate": 30,
            "goleador_local": "No definido", "goleador_visitante": "No definido"
        }

        url_gemini = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        try:
            res = requests.post(url_gemini, json=payload, headers={"Content-Type": "application/json"}, timeout=12).json()
            if "candidates" in res:
                texto_ia = res["candidates"][0]["content"]["parts"][0]["text"].strip()
                # Limpiamos el texto por si la IA le pone comillas de código (```json)
                texto_ia = texto_ia.replace("```json", "").replace("```", "").strip()
                
                # Convertimos el texto estricto a variables reales de Python
                datos_ia.update(json.loads(texto_ia))
        except Exception as e:
            print(f"Error procesando JSON de la IA: {e}")

        # 3. LÓGICA MATEMÁTICA
        total_prob = datos_ia["prob_local"] + datos_ia["prob_visit"] + datos_ia["prob_empate"]
        if total_prob > 0:
            p_loc = round((datos_ia["prob_local"] / total_prob) * 100)
            p_vis = round((datos_ia["prob_visit"] / total_prob) * 100)
            p_emp = 100 - (p_loc + p_vis)

        promedio_goles = round(goles_recientes / partidos_contados, 1) if partidos_contados > 0 else 2.0
        linea_goles = "Over 2.5 🔥" if promedio_goles > 2.2 else "Under 2.5 🧊"
        ambos_anotan = "Sí ⚽" if promedio_goles >= 2.0 and p_emp > 20 else "No 🚫"

        if p_loc >= 45:
            pick = f"Gana {home_name}"
            confianza = "Alta 🟢"
        elif p_vis >= 45:
            pick = f"Gana {away_name}"
            confianza = "Alta 🟢"
        else:
            pick = "Doble Oportunidad o Empate"
            confianza = "Media 🟡"

        # Si la API no trajo partidos, la confianza baja automáticamente
        if partidos_contados == 0:
            confianza = "Baja 🔴 (Sin datos oficiales API)"

        # 4. CONSTRUCCIÓN DEL REPORTE FINAL
        reporte = f"📊 **ANÁLISIS ESTADÍSTICO PRO**\n"
        reporte += f"⚽ *{home_name} vs {away_name}*\n\n"
        
        reporte += f"📈 **Probabilidades Matemáticas:**\n"
        reporte += f"🏠 Local: {p_loc}% | 🤝 Empate: {p_emp}% | ✈️ Visit: {p_vis}%\n\n"

        reporte += f"🔄 **Forma Reciente (Últimos 5 del Local):**\n{historial_local}\n"
        reporte += f"🔄 **Forma Reciente (Últimos 5 del Visitante):**\n{historial_visit}\n"
        
        reporte += f"🎯 **Líneas Calculadas para Apuestas:**\n"
        reporte += f"• Promedio Goles: {promedio_goles}\n"
        reporte += f"• Ambos Anotan: {ambos_anotan}\n"
        reporte += f"• Tiros de Esquina: Más de {datos_ia.get('corners', 8.5)}\n"
        reporte += f"• Tarjetas Totales: Más de {datos_ia.get('tarjetas', 4.0)}\n"
        reporte += f"• Atajadas (Porteros): Más de {datos_ia.get('atajadas', 5.0)}\n\n"

        reporte += f"⭐ **Jugadores Clave (Posibles Anotadores):**\n"
        reporte += f"• {home_name}: {datos_ia.get('goleador_local', 'N/A')}\n"
        reporte += f"• {away_name}: {datos_ia.get('goleador_visitante', 'N/A')}\n\n"
        
        reporte += f"💰 **PICK DEL ALGORITMO:** {pick}\n"
        reporte += f"⚡ **Confianza:** {confianza}"

        bot.send_message(call.message.chat.id, reporte, parse_mode="Markdown")

    except Exception as e:
        print(f"Error crítico: {e}")
        bot.send_message(call.message.chat.id, f"❌ Error interno procesando estadísticas.")

# ==========================================
# 5. RASTREADOR DE TEXTO LIBRE (CORREGIDO)
# ==========================================
@bot.message_handler(func=lambda message: True)
def buscar_equipo_libre(message):
    texto = message.text.lower()
    
    # Arreglamos el validador para que extraiga el nombre del equipo correctamente
    if texto.startswith("datos de "):
        equipo = message.text[9:].strip() # Corta exactamente los primeros 9 caracteres ("Datos de ")
        
        if not equipo:
            bot.reply_to(message, "Escribe el nombre del club. Ejemplo: `datos de Colombia`")
            return
            
        bot.reply_to(message, f"🌐 Buscando estadísticas y actualidad de *{equipo}*...", parse_mode="Markdown")
        
        try:
            contexto = "No hubo resultados web."
            try:
                with DDGS() as ddgs:
                    resultados = list(ddgs.text(f"{equipo} actualidad futbol ultimos partidos", max_results=2))
                    if resultados:
                        contexto = "\n".join([f"{r['title']}: {r['body']}" for r in resultados])
            except:
                pass
            
            prompt = f"Actúa como analista deportivo experto. Analiza a la selección o equipo: {equipo}. \nNoticias recientes si aplican: {contexto}. \nEscribe un perfil táctico resumido, estilo de juego, jugadores destacados actuales y recomendaciones para apuestas en Markdown."
            
            url_gemini = f"[https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=](https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=){GEMINI_KEY}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            res = requests.post(url_gemini, json=payload, headers={"Content-Type": "application/json"}, timeout=15).json()
            
            if "candidates" in res:
                respuesta_texto = res["candidates"][0]["content"]["parts"][0]["text"]
                bot.send_message(message.chat.id, respuesta_texto, parse_mode="Markdown")
            else:
                error_real = str(res.get("error", "Error desconocido de IA"))
                bot.send_message(message.chat.id, f"❌ Google IA bloqueó la respuesta. Motivo:\n`{error_real}`", parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, "❌ Error de conexión al procesar el resumen.")
if __name__ == "__main__":
    Thread(target=run_flask).start()
    print("Bot Estadístico Corriendo...")
    bot.infinity_polling()
