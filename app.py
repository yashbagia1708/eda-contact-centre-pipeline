"""
Interactive runner for the monthly refresh.

    python app.py          (or: make app)

Shows whether Docker and MySQL are ready, which months have arrived and which are already loaded,
and runs the same pipeline as `make setup` / `make refresh` + `make verify`, lighting up each stage
as it runs. Click any stage to see what it does and why. Nothing here is required: the command line
path works on its own, and this window only calls the same functions.
"""
from __future__ import annotations

import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

try:
    import customtkinter as ctk
except ImportError:
    sys.exit("customtkinter is not installed. Run: pip install -r requirements.txt")

from sqlalchemy import create_engine, text

from pipeline import export, extract, load, run
from pipeline.checks import CHECKS, run_checks
from pipeline.config import PROJECT_ROOT, settings
from pipeline.db import get_engine, wait_for_db

GREEN, AMBER, RED, GREY, BLUE = "#1E7B34", "#B54708", "#B42318", "#98A2B3", "#2E90FA"
POWERBI_WEB = "https://app.powerbi.com"
FRESH_LABEL, REFRESH_LABEL = "Start fresh: clear & load first month", "Run monthly refresh"
ACCENT, ACCENT_HOVER = "#344054", "#475467"
STATUS = {  # status -> (dot colour, symbol)
    "idle": (GREY, "○"), "running": (AMBER, "◐"), "done": (GREEN, "●"),
    "warn": (AMBER, "●"), "failed": (RED, "●"), "action": (BLUE, "◆"),
}

STEPS = [
    ("extract", "Extract",
     "Reads the four monthly drops exactly as the source systems send them: telephony CSV (UTC timestamps), "
     "CRM JSON (nested), post-call survey CSV (Australian dates) and the WFM workbook (title rows above the "
     "header). Each reader knows its own system's quirks, so a renamed column or a new layout is handled here."),
    ("validate", "Validate & clean",
     "Every source is cleaned by explicit rules: UTC to Brisbane time, duplicate extract pages removed, "
     "interaction IDs normalised across three formats, brand spellings standardised, out-of-range scores caught, "
     "and schema drift mapped (October renamed acw_sec to wrap_sec). Every rule records what it found, so "
     "nothing changes silently."),
    ("quarantine", "Quarantine",
     "Rows that can't be trusted are set aside in output/rejects/<month>/ with the reason, never silently "
     "dropped. If any source rejects more than 2% of its rows, the run stops here, before the database is touched."),
    ("stage", "Stage",
     "Clean data goes into staging tables that are rebuilt on every run, so the core model only ever "
     "reads from a known, validated state."),
    ("merge", "Merge (one transaction)",
     "Agents and queues are upserted, then the month's facts are replaced, all in a single transaction. "
     "Either everything lands or nothing does, and re-running a month never double counts."),
    ("export", "Power BI model",
     "Every model table is written to one workbook (one Excel table each) and swapped in atomically, so "
     "OneDrive never syncs a half-written file. The Power BI semantic model just refreshes."),
    ("kpi_pack", "KPI pack",
     "A formatted monthly Excel pack with month-on-month deltas, daily queue performance, agent scorecard, "
     "contact reasons and a data quality tab, for people who don't open Power BI."),
    ("verify", "Reconcile",
     f"{len(CHECKS)} SQL checks prove the numbers hang together: answered + abandoned = offered, handle time "
     "adds up, one survey per call, brand totals match the all-brand row, CRM cases link to calls, and more."),
    ("powerbi", "Refresh Power BI",
     "The pipeline's job ends when the model workbook is written. Power BI then pulls it in; nothing pushes to it.\n\n"
     "• Power BI Desktop: open the .pbix (button on the left) and click Home → Refresh.\n"
     "• Power BI web with the workbook in OneDrive: open the semantic model and click Refresh now, or let its "
     "scheduled refresh pick it up.\n\n"
     "Why it's manual here: triggering a refresh from code needs the Power BI REST API with an app registered in "
     "the organisation's Microsoft Entra ID, and Desktop can't be triggered at all. In production, the last step of "
     "this pipeline would call that API (or the whole flow would run as a Fabric pipeline), so the report updates "
     "itself the moment the data lands."),
]

