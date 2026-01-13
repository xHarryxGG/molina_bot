import os
import re
import logging
import requests
import time
from dataclasses import dataclass
from typing import List, Tuple
import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.neighbors import NearestNeighbors
import PyPDF2
import nltk
from nltk.corpus import stopwords

# -----------------------------
# Configuración
# -----------------------------
nltk.download("stopwords")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8273092293:AAHPX4-jEtzJD82LJTBVNXc3M7uSs4UC3j0")
LMSTUDIO_URL = os.getenv("LMSTUDIO_URL", "http://127.0.0.1:1234/v1/chat/completions")
LM_MODEL_NAME = os.getenv("LM_MODEL_NAME", "google/gemma-3-1b")  
PDF_PATH = os.getenv("PDF_PATH", "aplicaciones-inteligentes-en-la-ingenieria-del-futuro.pdf")

SYSTEM_PROMPT = (
    "Eres un asistente académico. Respondes solo con base en el documento proporcionado. "
    "Si algo no está en el documento, di explícitamente que no está disponible en el material. "
    "Mantén las respuestas concisas y, cuando corresponda, indica los fragmentos utilizados."
)

# Umbral mínimo de similitud
MIN_CONTEXT_SCORE = 0.05

# -----------------------------
# Logging
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger("uni-bot")

# -----------------------------
# Intento de leer última ruta del PDF desde la base de datos local
try:
    import db as _db
    _last_pdf = _db.get_last_pdf()
    if _last_pdf and os.path.exists(_last_pdf):
        PDF_PATH = _last_pdf
        logger.info(f"PDF_PATH reemplazado por la ruta guardada en DB: {PDF_PATH}")
except Exception:
    # No es crítico: seguir con la ruta por defecto o la de env var
    pass
# -----------------------------
# Utilidades: intención simple
# -----------------------------
GREETINGS = {"hola", "holaa", "buenas", "buenos dias", "buenos días", "saludos", "hey", "hello", "hi"}
THANKS = {"gracias", "muchas gracias", "mil gracias", "thank you", "thanks"}
BYE = {"chao", "adios", "adiós", "hasta luego", "nos vemos", "bye"}

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()

def is_exact_match(text: str, phrases: set) -> bool:
    return normalize(text) in phrases

# -----------------------------
# Utilidades PDF y texto
# -----------------------------
def read_pdf_text(path: str) -> str:
    reader = PyPDF2.PdfReader(path)
    texts = []
    for i, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ""
            t = re.sub(r"\s+", " ", t).strip()
            if t:
                texts.append(f"[Página {i+1}] {t}")
        except Exception as e:
            logger.warning(f"Error leyendo página {i+1}: {e}")
    return "\n\n".join(texts)

def chunk_text(text: str, max_tokens: int = 400, overlap: int = 100) -> List[str]:
    words = text.split()
    chunk_size = max_tokens
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i+chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap
    return chunks

@dataclass
class KnowledgeBase:
    chunks: List[str]
    vectorizer: TfidfVectorizer
    matrix: any
    nn: any = None

def build_kb_from_pdf(pdf_path: str) -> KnowledgeBase:
    full_text = read_pdf_text(pdf_path)
    if not full_text:
        raise ValueError("No se pudo extraer texto del PDF. Verifica el archivo.")
    chunks = chunk_text(full_text, max_tokens=400, overlap=100)

    spanish_stopwords = stopwords.words("spanish")
    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words=spanish_stopwords,
        ngram_range=(1, 2),
        max_df=0.9,
        min_df=1,
    )
    matrix = vectorizer.fit_transform(chunks)
    # Pre-ajustar un NearestNeighbors para búsquedas rápidas (cosine)
    try:
        nn = NearestNeighbors(n_neighbors=10, metric="cosine", algorithm="brute")
        nn.fit(matrix)
    except Exception:
        nn = None
    logger.info(f"KB creada con {len(chunks)} fragmentos.")
    return KnowledgeBase(chunks=chunks, vectorizer=vectorizer, matrix=matrix, nn=nn)

