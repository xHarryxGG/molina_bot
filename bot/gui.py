import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog
import threading
import logging
import sys
import os
import json
from pathlib import Path
import asyncio
import main

# Configurar CustomTkinter
ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"

class LogHandler(logging.Handler):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)
        self.text_widget.insert(tk.END, msg + '\n')
        self.text_widget.see(tk.END)

class BotGUI:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("Bot Académico GUI")
        self.root.geometry("600x500")

        # Variables
        self.config_path = Path("config.json")
        self.pdf_path = ctk.StringVar(value=self.load_config().get("pdf_path", "aplicaciones-inteligentes-en-la-ingenieria-del-futuro.pdf"))
        self.bot_thread = None
        self.stop_event = threading.Event()
        self.app = None

        # Crear widgets
        self.create_widgets()

        # Configurar logging
        self.setup_logging()

    def create_widgets(self):
        # Frame principal
        main_frame = ctk.CTkFrame(self.root)
        main_frame.pack(pady=20, padx=20, fill="both", expand=True)

        # Título
        title_label = ctk.CTkLabel(main_frame, text="Bot Académico", font=ctk.CTkFont(size=24, weight="bold"))
        title_label.pack(pady=10)

        # Selección de PDF
        pdf_frame = ctk.CTkFrame(main_frame)
        pdf_frame.pack(pady=10, padx=10, fill="x")

        pdf_label = ctk.CTkLabel(pdf_frame, text="Archivo PDF:")
        pdf_label.pack(side="left", padx=10)

        self.pdf_entry = ctk.CTkEntry(pdf_frame, textvariable=self.pdf_path, width=300)
        self.pdf_entry.pack(side="left", padx=10)

        browse_button = ctk.CTkButton(pdf_frame, text="Buscar", command=self.browse_pdf)
        browse_button.pack(side="left", padx=10)

        save_button = ctk.CTkButton(pdf_frame, text="Guardar", command=self.save_config)
        save_button.pack(side="left", padx=10)

        # Botones de control
        button_frame = ctk.CTkFrame(main_frame)
        button_frame.pack(pady=10, padx=10, fill="x")

        self.start_button = ctk.CTkButton(button_frame, text="Iniciar Bot", command=self.start_bot)
        self.start_button.pack(side="left", padx=10)

        self.stop_button = ctk.CTkButton(button_frame, text="Detener Bot", state="disabled", command=self.stop_bot)
        self.stop_button.pack(side="left", padx=10)

        # Área de logs
        log_label = ctk.CTkLabel(main_frame, text="Logs:")
        log_label.pack(pady=5)

        self.log_text = ctk.CTkTextbox(main_frame, wrap="word", height=200)
        self.log_text.pack(pady=5, padx=10, fill="both", expand=True)

    def setup_logging(self):
        logger = logging.getLogger("uni-bot")
        logger.setLevel(logging.INFO)
        handler = LogHandler(self.log_text)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        # También capturar stdout y stderr si es necesario
        # Pero por ahora, solo logging

    def browse_pdf(self):
        file_path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if file_path:
            self.pdf_path.set(file_path)

    def load_config(self) -> dict:
        try:
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            logging.getLogger("uni-bot").warning("No se pudo leer config.json, usando valores por defecto.")
        return {}

    def save_config(self):
        pdf = self.pdf_path.get()
        logger = logging.getLogger("uni-bot")
        if not pdf:
            logger.error("Ruta PDF vacía — no se guardó la configuración.")
            return
        try:
            data = {"pdf_path": pdf}
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Ruta PDF guardada en {self.config_path}: {pdf}")
        except Exception as e:
            logger.exception(f"Error guardando config: {e}")

    def start_bot(self):
        pdf_path = self.pdf_path.get()
        if not os.path.exists(pdf_path):
            self.log_text.insert(tk.END, f"Error: El archivo PDF '{pdf_path}' no existe.\n")
            return

        if self.bot_thread and self.bot_thread.is_alive():
            logging.getLogger("uni-bot").info("El bot ya se está ejecutando en otro hilo.")
            return

        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.stop_event.clear()

        self.bot_thread = threading.Thread(target=self.run_bot, args=(pdf_path,))
        self.bot_thread.start()

    def run_bot(self, pdf_path):
        # usaremos las funciones del módulo main para mantener la KB en el módulo correcto
        try:
            logger = logging.getLogger("uni-bot")
            logger.info("Construyendo base de conocimiento desde el PDF...")
            # Construir y establecer la KB dentro del módulo main
            try:
                kb = main.build_kb_from_pdf(pdf_path)
                main.set_kb(kb)
            except Exception as e:
                logger.exception(f"Error construyendo KB: {e}")
                raise
            logger.info("KB creada exitosamente en main module.")

            logger.info("Levantando bot de Telegram...")
            if main.TELEGRAM_TOKEN.startswith("REEMPLAZA"):
                raise ValueError("Debes configurar TELEGRAM_TOKEN en variables de entorno.")

            self.app = main.ApplicationBuilder().token(main.TELEGRAM_TOKEN).build()
            self.app.add_handler(main.CommandHandler("start", main.start))
            self.app.add_handler(main.CommandHandler("help", main.help_cmd))
            self.app.add_handler(main.MessageHandler(main.filters.TEXT & (~main.filters.COMMAND), main.ask))

            logger.info("Bot en ejecución. Ctrl+C para salir.")
            # Crear y asignar un event loop en este hilo; necesario para python-telegram-bot
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # run_polling usará el loop actual
                self.app.run_polling(poll_interval=1)
            except Exception as e:
                if self.stop_event.is_set():
                    pass
                logger.exception(f"Error en polling: {e}")
            finally:
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                try:
                    loop.close()
                except Exception:
                    pass
                asyncio.set_event_loop(None)
        except Exception as e:
            logger.exception(f"Error iniciando bot: {e}")
        finally:
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")

    def stop_bot(self):
        if self.app:
            try:
                self.app.stop()
            except:
                pass
        self.stop_event.set()
        if self.bot_thread:
            self.bot_thread.join(timeout=5)
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        logging.getLogger("uni-bot").info("Bot detenido.")

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    gui = BotGUI()
    gui.run()