KPIS = [  # column, label, format, direction: +1 higher is better, -1 lower is better, 0 neutral
    ("offered", "Calls offered", "{:,.0f}", 0),
    ("service_level_pct", "Service level", "{:.1%}", 1),
    ("abandon_rate", "Abandon rate", "{:.1%}", -1),
    ("asa_sec", "ASA", "{:.0f}s", -1),
    ("aht_sec", "AHT", "mm:ss", -1),
    ("avg_csat", "Avg CSAT", "{:.2f}", 1),
]


def find_docker() -> str | None:
    """Docker Desktop doesn't always put docker on PATH (especially for GUI apps), so look in the usual places."""
    candidates = [shutil.which("docker"), str(Path.home() / ".docker/bin/docker"), "/usr/local/bin/docker",
                  "/opt/homebrew/bin/docker", "/Applications/Docker.app/Contents/Resources/bin/docker",
                  r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"]
    return next((c for c in candidates if c and Path(c).exists()), None)


def docker_env(docker: str) -> dict:
    env = dict(os.environ)
    env["PATH"] = str(Path(docker).parent) + os.pathsep + env.get("PATH", "")
    return env


def open_path(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def fmt_value(fmt: str, v) -> str:
    if v is None:
        return "–"
    if fmt == "mm:ss":
        return f"{int(v) // 60}:{int(v) % 60:02d}"
    return fmt.format(v)


def fmt_delta(col: str, cur, prev) -> str:
    if cur is None or prev is None:
        return ""
    if col.endswith(("_pct", "_rate")):
        return f"{(cur - prev) * 100:+.1f} pts"
    if col == "offered":
        return f"{(cur - prev) / prev:+.1%}" if prev else ""
    if col == "avg_csat":
        return f"{cur - prev:+.2f}"
    return f"{cur - prev:+.0f}s"


class QueueLogHandler(logging.Handler):
    def __init__(self, events: queue.Queue):
        super().__init__()
        self.events = events
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        self.events.put(("log", self.format(record)))


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("EDA Contact Centre · Monthly Refresh")
        self.geometry("1220x820")
        self.minsize(1080, 720)
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.loaded: set[str] = set()
        self.known_months: list[str] = []
        self.last_outputs: dict = {}
        self.check_results: list = []
        self.docker = find_docker()
        self._setup_logging()
        self._build()
        self.after(80, self._drain_events)
        self.after(150, self._bring_to_front)
        self.after(300, lambda: self._start(self._task_readiness, label="Checking readiness…"))
        self.after(500, self._poll_months)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, corner_radius=0, fg_color=ACCENT)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        ctk.CTkLabel(header, text="Contact Centre Monthly Refresh", text_color="white",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(side="left", padx=20, pady=(14, 14))
        ctk.CTkLabel(header, text="KT Insurance & Club 4x4  ·  Mock data", text_color="#D0D5DD",
                     font=ctk.CTkFont(size=13)).pack(side="left", padx=4)
        self.status_label = ctk.CTkLabel(header, text="", text_color="white", font=ctk.CTkFont(size=13))
        self.status_label.pack(side="right", padx=20)

        # left: readiness, months, actions
        left = ctk.CTkFrame(self, width=330)
        left.grid(row=1, column=0, sticky="nsw", padx=(14, 7), pady=14)
        left.grid_propagate(False)
        self._section(left, "READY CHECKS")
        self.ready_rows = {k: self._status_row(left, t) for k, t in
                           [("docker", "Docker"), ("mysql", f"MySQL on port {settings.db_port}"),
                            ("source", "Source folder")]}
        self._section(left, "MONTHS")
        ctk.CTkLabel(left, text=self._short(settings.raw_dir), text_color=GREY, font=ctk.CTkFont(size=11),
                     wraplength=290, justify="left").pack(anchor="w", padx=16)
        self.months_frame = ctk.CTkFrame(left, fg_color="transparent")
        self.months_frame.pack(fill="x", padx=8, pady=(4, 0))
        self.new_month_label = ctk.CTkLabel(left, text="", text_color=AMBER, font=ctk.CTkFont(size=12, weight="bold"),
                                            wraplength=290, justify="left")
        self.new_month_label.pack(anchor="w", padx=16, pady=(2, 6))

        self.btn_fresh = ctk.CTkButton(left, text=FRESH_LABEL, height=40,
                                       fg_color="transparent", border_width=2, border_color=ACCENT,
                                       text_color=("#111927", "white"), hover_color=("#EAECF0", "#344054"),
                                       command=self._on_fresh)
        self.btn_fresh.pack(fill="x", padx=16, pady=(10, 6))
        self.btn_refresh = ctk.CTkButton(left, text=REFRESH_LABEL, height=46, fg_color=ACCENT,
                                         hover_color=ACCENT_HOVER, font=ctk.CTkFont(size=15, weight="bold"),
                                         command=self._on_refresh)
        self.btn_refresh.pack(fill="x", padx=16, pady=(0, 6))
        self._wire_actions()
        ctk.CTkLabel(left, text="Run monthly refresh loads the next month that has arrived,\n"
                                "then reconciles. With nothing new, it safely re-runs the latest.",
                     text_color=GREY, font=ctk.CTkFont(size=11), justify="left").pack(anchor="w", padx=16)

        self._section(left, "OUTPUTS")
        self.btn_powerbi = ctk.CTkButton(left, text="Open Power BI to refresh", height=34, fg_color=BLUE,
                                         hover_color="#1570CD", command=self._open_powerbi)
        self.btn_powerbi.pack(fill="x", padx=16, pady=(0, 6))
        for label, cmd in [("Open KPI pack", self._open_kpi_pack),
                           ("Open Power BI model folder", lambda: open_path(settings.export_dir)),
                           ("Open quarantined rows", self._open_rejects)]:
            ctk.CTkButton(left, text=label, height=30, fg_color="transparent", anchor="w",
                          text_color=("#175872", "#9CC3E6"), hover_color=("#EAECF0", "#344054"),
                          command=cmd).pack(fill="x", padx=10)

        # right: pipeline stages, explanation, KPIs, log
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew", padx=(7, 14), pady=14)
        right.grid_columnconfigure(0, weight=3)
        right.grid_columnconfigure(1, weight=2)
        right.grid_rowconfigure(2, weight=1)

        steps = ctk.CTkFrame(right)
        steps.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self._section(steps, "PIPELINE  ·  click a stage")
        self.step_rows = {}
        for i, (key, title, _) in enumerate(STEPS, 1):
            self.step_rows[key] = self._step_row(steps, i, key, title)

        explain = ctk.CTkFrame(right)
        explain.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self._section(explain, "WHAT THIS STAGE DOES")
        self.explain_title = ctk.CTkLabel(explain, text="", font=ctk.CTkFont(size=16, weight="bold"), anchor="w")
        self.explain_title.pack(fill="x", padx=16)
        self.explain_text = ctk.CTkTextbox(explain, wrap="word", fg_color="transparent", font=ctk.CTkFont(size=13),
                                           activate_scrollbars=True)
        self.explain_text.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self._explain("extract")

        kpi = ctk.CTkFrame(right)
        kpi.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        self.kpi_title = ctk.CTkLabel(kpi, text="RESULT  ·  run the pipeline to see the latest month",
                                      text_color=GREY, font=ctk.CTkFont(size=12, weight="bold"), anchor="w")
        self.kpi_title.grid(row=0, column=0, columnspan=len(KPIS), sticky="w", padx=16, pady=(10, 2))
        self.kpi_tiles = {}
        for i, (col, label, _, _) in enumerate(KPIS):
            kpi.grid_columnconfigure(i, weight=1)
            box = ctk.CTkFrame(kpi, fg_color="transparent")
            box.grid(row=1, column=i, sticky="w", padx=16, pady=(0, 12))
            ctk.CTkLabel(box, text=label, text_color=GREY, font=ctk.CTkFont(size=12)).pack(anchor="w")
            value = ctk.CTkLabel(box, text="–", font=ctk.CTkFont(size=24, weight="bold"))
            value.pack(anchor="w")
            delta = ctk.CTkLabel(box, text="", font=ctk.CTkFont(size=12))
            delta.pack(anchor="w")
            self.kpi_tiles[col] = (value, delta)

        logbox = ctk.CTkFrame(right)
        logbox.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(14, 0))
        self._section(logbox, "LIVE LOG")
        self.log_text = ctk.CTkTextbox(logbox, wrap="none", font=ctk.CTkFont(family="Courier", size=11))
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _wire_actions(self) -> None:
        """Keyboard shortcuts, plus a click fallback on mouse-up. Tk 8.6.12 on recent macOS can drop trackpad
        taps; the busy flag stops an action starting twice if both press and release get through."""
        mod = "Command" if sys.platform == "darwin" else "Control"
        self.bind_all(f"<{mod}-r>", lambda _e: self._on_refresh())
        self.bind_all(f"<{mod}-Shift-F>", lambda _e: self._on_fresh())
        self.bind_all(f"<{mod}-Shift-f>", lambda _e: self._on_fresh())
        for button, action in ((self.btn_fresh, self._on_fresh), (self.btn_refresh, self._on_refresh)):
            button.bind("<ButtonRelease-1>", lambda _e, a=action: None if self.busy else a(), add="+")
        key = "⌘" if sys.platform == "darwin" else "Ctrl+"
        ctk.CTkLabel(self.btn_refresh.master, text=f"Shortcuts: {key}R refresh  ·  {key}⇧F start fresh",
                     text_color=GREY, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=16)

    def _section(self, parent, text_: str) -> None:
        ctk.CTkLabel(parent, text=text_, text_color=GREY, font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").pack(fill="x", padx=16, pady=(14, 4))

    def _status_row(self, parent, title: str):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=1)
        dot = ctk.CTkLabel(row, text="○", text_color=GREY, width=22, font=ctk.CTkFont(size=16))
        dot.pack(side="left")
        ctk.CTkLabel(row, text=title, font=ctk.CTkFont(size=13), anchor="w").pack(side="left")
        detail = ctk.CTkLabel(row, text="", text_color=GREY, font=ctk.CTkFont(size=12), anchor="e")
        detail.pack(side="right", padx=4)
        return dot, detail

    def _step_row(self, parent, n: int, key: str, title: str):
        row = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=6, cursor="hand2")
        row.pack(fill="x", padx=8, pady=2)
        dot = ctk.CTkLabel(row, text="○", text_color=GREY, width=26, font=ctk.CTkFont(size=18))
        dot.pack(side="left", padx=(6, 0))
        name = ctk.CTkLabel(row, text=f"{n}  {title}", font=ctk.CTkFont(size=14, weight="bold"), width=225,
                            anchor="w")
        name.pack(side="left", pady=6)
        detail = ctk.CTkLabel(row, text="", text_color=GREY, font=ctk.CTkFont(size=12), anchor="w")
        detail.pack(side="left", fill="x", expand=True)
        for w in (row, dot, name, detail):
            w.bind("<Button-1>", lambda _e, k=key: self._explain(k))
        return row, dot, detail

    @staticmethod
    def _short(path: Path) -> str:
        try:
            return "./" + str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            return str(path).replace(str(Path.home()), "~")

    # ------------------------------------------------------------------ display helpers
    def _explain(self, key: str) -> None:
        for k, (row, _, _) in self.step_rows.items():
            row.configure(fg_color=("#EAECF0", "#344054") if k == key else "transparent")
        title, body = next((t, b) for k, t, b in STEPS if k == key)
        if key == "verify" and self.check_results:
            body += "\n\nLast run:\n" + "\n".join(f"{'✓' if ok else '✗'}  {name}" + ("" if ok else f"  (got {got})")
                                                  for name, ok, got, _ in self.check_results)
        self.explain_title.configure(text=title)
        self.explain_text.configure(state="normal")
        self.explain_text.delete("1.0", "end")
        self.explain_text.insert("1.0", body)
        self.explain_text.configure(state="disabled")

    def _set_step(self, key: str, status: str, detail: str = "") -> None:
        colour, symbol = STATUS[status]
        _, dot, label = self.step_rows[key]
        dot.configure(text=symbol, text_color=colour)
        label.configure(text=detail[:80] if status != "running" else "running…",
                        text_color={"failed": RED, "action": BLUE}.get(status, GREY))

    def _set_ready(self, key: str, ok: bool | None, detail: str) -> None:
        dot, label = self.ready_rows[key]
        colour, symbol = (GREY, "○") if ok is None else ((GREEN, "●") if ok else (RED, "●"))
        dot.configure(text=symbol, text_color=colour)
        label.configure(text=detail)

    def _render_months(self) -> None:
        for w in self.months_frame.winfo_children():
            w.destroy()
        if not self.known_months:
            ctk.CTkLabel(self.months_frame, text="No month folders yet (expected YYYY-MM)", text_color=GREY,
                         font=ctk.CTkFont(size=12)).pack(anchor="w", padx=8)
        for m in self.known_months:
            try:
                extract.month_files(settings.raw_dir, m)
                complete = True
            except FileNotFoundError:
                complete = False
            if m in self.loaded:
                colour, text_ = GREEN, "loaded"
            elif complete:
                colour, text_ = AMBER, "new files ready to load"
            else:
                colour, text_ = RED, "incomplete: waiting for files"
            row = ctk.CTkFrame(self.months_frame, fg_color="transparent")
            row.pack(fill="x", padx=4, pady=1)
            ctk.CTkLabel(row, text="●", text_color=colour, width=22, font=ctk.CTkFont(size=16)).pack(side="left")
            ctk.CTkLabel(row, text=datetime.strptime(m, "%Y-%m").strftime("%b %Y"),
                         font=ctk.CTkFont(size=13, weight="bold"), width=80, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=text_, text_color=colour, font=ctk.CTkFont(size=12)).pack(side="left")

    def _render_kpis(self, rows: list[dict]) -> None:
        if not rows:
            return
        cur = rows[-1]
        prev = rows[-2] if len(rows) > 1 else None
        month = datetime.strptime(cur["reporting_month"], "%Y-%m").strftime("%B %Y")
        self.kpi_title.configure(text=f"RESULT  ·  {month}, all brands" +
                                 (f"  ·  vs {datetime.strptime(prev['reporting_month'], '%Y-%m'):%B}" if prev else ""))
        for col, _, fmt, direction in KPIS:
            value, delta = self.kpi_tiles[col]
            value.configure(text=fmt_value(fmt, cur[col]))
            d = fmt_delta(col, cur[col], prev[col]) if prev else ""
            change = (cur[col] - prev[col]) if prev and cur[col] is not None and prev[col] is not None else 0
            good = direction * change
            delta.configure(text=d, text_color=GREY if direction == 0 or not change else (GREEN if good > 0 else RED))

    # ------------------------------------------------------------------ events from worker threads
    def _drain_events(self) -> None:
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "log":
                    self.log_text.insert("end", ev[1] + "\n")
                    self.log_text.see("end")
                elif kind == "step":
                    self._set_step(*ev[1:])
                elif kind == "ready":
                    self._set_ready(*ev[1:])
                elif kind == "loaded":
                    self.loaded = ev[1]
                    self._render_months()
                elif kind == "kpis":
                    self._render_kpis(ev[1])
                elif kind == "checks":
                    self.check_results = ev[1]
                    self._explain("verify")
                elif kind == "outputs":
                    self.last_outputs.update(ev[1])
                elif kind == "done":
                    self._finish(*ev[1:])
        except queue.Empty:
            pass
        self.after(80, self._drain_events)

    def _poll_months(self) -> None:
        """Watch the source folder, so a new month lights up the moment its files land."""
        months = run.available_months()
        if months != self.known_months:
            new = [m for m in months if m not in self.known_months and m not in self.loaded]
            if self.known_months and new:
                self.new_month_label.configure(
                    text=f"New month detected: {datetime.strptime(new[-1], '%Y-%m'):%B %Y}. Ready to refresh.")
            self.known_months = months
            self._render_months()
            ok = settings.raw_dir.exists() and bool(months)
            self._set_ready("source", ok, f"{len(months)} month(s)" if ok else "not found")
        self.after(2000, self._poll_months)

    # ------------------------------------------------------------------ actions
    def _start(self, task, label: str) -> None:
        if self.busy:
            return
        self.busy = True
        for b in (self.btn_fresh, self.btn_refresh):
            b.configure(state="disabled", text="Working…")
        self.status_label.configure(text=label, text_color="white")
        threading.Thread(target=self._run_task, args=(task,), daemon=True).start()

    def _run_task(self, task) -> None:
        try:
            msg = task()
            self.events.put(("done", True, msg or ""))
        except Exception as exc:  # shown in the window; the log has the detail
            logging.getLogger("app").exception("Run failed")
            self.events.put(("done", False, f"{type(exc).__name__}: {exc}"))

    def _finish(self, ok: bool, msg: str) -> None:
        self.busy = False
        self.btn_fresh.configure(state="normal", text=FRESH_LABEL)
        self.btn_refresh.configure(state="normal", text=REFRESH_LABEL)
        self._notify(msg if ok else f"Stopped: {msg}", error=not ok)

    def _notify(self, text_: str, error: bool = False) -> None:
        """Messages go in the header, not pop-ups: Tk's native dialogs don't reliably appear on recent macOS."""
        self.status_label.configure(text=text_[:140], text_color="#FDA29B" if error else "white")

    def _on_fresh(self) -> None:
        if not self.known_months:
            self._notify(f"No month folders found in {self._short(settings.raw_dir)}", error=True)
            return
        first = self.known_months[0]
        self._start(lambda: self._task_load(first, reset_first=True), label=f"Loading baseline {first}…")

    def _on_refresh(self) -> None:
        if not self.known_months:
            self._notify(f"No month folders found in {self._short(settings.raw_dir)}", error=True)
            return
        pending = [m for m in self.known_months if m not in self.loaded]
        # Nothing new: re-run the latest month. Safe, because a month is replaced, never added twice.
        month = pending[0] if pending else self.known_months[-1]
        self.new_month_label.configure(text="")
        self._start(lambda: self._task_load(month),
                    label=f"Refreshing {month}…" if pending else f"Nothing new, re-running {month}…")

    def _open_kpi_pack(self) -> None:
        path = self.last_outputs.get("kpi_pack")
        packs = sorted(settings.report_dir.glob("Contact_Centre_KPI_Pack_*.xlsx")) if settings.report_dir.exists() else []
        target = path or (packs[-1] if packs else None)
        if target:
            open_path(target)
        else:
            self._notify("No KPI pack yet: run the pipeline first")

    def _open_powerbi(self) -> None:
        """POWERBI_URL (optional, in .env) wins, e.g. the semantic model page with Refresh now. Otherwise the
        repo's .pbix in Power BI Desktop on Windows, otherwise Power BI in the browser."""
        url = os.getenv("POWERBI_URL", "").strip()
        reports = sorted((PROJECT_ROOT / "powerbi").glob("*.pbix"))
        if url:
            webbrowser.open(url)
        elif reports and sys.platform.startswith("win"):
            open_path(reports[0])
        else:
            webbrowser.open(POWERBI_WEB)
        self._explain("powerbi")

    def _open_rejects(self) -> None:
        month = self.last_outputs.get("month")
        folder = settings.reject_dir / month if month else settings.reject_dir
        if folder.exists():
            open_path(folder)
        else:
            self._notify("Nothing quarantined yet: run the pipeline first")

    def _bring_to_front(self) -> None:
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def _on_close(self) -> None:
        # A run interrupted here is safe: the merge is one transaction, so a half-finished month rolls back.
        self.destroy()

    # ------------------------------------------------------------------ worker tasks (background thread)
    def _task_readiness(self) -> str:
        self._ensure_database(start_if_needed=True)
        engine = get_engine()
        load.init_schema(engine)  # idempotent: a fresh clone (or a reset database) has no tables yet
        self.events.put(("loaded", load.loaded_months(engine)))
        self._push_kpis()
        return "Ready"

    def _ensure_database(self, start_if_needed: bool) -> None:
        if not self.docker:
            self.events.put(("ready", "docker", False, "not installed"))
        else:
            up = subprocess.run([self.docker, "info"], capture_output=True, env=docker_env(self.docker),
                                timeout=30).returncode == 0
            self.events.put(("ready", "docker", up, "running" if up else "not running"))
        if self._mysql_up():
            self.events.put(("ready", "mysql", True, "connected"))
            return
        if not self.docker:
            raise RuntimeError("Docker Desktop isn't installed. Install it, then reopen this window.")
        if not start_if_needed:
            raise RuntimeError("MySQL isn't reachable.")
        self.events.put(("ready", "mysql", None, "starting container…"))
        result = subprocess.run([self.docker, "compose", "up", "-d", "--wait"], cwd=PROJECT_ROOT,
                                capture_output=True, text=True, env=docker_env(self.docker), timeout=300)
        if result.returncode != 0:
            self.events.put(("ready", "mysql", False, "could not start"))
            raise RuntimeError("Could not start MySQL. Is Docker Desktop running?\n\n" + result.stderr[-600:])
        wait_for_db(get_engine())
        self.events.put(("ready", "mysql", True, "connected"))

    @staticmethod
    def _mysql_up() -> bool:
        try:
            with create_engine(settings.db_url, connect_args={"connect_timeout": 3}).connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def _task_load(self, month: str, reset_first: bool = False) -> str:
        for key, _, _ in STEPS:
            self.events.put(("step", key, "idle", ""))
        self._ensure_database(start_if_needed=True)
        engine = get_engine()
        if reset_first:
            run.reset(engine)
        load.init_schema(engine)
        result = run.run_month(engine, month, progress=lambda *a: self.events.put(("step", *a)))
        self.events.put(("outputs", {"month": month, **{k: result[k] for k in ("model", "kpi_pack") if k in result}}))

        self.events.put(("step", "verify", "running", ""))
        checks, _ = run_checks(engine)
        passed = sum(ok for _, ok, _, _ in checks)
        self.events.put(("checks", checks))
        self.events.put(("step", "verify", "done" if passed == len(checks) else "failed",
                         f"{passed}/{len(checks)} checks passed"))
        model = settings.export_dir / export.MODEL_WORKBOOK
        if passed == len(checks) and model.exists():
            written = datetime.fromtimestamp(model.stat().st_mtime)
            self.events.put(("step", "powerbi", "action", f"your turn: model written {written:%H:%M}, click Refresh"))
        self.events.put(("loaded", load.loaded_months(engine)))
        self._push_kpis()
        return f"{month} loaded in {result['seconds']:.0f}s · {passed}/{len(checks)} checks passed"

    def _push_kpis(self) -> None:
        try:
            with get_engine().connect() as conn:
                rows = conn.execute(text(
                    "SELECT * FROM vw_monthly_kpi_summary WHERE is_total = 1 ORDER BY reporting_month")).mappings()
                data = [{k: (float(v) if isinstance(v, (int, float)) or hasattr(v, "as_integer_ratio") else v)
                         for k, v in r.items()} for r in rows]
            self.events.put(("kpis", data))
        except Exception:  # views don't exist before the first load
            pass

    def _setup_logging(self) -> None:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(QueueLogHandler(self.events))
        file_handler = logging.FileHandler(settings.log_dir / f"pipeline_{datetime.now():%Y%m%d}.log")
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
        root.addHandler(file_handler)


if __name__ == "__main__":
    ctk.set_appearance_mode("system")
    App().mainloop()
