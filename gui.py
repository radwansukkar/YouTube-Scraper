"""Tkinter front-end for the YouTube scraper."""
from __future__ import annotations

import os
import platform
import queue
import subprocess
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from scraper import ScrapeConfig, Video, scrape
from storage import build_filename, save_csv

RED, RED_DARK, BG = "#c4302b", "#a82622", "#f5f5f7"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("YouTube Scraper")
        self.geometry("980x700")
        self.minsize(860, 620)
        self.configure(bg=BG)

        self.events: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.running = False
        self.target = 0
        self.links: dict[str, str] = {}

        self.keyword = tk.StringVar()
        self.count = tk.StringVar(value="20")
        self.filter = tk.StringVar()
        self.filename = tk.StringVar()
        self.out_dir = tk.StringVar(value=str(Path.home() / "Documents" / "YouTubeScraper"))
        self.headless = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Ready")
        self.progress_text = tk.StringVar(value="0 / 0")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, font=("Segoe UI", 10))
        style.configure("TLabelframe", background=BG)
        style.configure("TLabelframe.Label", background=BG, font=("Segoe UI", 10, "bold"))
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"), foreground=RED)
        style.configure("Sub.TLabel", foreground="#666666")
        style.configure("Hint.TLabel", foreground="#888888", font=("Segoe UI", 9))
        style.configure("TButton", padding=(14, 8))
        style.configure("Accent.TButton", background=RED, foreground="white",
                        font=("Segoe UI", 10, "bold"), padding=(18, 8), borderwidth=0)
        style.map("Accent.TButton",
                  background=[("disabled", "#d0d0d0"), ("active", RED_DARK)],
                  foreground=[("disabled", "#888888")])
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure("Horizontal.TProgressbar", troughcolor="#e2e2e2", background=RED)

        # Status bar first, so it always stays visible at the bottom
        ttk.Label(self, textvariable=self.status, anchor="w",
                  relief="sunken", padding=(10, 4)).pack(side="bottom", fill="x")

        header = ttk.Frame(self, padding=(20, 16, 20, 0))
        header.pack(fill="x")
        ttk.Label(header, text="YouTube Scraper", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="Search YouTube, filter the results and export them to CSV.",
                  style="Sub.TLabel").pack(anchor="w")

        box = ttk.LabelFrame(self, text="Search settings", padding=14)
        box.pack(fill="x", padx=20, pady=12)
        box.columnconfigure(1, weight=1)
        box.columnconfigure(3, weight=1)

        ttk.Label(box, text="Keyword").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=6)
        entry = ttk.Entry(box, textvariable=self.keyword)
        entry.grid(row=0, column=1, sticky="ew", pady=6)
        entry.bind("<Return>", lambda _e: self._start())
        entry.focus_set()

        ttk.Label(box, text="Videos").grid(row=0, column=2, sticky="w", padx=(20, 8))
        ttk.Spinbox(box, from_=1, to=500, textvariable=self.count, width=8).grid(
            row=0, column=3, sticky="w")

        ttk.Label(box, text="Title filter").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=6)
        ttk.Entry(box, textvariable=self.filter).grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Label(box, text="File name").grid(row=1, column=2, sticky="w", padx=(20, 8))
        ttk.Entry(box, textvariable=self.filename).grid(row=1, column=3, sticky="ew")

        ttk.Label(box, text="Save to").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=6)
        ttk.Entry(box, textvariable=self.out_dir).grid(row=2, column=1, columnspan=2,
                                                       sticky="ew", pady=6)
        ttk.Button(box, text="Browse...", command=self._browse).grid(
            row=2, column=3, sticky="w", padx=(10, 0))

        ttk.Checkbutton(box, text="Run Chrome in background (headless)",
                        variable=self.headless).grid(row=3, column=1, sticky="w", pady=(6, 0))
        ttk.Label(box, text="Empty file name = keyword + timestamp",
                  style="Hint.TLabel").grid(row=3, column=2, columnspan=2, sticky="w",
                                            padx=(20, 0), pady=(6, 0))

        bar = ttk.Frame(self, padding=(20, 0))
        bar.pack(fill="x")
        self.btn_start = ttk.Button(bar, text="▶  Start scraping", style="Accent.TButton",
                                    command=self._start)
        self.btn_stop = ttk.Button(bar, text="■  Stop", command=self._stop, state="disabled")
        self.btn_start.pack(side="left")
        self.btn_stop.pack(side="left", padx=10)
        ttk.Button(bar, text="Open folder", command=self._open_folder).pack(side="left")

        prog = ttk.Frame(self, padding=(20, 12, 20, 0))
        prog.pack(fill="x")
        self.progress = ttk.Progressbar(prog, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        ttk.Label(prog, textvariable=self.progress_text, width=12, anchor="e").pack(
            side="left", padx=(10, 0))

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=20, pady=12)

        results = ttk.Frame(notebook)
        notebook.add(results, text="Results (double-click to open)")
        columns = {"title": ("Title", 400), "channel": ("Channel", 150),
                   "views": ("Views", 110), "published": ("Published", 110),
                   "duration": ("Duration", 70)}
        self.tree = ttk.Treeview(results, columns=list(columns), show="headings")
        for key, (label, width) in columns.items():
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w", stretch=(key == "title"))
        scroll = ttk.Scrollbar(results, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._open_link)

        logs = ttk.Frame(notebook)
        notebook.add(logs, text="Log")
        self.log_box = tk.Text(logs, state="disabled", wrap="word", height=8,
                               font=("Consolas", 10), bg="white", relief="flat")
        log_scroll = ttk.Scrollbar(logs, orient="vertical", command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=log_scroll.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    # ------------------------------------------------------------- actions
    def _browse(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.out_dir.get() or None)
        if folder:
            self.out_dir.set(folder)

    def _open_folder(self) -> None:
        folder = Path(self.out_dir.get())
        folder.mkdir(parents=True, exist_ok=True)
        system = platform.system()
        if system == "Windows":
            os.startfile(folder)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def _open_link(self, _event) -> None:
        link = self.links.get(self.tree.focus())
        if link:
            webbrowser.open(link)

    def _start(self) -> None:
        if self.running:
            return
        keyword = self.keyword.get().strip()
        if not keyword:
            messagebox.showwarning("Missing keyword", "Please enter a keyword.")
            return
        try:
            target = int(self.count.get())
        except ValueError:
            target = 0
        if not 1 <= target <= 500:
            messagebox.showwarning("Invalid number", "Videos must be a number between 1 and 500.")
            return

        config = ScrapeConfig(keyword=keyword, target=target,
                              filter_word=self.filter.get(), headless=self.headless.get())
        self.target = target
        self.stop_event = threading.Event()
        self.tree.delete(*self.tree.get_children())
        self.links.clear()
        self.progress.configure(maximum=target, value=0)
        self.progress_text.set(f"0 / {target}")
        self._set_running(True)
        self.status.set("Working...")

        self.worker = threading.Thread(
            target=self._run,
            args=(config, self.out_dir.get(), self.filename.get()),
            daemon=True,
        )
        self.worker.start()
        self.after(100, self._poll)

    def _stop(self) -> None:
        self.stop_event.set()
        self.btn_stop.configure(state="disabled")
        self.status.set("Stopping...")

    def _set_running(self, running: bool) -> None:
        self.running = running
        self.btn_start.configure(state="disabled" if running else "normal")
        self.btn_stop.configure(state="normal" if running else "disabled")

    # ---------------------------------------------------- background thread
    def _run(self, config: ScrapeConfig, folder: str, custom_name: str) -> None:
        collected: list[Video] = []
        error: Exception | None = None

        def on_video(video: Video, count: int) -> None:
            collected.append(video)
            self.events.put(("video", video, count))

        try:
            scrape(config, on_log=lambda m: self.events.put(("log", m)),
                   on_video=on_video, stop_event=self.stop_event)
        except Exception as exc:  # thread boundary: report anything to the UI
            error = exc

        path = None
        if collected:  # save partial results even after a stop or an error
            try:
                path = save_csv(collected, folder, build_filename(config.keyword, custom_name))
            except OSError as exc:
                error = error or exc
        self.events.put(("finished", path, len(collected), error, self.stop_event.is_set()))

    # ---------------------------------------------------------- UI updates
    def _poll(self) -> None:
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        if self.running:
            self.after(100, self._poll)

    def _handle(self, event: tuple) -> None:
        kind = event[0]
        if kind == "log":
            self._log(event[1])
        elif kind == "video":
            _, video, count = event
            iid = self.tree.insert("", "end", values=(
                video.title, video.channel, video.views, video.published, video.duration))
            self.links[iid] = video.link
            self.tree.see(iid)
            self.progress.configure(value=count)
            self.progress_text.set(f"{count} / {self.target}")
            self.status.set(f"Collected {count} of {self.target}")
        elif kind == "finished":
            _, path, count, error, stopped = event
            self._set_running(False)
            if error:
                self._log(f"ERROR: {error}")
                self.status.set("Failed")
                note = f"\n\nPartial results saved to:\n{path}" if path else ""
                messagebox.showerror("Scraping failed", f"{error}{note}")
            elif path:
                self._log(f"Saved {count} videos to {path}")
                self.status.set(f"{'Stopped' if stopped else 'Done'} - {count} videos saved")
                messagebox.showinfo("Saved", f"{count} videos saved to:\n{path}")
            else:
                self.status.set("No matching videos")
                messagebox.showinfo("No results", "No videos matched your search/filter.")

    def _log(self, message: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _on_close(self) -> None:
        if self.running:
            if not messagebox.askyesno("Quit", "Scraping is still running. Stop and quit?"):
                return
            self.stop_event.set()
            if self.worker:
                self.worker.join(timeout=8)  # let Chrome shut down cleanly
        self.destroy()