def retrieve_context(kb: KnowledgeBase, query: str, k: int = 5) -> List[Tuple[int, str, float]]:
    q_vec = kb.vectorizer.transform([query])
    if kb.nn is not None:
        # NearestNeighbors returns distances (cosine distance), convert to similarity
        try:
            dists, idxs = kb.nn.kneighbors(q_vec, n_neighbors=min(k, kb.matrix.shape[0]))
            dists = dists.flatten()
            idxs = idxs.flatten()
            sims = [1.0 - float(d) for d in dists]
            results = [(int(idx), kb.chunks[int(idx)], float(sim)) for idx, sim in zip(idxs, sims)]
            return results
        except Exception:
            pass

    sims = cosine_similarity(q_vec, kb.matrix).flatten()
    top_idx = sims.argsort()[::-1][:k]
    results = [(int(i), kb.chunks[int(i)], float(sims[int(i)])) for i in top_idx]
    return results

def build_prompt(contexts: List[Tuple[int, str, float]], question: str, limit_chars: int = 3000) -> List[dict]:
    context_texts = []
    total = 0
    for idx, chunk, score in contexts:
        tag = f"[Fragmento {idx} | score {score:.3f}] "
        ct = tag + chunk
        if total + len(ct) > limit_chars:
            break
        context_texts.append(ct)
        total += len(ct)

    context_block = "\n\n".join(context_texts) if context_texts else "No se recuperó contexto relevante."
    user_message = (
        "Usa EXCLUSIVAMENTE el siguiente contexto del documento para responder.\n\n"
        f"{context_block}\n\n"
        f"Pregunta: {question}\n\n"
        "Si no está en el contexto, responde: 'No se encuentra en el material proporcionado.'"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    return messages

def call_lmstudio(messages: List[dict], temperature: float = 0.3, max_tokens: int = 300) -> str:
    payload = {
        "model": LM_MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 0.9,
        "stream": False
    }
    # Timeout configurable via env var LMSTUDIO_TIMEOUT (seconds)
    timeout = int(os.getenv("LMSTUDIO_TIMEOUT", "60"))
    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(LMSTUDIO_URL, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        except requests.exceptions.ReadTimeout as e:
            logger.exception(f"Timeout connecting to LM Studio (attempt {attempt}/{attempts}): {e}")
            if attempt == attempts:
                raise
            time.sleep(1 * attempt)
        except requests.exceptions.RequestException as e:
            logger.exception(f"Request error calling LM Studio: {e}")
            # For non-timeout request errors, don't retry many times
            raise

# -----------------------------
# Bot de Telegram
# -----------------------------
KB: KnowledgeBase = None

from collections import deque

# Evitar respuestas duplicadas: almacenar últimos updates procesados (chat_id, message_id)
_PROCESSED_DEQUE = deque(maxlen=2048)
_PROCESSED_SET = set()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bot académico cargado. Envía tu pregunta sobre la materia.\n"
        "Respondo únicamente con base en el documento."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Envía una pregunta. Ejemplo:\n"
        " - ¿Cuál es la definición formal del concepto X?\n"
        " - Explica el teorema Y y sus condiciones.\n"
        "Si no está en el PDF, te lo diré."
    )

async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global KB
    question = update.message.text.strip()

    # Dedupe: evitar responder dos veces al mismo mensaje
    try:
        chat_id = update.effective_chat.id
        msg_id = update.effective_message.message_id
        key = (chat_id, msg_id)
        if key in _PROCESSED_SET:
            logger.info(f"Ignorando mensaje duplicado: {key}")
            return
        # Evict oldest if estamos al tope
        if len(_PROCESSED_DEQUE) >= _PROCESSED_DEQUE.maxlen:
            old = _PROCESSED_DEQUE.popleft()
            _PROCESSED_SET.discard(old)
        _PROCESSED_DEQUE.append(key)
        _PROCESSED_SET.add(key)
    except Exception:
        # Si algo falla en la deduplicación, seguir de todas formas
        pass
    if not question:
        await update.message.reply_text("Escribe una pregunta válida.")
        return

    # Si la KB no está cargada, intentar construirla (bloqueante) en un executor
    if KB is None:
        logger.warning("KB no está cargada en memoria. Intentando construir desde PDF...")
        pdf_path = os.getenv("PDF_PATH", PDF_PATH)
        if not os.path.exists(pdf_path):
            await update.message.reply_text("La base de conocimiento no está cargada y no se encontró el PDF para construirla.")
            return
        try:
            loop = asyncio.get_running_loop()
            KB = await loop.run_in_executor(None, build_kb_from_pdf, pdf_path)
            logger.info("KB reconstruida dinámicamente desde PDF.")
        except Exception as e:
            logger.exception("Error construyendo KB dinámicamente")
            await update.message.reply_text(f"Error construyendo la base de conocimiento: {e}")
            return

    # Respuestas rápidas exactas
    if is_exact_match(question, GREETINGS):
        await update.message.reply_text("¡Hola! Soy tu asistente académico. Pregúntame sobre el material del PDF cuando quieras.")
        return
    if is_exact_match(question, THANKS):
        await update.message.reply_text("¡Con gusto! Si necesitas algo más del material, aquí estoy.")
        return
    if is_exact_match(question, BYE):
        await update.message.reply_text("¡Hasta luego! Cuando quieras retomamos.")
        return

    # Recuperación basada en PDF
    contexts = retrieve_context(KB, question, k=10)
    max_score = max([score for _, _, score in contexts], default=0.0)

    # Con umbral bajo, casi siempre se pasa al modelo
    if max_score < MIN_CONTEXT_SCORE:
        logger.info("Contexto débil, pero se enviará al modelo igualmente.")

    messages = build_prompt(contexts, question, limit_chars=7000)

    try:
        # longitud máxima de la respuesta en caracteres (configurable)
        max_reply_chars = int(os.getenv("MAX_REPLY_CHARS", "1000"))
        answer = call_lmstudio(messages, temperature=0.3, max_tokens=300)
        if answer and len(answer) > max_reply_chars:
            # intentar cortar en el último punto para no romper frases
            truncated = answer[:max_reply_chars]
            if "." in truncated:
                truncated = truncated.rsplit('.', 1)[0] + '.'
            answer = truncated + "\n\n[Respuesta truncada por longitud]"
    except Exception as e:
        logger.exception("Error llamando al modelo")
        await update.message.reply_text(f"Error llamando al modelo: {e}")
        return

    refs = "\n".join([f"- Fragmento {idx} (score {score:.3f})" for idx, _, score in contexts])
    reply = f"{answer}\n\nReferencias usadas:\n{refs}"
    await update.message.reply_text(reply, parse_mode=ParseMode.HTML)

def main():
    global KB
    if not os.path.exists(PDF_PATH):
        raise FileNotFoundError(f"No se encuentra el PDF en {PDF_PATH}")

    logger.info("Construyendo base de conocimiento desde el PDF...")
    KB = build_kb_from_pdf(PDF_PATH)

    logger.info("Levantando bot de Telegram...")
    if TELEGRAM_TOKEN.startswith("REEMPLAZA"):
        raise ValueError("Debes configurar TELEGRAM_TOKEN en variables de entorno.")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), ask))

    logger.info("Bot en ejecución. Ctrl+C para salir.")
    app.run_polling()

def set_kb(kb: KnowledgeBase):
    global KB
    KB = kb

def build_and_set_kb_from_pdf(pdf_path: str) -> KnowledgeBase:
    kb = build_kb_from_pdf(pdf_path)
    set_kb(kb)
    return kb

if __name__ == "__main__":
    main()
