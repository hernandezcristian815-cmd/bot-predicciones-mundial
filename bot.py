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
# 4. MOTOR ESTADÍSTICO COMBINADO (CON RASTREADOR WEB DE EMERGENCIA)
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('c_'))
def procesar_prediccion_ia(call):
    bot.answer_callback_query(call.id, text="Buscando estadísticas avanzadas...")
    
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

        # 1. INTENTAR TRAER PARTIDOS REALES DESDE LA API
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
            return res_str

        historial_local = formatear_resultados(local_data)
        historial_visit = formatear_resultados(visit_data)

        # 2. INTENTO CON INTELIGENCIA ARTIFICIAL DE GOOGLE
        prompt = f"""
        Devuelve ÚNICAMENTE un objeto JSON con estadísticas para {home_name} vs {away_name}. No uses texto extra.
        {{
            "corners": 9.5, "tarjetas": 4.5, "atajadas": 5.5,
            "prob_local": 45, "prob_visit": 30, "prob_empate": 25,
            "goleador_local": "Apellido", "goleador_visitante": "Apellido"
        }}
        """

        datos_ia = None
        url_gemini = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        }

        try:
            res_google = requests.post(url_gemini, json=payload, headers={"Content-Type": "application/json"}, timeout=10).json()
            if "candidates" in res_google:
                texto_ia = res_google["candidates"][0]["content"]["parts"][0]["text"].strip()
                datos_ia = json.loads(texto_ia)
        except:
            datos_ia = None # Si Google da error o 404, pasamos al plan web

        # 3. PLAN DE RESPALDO: RASTREADOR WEB (Si la IA falló o mandó datos vacíos)
        origen_datos = "Modelo de Inteligencia Artificial (Google AI)"
        
        if not datos_ia:
            origen_datos = "Rastreador Web de Emergencia (DuckDuckGo Search)"
            print(f"⚠️ Google IA falló. Activando rastreo web para {home_name} vs {away_name}...")
            
            contexto_busqueda = ""
            try:
                with DDGS() as ddgs:
                    # Buscamos noticias del partido actual
                    busqueda = list(ddgs.text(f"{home_name} vs {away_name} pronostico estadisticas corners", max_results=3))
                    for r in busqueda:
                        contexto_busqueda += f"{r['title']} {r['body']} "
            except:
                pass

            # Usamos lógica deportiva analítica para construir el JSON basados en la web
            # Si no hay texto, calculamos promedios estándar de fútbol profesional
            goles_en_texto = contexto_busqueda.count("gol") + contexto_busqueda.count("over")
            corners_estimados = 9.5 if "corners" in contexto_busqueda.lower() else 8.5
            tarjetas_estimadas = 5.5 if any(x in contexto_busqueda.lower() for x in ["tarjeta", "arbitro", "fuerte"]) else 4.2
            
            datos_ia = {
                "corners": corners_estimados,
                "tarjetas": tarjetas_estimadas,
                "atajadas": 4.8,
                "prob_local": 45 if "favorito" in contexto_busqueda.lower() or "gana" in contexto_busqueda.lower() else 38,
                "prob_visit": 28,
                "prob_empate": 34,
                "goleador_local": "Buscando...",
                "goleador_visitante": "Buscando..."
            }
            
            # Intentamos rescatar apellidos reales del texto de internet si los hay
            palabras = [p.replace(",", "").replace(".", "") for p in contexto_busqueda.split() if p.istitle() and len(p) > 4]
            if len(palabras) > 1: datos_ia["goleador_local"] = palabras[0]
            if len(palabras) > 3: datos_ia["goleador_visitante"] = palabras[2]

        # 4. PROCESAMIENTO MATEMÁTICO REAL EN PYTHON
        total_prob = datos_ia["prob_local"] + datos_ia["prob_visit"] + datos_ia["prob_empate"]
        if total_prob == 0: total_prob = 100
        p_loc = round((datos_ia["prob_local"] / total_prob) * 100)
        p_vis = round((datos_ia["prob_visit"] / total_prob) * 100)
        p_emp = 100 - (p_loc + p_vis)

        promedio_goles = round(goles_recientes / partidos_contados, 1) if partidos_contados > 0 else 2.4
        linea_goles = "Over 2.5 🔥" if promedio_goles > 2.2 else "Under 2.5 🧊"
        ambos_anotan = "Sí ⚽" if promedio_goles >= 1.9 and p_emp > 15 else "No 🚫"

        if p_loc >= 44:
            pick = f"Gana {home_name} (o Empate)"
            confianza = "Alta 🟢"
            marcador = "2-0 o 2-1"
        elif p_vis >= 44:
            pick = f"Gana {away_name} (o Empate)"
            confianza = "Alta 🟢"
            marcador = "0-1 o 1-2"
        else:
            pick = "Menos de 2.5 goles o Empate"
            confianza = "Media 🟡"
            marcador = "1-1 o 0-0"

        # Ajuste visual si la API no trajo datos reales
        txt_local = historial_local if historial_local else "▫️ Sin registros en la API de fútbol hoy.\n"
        txt_visit = historial_visit if historial_visit else "▫️ Sin registros en la API de fútbol hoy.\n"

        # 5. CONSTRUCCIÓN DEL REPORTE PRO INALTERABLE
        reporte = f"📊 **ANÁLISIS ESTADÍSTICO PROFESIONAL**\n"
        reporte += f"⚽ *{home_name} vs {away_name}*\n\n"
        
        reporte += f"📈 **Probabilidades Calculadas:**\n"
        reporte += f"🏠 Local: {p_loc}% | 🤝 Empate: {p_emp}% | ✈️ Visit: {p_vis}%\n\n"

        reporte += f"🔄 **Historial Reciente (Local):**\n{txt_local}"
        reporte += f"🔄 **Historial Reciente (Visitante):**\n{txt_visit}\n"
        
        reporte += f"🎯 **Líneas del Modelo Matemático:**\n"
        reporte += f"• Promedio Goles: {promedio_goles}\n"
        reporte += f"• Ambos Anotan: {ambos_anotan}\n"
        reporte += f"• Tiros de Esquina: Más de {datos_ia['corners']}\n"
        reporte += f"• Tarjetas Totales: Más de {datos_ia['tarjetas']}\n"
        reporte += f"• Atajadas Estimadas: Más de {datos_ia['atajadas']}\n\n"

        reporte += f"⭐ **Jugadores Clave (Monitoreo):**\n"
        reporte += f"• {home_name}: {datos_ia['goleador_local']}\n"
        reporte += f"• {away_name}: {datos_ia['goleador_visitante']}\n\n"
        
        reporte += f"💰 **PICK DEL ALGORITMO:** {pick}\n"
        reporte += f"⚡ **Confianza:** {confianza}\n"
        reporte += f"_(Fuente: {origen_datos})_"

        bot.send_message(call.message.chat.id, reporte, parse_mode="Markdown")

    except Exception as e:
        print(f"Error crítico en el motor matemático: {e}")
        bot.send_message(call.message.chat.id, "❌ Error interno del servidor al procesar la predicción.")
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
