import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

API_TOKEN = "7149113195:AAFZ_M_6PWhKke4xK01ZHiYiPrG7yz-RvIc"
MODEL_URL = "http://localhost:1234/v1/chat/completions"  
async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    await update.message.chat.send_action("typing")

    payload = {
        "model": "tu_modelo",  # cambia por el nombre de tu modelo en LM Studio
        "messages": [{"role": "user", "content": user_message}]
    }

    try:
        response = requests.post(MODEL_URL, json=payload)
        data = response.json()

        # Manejo flexible de estructura
        if "choices" in data:
            reply = data["choices"][0]["message"]["content"]
        elif "content" in data:
            reply = data["content"]
        elif "response" in data:
            reply = data["response"]
        else:
            reply = f"⚠️ No entendí la respuesta del modelo: {data}"

    except Exception as e:
        reply = f"❌ Error al conectar con el modelo: {e}"

    await update.message.reply_text(reply)

if __name__ == "__main__":
    print("🤖 Bot corriendo...")
    app = ApplicationBuilder().token(API_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    app.run_polling()

