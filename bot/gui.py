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
import db
from telegram.error import Conflict

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
        # Leer primero desde la DB (si existe), si no, usar config.json o valor por defecto
        db_pdf = None
        try:
            db_pdf = db.get_last_pdf()
        except Exception:
            db_pdf = None

        initial_pdf = db_pdf or self.load_config().get("pdf_path", "aplicaciones-inteligentes-en-la-ingenieria-del-futuro.pdf")
        self.pdf_path = ctk.StringVar(value=initial_pdf)
        self.bot_thread = None
        self.stop_event = threading.Event()
        self.app = None

        # Crear widgets
        self.create_widgets()

        # Configurar logging
        self.setup_logging()

    def create_widgets(self):
        # Barra superior (menú con estilo CustomTkinter)
        toolbar = ctk.CTkFrame(self.root, height=40)
        toolbar.pack(fill="x")

        # Botón de menú (usar un icono tipo 'hamburger' en vez de la palabra MENU)
        self.menu_button = ctk.CTkButton(toolbar, text="☰", width=40, height=28, command=self.toggle_popup_menu)
        self.menu_button.pack(side="left", padx=20, pady=6)

        # Contenedor principal debajo de la barra

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

    def open_advanced_options(self):
        win = ctk.CTkToplevel(self.root)
        win.title("Opciones avanzadas")
        win.geometry("520x320")
        # Make modal and stay on top
        try:
            win.transient(self.root)
            win.grab_set()
            win.lift()
            win.focus_force()
            win.attributes("-topmost", True)
        except Exception:
            pass

        # Valores iniciales: preferir DB, luego atributos en main, luego env/defaults
        try:
            token = db.get_kv("telegram_token") or getattr(main, "TELEGRAM_TOKEN", "")
        except Exception:
            token = getattr(main, "TELEGRAM_TOKEN", "")
        try:
            lm_url = db.get_kv("lmstudio_url") or getattr(main, "LMSTUDIO_URL", "http://127.0.0.1:1234/v1/chat/completions")
        except Exception:
            lm_url = getattr(main, "LMSTUDIO_URL", "http://127.0.0.1:1234/v1/chat/completions")
        try:
            lm_model = db.get_kv("lm_model_name") or getattr(main, "LM_MODEL_NAME", "google/gemma-3-1b")
        except Exception:
            lm_model = getattr(main, "LM_MODEL_NAME", "google/gemma-3-1b")
        try:
            pdf = db.get_kv("last_pdf") or self.pdf_path.get()
        except Exception:
            pdf = self.pdf_path.get()

        # Campos
        pad = 8
        lbl_token = ctk.CTkLabel(win, text="Telegram Token:")
        lbl_token.pack(anchor="w", padx=12, pady=(12, 0))
        entry_token = ctk.CTkEntry(win, width=480)
        entry_token.insert(0, token)
        entry_token.pack(padx=12, pady=(0, pad))

        lbl_url = ctk.CTkLabel(win, text="LM Studio URL:")
        lbl_url.pack(anchor="w", padx=12)
        entry_url = ctk.CTkEntry(win, width=480)
        entry_url.insert(0, lm_url)
        entry_url.pack(padx=12, pady=(0, pad))

        lbl_model = ctk.CTkLabel(win, text="Nombre del modelo:")
        lbl_model.pack(anchor="w", padx=12)
        entry_model = ctk.CTkEntry(win, width=480)
        entry_model.insert(0, lm_model)
        entry_model.pack(padx=12, pady=(0, pad))

        lbl_pdf = ctk.CTkLabel(win, text="Archivo PDF:")
        lbl_pdf.pack(anchor="w", padx=12)
        frame_pdf = ctk.CTkFrame(win)
        frame_pdf.pack(fill="x", padx=12, pady=(0, pad))
        entry_pdf = ctk.CTkEntry(frame_pdf, width=360)
        entry_pdf.insert(0, pdf)
        entry_pdf.pack(side="left", padx=(0, 8), pady=8)

        def browse_local_pdf():
            p = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
            if p:
                entry_pdf.delete(0, tk.END)
                entry_pdf.insert(0, p)

        btn_browse = ctk.CTkButton(frame_pdf, text="Buscar", command=browse_local_pdf)
        btn_browse.pack(side="left", pady=8)

        def save_advanced():
            new_token = entry_token.get().strip()
            new_url = entry_url.get().strip()
            new_model = entry_model.get().strip()
            new_pdf = entry_pdf.get().strip()

            try:
                db.set_kv("telegram_token", new_token)
                db.set_kv("lmstudio_url", new_url)
                db.set_kv("lm_model_name", new_model)
                db.set_kv("last_pdf", new_pdf)
            except Exception as e:
                logging.getLogger("uni-bot").exception(f"Error guardando opciones en DB: {e}")
            # Actualizar valores en main y en la GUI
            try:
                main.TELEGRAM_TOKEN = new_token
                main.LMSTUDIO_URL = new_url
                main.LM_MODEL_NAME = new_model
            except Exception:
                pass
            try:
                self.pdf_path.set(new_pdf)
            except Exception:
                pass

            logging.getLogger("uni-bot").info("Opciones avanzadas guardadas.")
            win.destroy()

        btn_save = ctk.CTkButton(win, text="Guardar", command=save_advanced)
        btn_save.pack(pady=(0, 12))

    def show_about(self):
        msg = "Bot Académico\nDesarrollado por el equipo: Los Mancos UGMA.\nContacto: harryjose.sp777@gmail.com"
        try:
            win = ctk.CTkToplevel(self.root)
            win.title("Sobre nosotros")
            win.geometry("360x140")
            try:
                win.transient(self.root)
                win.grab_set()
                win.lift()
                win.focus_force()
                win.attributes("-topmost", True)
            except Exception:
                pass
            lbl = ctk.CTkLabel(win, text=msg)
            lbl.pack(padx=12, pady=12)
            btn = ctk.CTkButton(win, text="Cerrar", command=win.destroy)
            btn.pack(pady=(0, 12))
        except Exception:
            logging.getLogger("uni-bot").info(msg)

    def exit_app(self):
        # Intentar detener el bot antes de salir
        try:
            self.stop_bot()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            os._exit(0)

    def toggle_popup_menu(self):
        # Si el popup ya existe, cerrarlo
        if hasattr(self, "_popup") and self._popup is not None:
            try:
                self._popup.destroy()
            except Exception:
                pass
            self._popup = None
            return

        # Crear popup estilo CTk
        popup = ctk.CTkToplevel(self.root)
        popup.overrideredirect(True)
        popup.geometry("200x120")
        # posicionar debajo del botón
        try:
            bx = self.menu_button.winfo_rootx()
            by = self.menu_button.winfo_rooty() + self.menu_button.winfo_height()
            popup.geometry(f"+{bx}+{by}")
        except Exception:
            pass

        frame = ctk.CTkFrame(popup)
        frame.pack(fill="both", expand=True)

        # colores según el modo de apariencia
        mode = ctk.get_appearance_mode()
        if mode == "Dark":
            sep_color = "#FFFFFF"  # blanco sobre fondo oscuro
            hover_color = "#505050"  # contraste más visible
        else:
            sep_color = "#C0C0C0"  # gris claro visible en modo claro
            hover_color = "#D9D9D9"  # contraste más visible en claro

        def make_row(text, command):
            # altura fija y no propagar para que ocupe bien el espacio
            row = ctk.CTkFrame(frame, height=25, fg_color=None)
            row.pack(fill="x", padx=4, pady=5)
            row.pack_propagate(False)
            lbl = ctk.CTkLabel(row, text=text, anchor="w")
            lbl.pack(fill="both", padx=12)

            # Capturar color original del row (puede variar según tema)
            try:
                normal_color = row.cget("fg_color")
            except Exception:
                normal_color = None

            def on_enter(e):
                try:
                    row.configure(fg_color=hover_color)
                except Exception:
                    pass

            def on_leave(e):
                try:
                    row.configure(fg_color=normal_color)
                except Exception:
                    pass

            row.bind("<Enter>", on_enter)
            row.bind("<Leave>", on_leave)
            lbl.bind("<Enter>", on_enter)
            lbl.bind("<Leave>", on_leave)

            def on_click(e=None):
                try:
                    command()
                finally:
                    try:
                        popup.destroy()
                    except Exception:
                        pass

            row.bind("<Button-1>", on_click)
            lbl.bind("<Button-1>", on_click)
            return row

        make_row("Opciones avanzadas", self.open_advanced_options)
        sep1 = ctk.CTkFrame(frame, height=1, fg_color=sep_color)
        sep1.pack(fill="x", padx=8, pady=(0, 0))
        make_row("Sobre nosotros", self.show_about)
        sep2 = ctk.CTkFrame(frame, height=1, fg_color=sep_color)
        sep2.pack(fill="x", padx=8, pady=(0, 0))
        make_row("Salir", self.exit_app)

        # cerrar al perder foco
        popup.bind("<FocusOut>", lambda e: popup.destroy())
        popup.focus_force()
        self._popup = popup

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
            try:
                db.set_last_pdf(pdf)
                logger.info("Ruta PDF guardada en la base de datos interna.")
            except Exception as e:
                logger.warning(f"No se pudo guardar la ruta en la DB: {e}")
        except Exception as e:
            logger.exception(f"Error guardando config: {e}")

    def start_bot(self):
        pdf_path = self.pdf_path.get()
        if not os.path.exists(pdf_path):
            self.log_text.insert(tk.END, f"Error: El archivo PDF '{pdf_path}' no existe.\n")
            return

        # Persistir la ruta seleccionada en la DB al iniciar el bot
        try:
            db.set_last_pdf(pdf_path)
            logging.getLogger("uni-bot").info("Ruta PDF guardada en la DB al iniciar el bot.")
        except Exception:
            logging.getLogger("uni-bot").warning("No se pudo guardar la ruta en la DB al iniciar.")

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
            except Conflict as e:
                # Error 409 de Telegram: otra instancia está haciendo getUpdates
                msg = (
                    "Conflict de Telegram (409): otra instancia está usando getUpdates. "
                    "Asegúrate de detener otras ejecuciones del bot o reinicia el proceso."
                )
                logger.error(msg)
                try:
                    self.log_text.insert(tk.END, msg + "\n")
                    self.log_text.see(tk.END)
                except Exception:
                    pass
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
            # Asegurarnos de limpiar referencias al finalizar el hilo
            try:
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
            except Exception:
                pass
            # El hilo terminó, permitir reinicio
            self.bot_thread = None
            self.app = None

    def stop_bot(self):
        if self.app:
            try:
                self.app.stop()
            except:
                pass
        self.stop_event.set()
        if self.bot_thread:
            # Esperar un poco más a que el hilo termine, pero no bloquear indefinidamente
            self.bot_thread.join(timeout=10)
        # Aunque el hilo siga vivo por alguna razón, limpiar la referencia para permitir reinicio
        try:
            if self.bot_thread and self.bot_thread.is_alive():
                logging.getLogger("uni-bot").warning("El hilo del bot sigue vivo tras intentar detenerlo; se permitirá reinicio.")
        except Exception:
            pass
        self.bot_thread = None
        self.app = None
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        logging.getLogger("uni-bot").info("Bot detenido.")

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    gui = BotGUI()
    gui.run()
