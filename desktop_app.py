"""Nasdaq-100 Monitor per Windows (Fase 9B): il programma che parte con il doppio clic su «Nasdaq-100 Monitor.exe».

1. crea (la prima volta) %LOCALAPPDATA%\\Nasdaq100Monitor con dati\\, cache\\, logs\\, backup\\;
2. se l'app è già aperta, le chiede di riaprire il browser ed esce;
3. accende la protezione (app_env.enable_desktop) PRIMA di caricare il resto del programma;
4. avvia il server solo su 127.0.0.1, sulla prima porta libera tra 8130 e 8149;
5. apre il browser predefinito con una chiave usa e getta;
6. mostra una piccola finestra con «Apri la dashboard» e «Chiudi Nasdaq-100 Monitor»; chiudendola (o con «Chiudi l'app»
   nella pagina) il server si ferma e il processo termina, senza lasciare nulla acceso.

Opzioni per le prove: --senza-finestra (nessuna finestra: si chiude dalla pagina), --senza-browser, --cartella DIR."""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import secrets
import sys
import threading
import traceback
import webbrowser

os.environ.setdefault("NDX_ENV", "desktop")
TITLE = "Nasdaq-100 Monitor"


def _message(text, error=True):
    """A window with the message (tkinter, or Windows' own box); on the terminal when neither is available."""
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        (messagebox.showerror if error else messagebox.showinfo)(TITLE, text)
        root.destroy()
        return
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10 if error else 0x40)
            return
        except Exception:
            pass
    print(text, file=sys.stderr if sys.stderr else sys.__stdout__)


def _logging(logs_dir):
    """Technical log in logs\\app.log (at most 3 × 1 MB). Never positions, quantities or values: the modules log only the
    kind of an error for anything personal, and the request log of the web server is off."""
    handler = logging.handlers.RotatingFileHandler(os.path.join(logs_dir, "app.log"), maxBytes=1_000_000, backupCount=2,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)      # no URLs in the log (the opening key is in one)
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    if sys.stdout is None or sys.stderr is None:                 # windowed program: no console to write to
        sink = open(os.path.join(logs_dir, "console.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or sink
        sys.stderr = sys.stderr or sink


class Window:
    """The small control window. Closing it closes the app."""

    def __init__(self, app, url_hint):
        import tkinter
        from tkinter import ttk
        self.app = app
        self.tk = tkinter.Tk()
        self.tk.title(TITLE)
        self.tk.resizable(False, False)
        frame = ttk.Frame(self.tk, padding=18)
        frame.grid()
        ttk.Label(frame, text=TITLE, font=("Segoe UI", 13, "bold")).grid(column=0, row=0, columnspan=2, sticky="w")
        ttk.Label(frame, text="La dashboard si apre nel browser (Chrome o Edge).\n"
                              "Lascia aperta questa finestra mentre la usi.", justify="left").grid(
            column=0, row=1, columnspan=2, sticky="w", pady=(6, 4))
        ttk.Label(frame, text=url_hint, foreground="#555").grid(column=0, row=2, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Button(frame, text="Apri la dashboard", command=app.open_browser).grid(column=0, row=3, sticky="ew", padx=(0, 8))
        ttk.Button(frame, text="Chiudi Nasdaq-100 Monitor", command=self.close).grid(column=1, row=3, sticky="ew")
        self.tk.protocol("WM_DELETE_WINDOW", self.close)
        self.tk.after(300, self._poll)

    def _poll(self):
        if self.app.quit.is_set():
            self.tk.destroy()
            return
        self.tk.after(300, self._poll)

    def close(self):
        from tkinter import messagebox
        if self.app.state.get("running") and not messagebox.askyesno(
                TITLE, "È in corso «Aggiorna dati». Chiudere comunque?\nI dati già salvati restano; "
                       "l'aggiornamento si potrà rifare più tardi."):
            return
        self.app.quit.set()

    def run(self):
        self.tk.mainloop()


def main(argv=None):
    args = argparse.ArgumentParser(prog="Nasdaq-100 Monitor")
    args.add_argument("--senza-finestra", action="store_true")
    args.add_argument("--senza-browser", action="store_true")
    args.add_argument("--cartella")
    a = args.parse_args(argv)
    import desktop
    try:
        base = desktop.ensure_dirs(a.cartella or desktop.default_dir())
    except Exception as e:
        (print if a.senza_finestra else _message)(f"Impossibile creare la cartella dei dati.\n\n{e}")
        return 2
    p = desktop.paths(base)
    _logging(p["logs"])
    log = logging.getLogger("app")
    if desktop.ask_running_copy(base):
        log.info("già aperta: chiesto di riaprire il browser")
        return 0
    try:
        restored = desktop.apply_pending_restore(base)  # the page says it (no window that stops the start)
        if restored:
            log.info("ripristino del backup completato")
        import app_env
        app_env.enable_desktop(base)                    # before every other import of the program
        desktop.patch_windows_replace()
        import server
        srv, port = desktop.bind_server(server.app)
        app = desktop.configure(base, port)
        app.restored = restored
        app_env.authorize("app desktop")
    except Exception as e:
        log.error("avvio non riuscito: %s", type(e).__name__)
        log.debug("%s", traceback.format_exc())
        if a.senza_finestra:
            print(f"avvio non riuscito: {e}", file=sys.stderr or sys.__stderr__)
            return 1
        _message("Nasdaq-100 Monitor non è riuscito ad avviarsi.\n\n"
                 f"Motivo: {e}\n\nRiprova; se succede ancora, invia il file:\n{os.path.join(p['logs'], 'app.log')}")
        return 1
    app.secret = secrets.token_urlsafe(32)
    url = f"http://127.0.0.1:{port}"

    def open_browser():
        key = server.INSTANCE["open_keys"].make()
        target = os.environ.get("NDX_PROVA_URL_FILE")    # automatic tests only: the address goes to a file
        if target:
            with open(target, "a", encoding="utf-8") as f:
                f.write(f"{url}/avvio?k={key}\n")
            return
        webbrowser.open(f"{url}/avvio?k={key}")
    app.open_browser = open_browser
    desktop.write_lock(base, port, app.secret)
    threading.Thread(target=srv.serve_forever, daemon=True, name="server").start()
    threading.Thread(target=app.worker, daemon=True, name="aggiornamenti").start()
    log.info("avviata su %s", url)
    if not a.senza_browser:
        open_browser()
    try:
        if a.senza_finestra:
            app.quit.wait()
        else:
            try:
                Window(app, url).run()
            except Exception as e:                      # no graphical window available: closed from the page
                log.warning("finestra non disponibile (%s): si chiude dalla pagina", type(e).__name__)
                app.quit.wait()
    except KeyboardInterrupt:
        pass
    finally:
        app.quit.set()
        srv.shutdown()
        desktop.remove_lock(base)
        log.info("chiusa")
        logging.shutdown()
    return 0


if __name__ == "__main__":
    code = main()
    try:
        sys.stdout and sys.stdout.flush()
    except Exception:
        pass
    os._exit(code)                                      # no thread left behind (downloads in progress included)
