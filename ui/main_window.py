import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ui.log_parser import parse_engine_line


ROOT = Path(__file__).resolve().parents[1]

BG = "#0b0f14"
PANEL = "#111821"
PANEL_2 = "#151e29"
BORDER = "#263241"
TEXT = "#f3f6fa"
MUTED = "#91a0b3"
ACCENT = "#5b8cff"
ACCENT_HOVER = "#709bff"
DANGER = "#e15c64"
SUCCESS = "#62c48d"
WARNING = "#e2aa5c"


class ArgusApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("ARGUS")
        self.geometry("1240x820")
        self.minsize(1040, 700)
        self.configure(bg=BG)

        self.process = None
        self.events = queue.Queue()
        self.started_at = None
        self.cancel_requested = False
        self.result_path = ROOT / "result.json"

        self.status_var = tk.StringVar(value="대기")
        self.pages_var = tk.StringVar(value="0")
        self.findings_var = tk.StringVar(value="0")
        self.elapsed_var = tk.StringVar(value="0.0초")
        self.current_url_var = tk.StringVar(value="검사할 주소를 입력하세요.")
        self.autotune_var = tk.StringVar(value="Auto-Tune 대기")
        self.confirmed_var = tk.StringVar(value="0")
        self.suspicious_var = tk.StringVar(value="0")
        self.benign_var = tk.StringVar(value="0")

        self._configure_styles()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._poll_events)
        self.after(200, self._tick_elapsed)

    def _configure_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Argus.Horizontal.TProgressbar",
            troughcolor=PANEL_2,
            background=ACCENT,
            bordercolor=PANEL_2,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=8,
        )
        style.configure(
            "Argus.Treeview",
            background=PANEL,
            foreground=TEXT,
            fieldbackground=PANEL,
            rowheight=30,
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.map(
            "Argus.Treeview",
            background=[("selected", "#233a63")],
            foreground=[("selected", TEXT)],
        )
        style.configure(
            "Argus.Treeview.Heading",
            background=PANEL_2,
            foreground=MUTED,
            relief="flat",
            font=("Segoe UI Semibold", 9),
            padding=(8, 8),
        )
        style.map(
            "Argus.Treeview.Heading",
            background=[("active", PANEL_2)],
        )
        style.configure(
            "Argus.TNotebook",
            background=BG,
            borderwidth=0,
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "Argus.TNotebook.Tab",
            background=PANEL_2,
            foreground=MUTED,
            borderwidth=0,
            padding=(18, 9),
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            "Argus.TNotebook.Tab",
            background=[
                ("selected", PANEL),
                ("active", "#1b2734"),
            ],
            foreground=[
                ("selected", TEXT),
                ("active", TEXT),
            ],
        )
        style.configure(
            "Argus.Vertical.TScrollbar",
            background="#1b2734",
            troughcolor="#0d131b",
            bordercolor="#0d131b",
            arrowcolor=MUTED,
            lightcolor="#1b2734",
            darkcolor="#1b2734",
            gripcount=0,
        )
        style.configure(
            "Argus.Horizontal.TScrollbar",
            background="#1b2734",
            troughcolor="#0d131b",
            bordercolor="#0d131b",
            arrowcolor=MUTED,
            lightcolor="#1b2734",
            darkcolor="#1b2734",
            gripcount=0,
        )

    def _build_ui(self):
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=28, pady=24)

        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")

        title_wrap = tk.Frame(header, bg=BG)
        title_wrap.pack(side="left")

        tk.Label(
            title_wrap,
            text="ARGUS",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI Semibold", 25),
        ).pack(anchor="w")
        tk.Label(
            title_wrap,
            text="공공 웹사이트 은닉 광고 자동 탐지 · 분석",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(1, 0))

        self.status_badge = tk.Label(
            header,
            textvariable=self.status_var,
            bg=PANEL_2,
            fg=MUTED,
            padx=14,
            pady=7,
            font=("Segoe UI Semibold", 9),
        )
        self.status_badge.pack(side="right", pady=4)

        target_panel = tk.Frame(
            outer,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        target_panel.pack(fill="x", pady=(22, 14))

        target_inner = tk.Frame(target_panel, bg=PANEL)
        target_inner.pack(fill="x", padx=18, pady=16)

        tk.Label(
            target_inner,
            text="검사 대상",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        ).pack(anchor="w")

        entry_row = tk.Frame(target_inner, bg=PANEL)
        entry_row.pack(fill="x", pady=(8, 0))

        entry_shell = tk.Frame(
            entry_row,
            bg=PANEL_2,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        entry_shell.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 10),
        )

        self.target_entry = tk.Entry(
            entry_shell,
            bg=PANEL_2,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("Segoe UI", 11),
            bd=0,
        )
        self.target_entry.pack(
            fill="x",
            expand=True,
            padx=13,
            pady=11,
        )
        self.target_entry.insert(0, "https://")
        self.target_entry.bind("<Return>", lambda _event: self.start_scan())

        self.browse_button = self._button(
            entry_row,
            "파일 선택",
            self._browse_file,
            bg=PANEL_2,
            active_bg="#1b2734",
        )
        self.browse_button.pack(side="left", padx=(0, 8))

        self.start_button = self._button(
            entry_row,
            "검사 시작",
            self.start_scan,
            bg=ACCENT,
            active_bg=ACCENT_HOVER,
        )
        self.start_button.pack(side="left", padx=(0, 8))

        self.cancel_button = self._button(
            entry_row,
            "중지",
            self.cancel_scan,
            bg="#3a2025",
            active_bg="#4a282e",
            fg="#ffb8bd",
        )
        self.cancel_button.pack(side="left")
        self.cancel_button.configure(state="disabled")

        cards = tk.Frame(outer, bg=BG)
        cards.pack(fill="x", pady=(0, 14))
        for column in range(4):
            cards.grid_columnconfigure(column, weight=1, uniform="cards")

        self._stat_card(cards, 0, "상태", self.status_var)
        self._stat_card(cards, 1, "완료 페이지", self.pages_var)
        self._stat_card(cards, 2, "탐지 결과", self.findings_var)
        self._stat_card(cards, 3, "경과 시간", self.elapsed_var)

        progress_panel = tk.Frame(
            outer,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        progress_panel.pack(fill="x", pady=(0, 14))

        progress_inner = tk.Frame(progress_panel, bg=PANEL)
        progress_inner.pack(fill="x", padx=18, pady=14)

        top_line = tk.Frame(progress_inner, bg=PANEL)
        top_line.pack(fill="x")

        tk.Label(
            top_line,
            text="현재 작업",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        ).pack(side="left")
        tk.Label(
            top_line,
            textvariable=self.autotune_var,
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(side="right")

        tk.Label(
            progress_inner,
            textvariable=self.current_url_var,
            bg=PANEL,
            fg=TEXT,
            anchor="w",
            justify="left",
            font=("Segoe UI", 10),
        ).pack(fill="x", pady=(7, 10))

        self.progress = ttk.Progressbar(
            progress_inner,
            mode="determinate",
            maximum=100,
            value=0,
            style="Argus.Horizontal.TProgressbar",
        )
        self.progress.pack(fill="x")

        tab_shell = tk.Frame(
            outer,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        tab_shell.pack(fill="both", expand=True)

        tab_header = tk.Frame(tab_shell, bg=PANEL_2)
        tab_header.pack(fill="x")

        self.results_tab_button = tk.Button(
            tab_header,
            text="탐지 결과",
            command=lambda: self._show_tab("results"),
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Segoe UI Semibold", 9),
            padx=18,
            pady=9,
        )
        self.results_tab_button.pack(side="left")

        self.log_tab_button = tk.Button(
            tab_header,
            text="실행 로그",
            command=lambda: self._show_tab("log"),
            bg=PANEL_2,
            fg=MUTED,
            activebackground="#1b2734",
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Segoe UI Semibold", 9),
            padx=18,
            pady=9,
        )
        self.log_tab_button.pack(side="left")

        self.tab_content = tk.Frame(tab_shell, bg=PANEL)
        self.tab_content.pack(fill="both", expand=True)

        results_frame = tk.Frame(self.tab_content, bg=PANEL)
        log_frame = tk.Frame(self.tab_content, bg=PANEL)
        self.results_frame = results_frame
        self.log_frame = log_frame

        results_frame.place(x=0, y=0, relwidth=1, relheight=1)
        log_frame.place(x=0, y=0, relwidth=1, relheight=1)
        results_frame.tkraise()

        result_toolbar = tk.Frame(results_frame, bg=PANEL)
        result_toolbar.pack(fill="x", padx=12, pady=(12, 8))

        self.result_summary_label = tk.Label(
            result_toolbar,
            text="CONFIRMED 0   ·   SUSPICIOUS 0   ·   BENIGN_LIKELY 0",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
        )
        self.result_summary_label.pack(side="left")

        self.open_result_button = self._button(
            result_toolbar,
            "결과 폴더 열기",
            self._open_result_folder,
            bg=PANEL_2,
            active_bg="#1b2734",
        )
        self.open_result_button.pack(side="right")
        self.open_result_button.configure(state="disabled")

        tree_wrap = tk.Frame(results_frame, bg=PANEL)
        tree_wrap.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        columns = ("technique", "evidence", "url", "location")
        self.tree = ttk.Treeview(
            tree_wrap,
            columns=columns,
            show="headings",
            style="Argus.Treeview",
        )
        self.tree.heading("technique", text="기법")
        self.tree.heading("evidence", text="탐지 문구")
        self.tree.heading("url", text="페이지")
        self.tree.heading("location", text="위치")
        self.tree.column("technique", width=110, minwidth=100, stretch=False)
        self.tree.column("evidence", width=270, minwidth=180)
        self.tree.column("url", width=390, minwidth=240)
        self.tree.column("location", width=300, minwidth=220)

        y_scroll = self._scrollbar(
            tree_wrap,
            orient="vertical",
            command=self.tree.yview,
        )
        x_scroll = self._scrollbar(
            tree_wrap,
            orient="horizontal",
            command=self.tree.xview,
        )
        self.tree.configure(
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set,
        )
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        tree_wrap.grid_rowconfigure(0, weight=1)
        tree_wrap.grid_columnconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_frame,
            bg="#090d12",
            fg="#cdd6e1",
            insertbackground=TEXT,
            relief="flat",
            wrap="none",
            font=("Consolas", 9),
            padx=12,
            pady=12,
            state="disabled",
        )
        log_y = self._scrollbar(
            log_frame,
            orient="vertical",
            command=self.log_text.yview,
        )
        log_x = self._scrollbar(
            log_frame,
            orient="horizontal",
            command=self.log_text.xview,
        )
        self.log_text.configure(
            yscrollcommand=log_y.set,
            xscrollcommand=log_x.set,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_y.grid(row=0, column=1, sticky="ns")
        log_x.grid(row=1, column=0, sticky="ew")
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)

    def _show_tab(self, name):
        if name == "log":
            self.log_frame.tkraise()
            self.log_tab_button.configure(bg=PANEL, fg=TEXT)
            self.results_tab_button.configure(bg=PANEL_2, fg=MUTED)
            return

        self.results_frame.tkraise()
        self.results_tab_button.configure(bg=PANEL, fg=TEXT)
        self.log_tab_button.configure(bg=PANEL_2, fg=MUTED)

    def _scrollbar(self, parent, *, orient, command):
        return tk.Scrollbar(
            parent,
            orient=orient,
            command=command,
            bg="#1b2734",
            activebackground="#2a394a",
            troughcolor="#0d131b",
            relief="flat",
            bd=0,
            width=12,
            highlightthickness=0,
            elementborderwidth=0,
        )

    def _button(self, parent, text, command, *, bg, active_bg, fg=TEXT):
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=fg,
            disabledforeground="#667385",
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Segoe UI Semibold", 9),
            padx=16,
            pady=9,
        )
        return button

    def _stat_card(self, parent, column, label, variable):
        card = tk.Frame(
            parent,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        card.grid(
            row=0,
            column=column,
            sticky="nsew",
            padx=(0 if column == 0 else 5, 0 if column == 3 else 5),
        )

        tk.Label(
            card,
            text=label,
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=16, pady=(13, 2))
        tk.Label(
            card,
            textvariable=variable,
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI Semibold", 17),
        ).pack(anchor="w", padx=16, pady=(0, 13))

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="검사할 HTML 파일 선택",
            filetypes=[
                ("HTML 파일", "*.html *.htm"),
                ("모든 파일", "*.*"),
            ],
        )
        if not path:
            return

        self.target_entry.delete(0, "end")
        self.target_entry.insert(0, path)

    def start_scan(self):
        if self.process is not None:
            return

        target = self.target_entry.get().strip()
        if not target or target == "https://":
            messagebox.showwarning("ARGUS", "검사할 URL 또는 파일을 입력해 주세요.")
            self.target_entry.focus_set()
            return

        self.cancel_requested = False
        self.started_at = time.monotonic()
        self.result_path = ROOT / "result.json"

        self.status_var.set("검사 중")
        self.pages_var.set("0")
        self.findings_var.set("0")
        self.elapsed_var.set("0.0초")
        self.current_url_var.set("엔진을 시작하고 있습니다…")
        self.autotune_var.set("Auto-Tune 준비 중")
        self.confirmed_var.set("0")
        self.suspicious_var.set("0")
        self.benign_var.set("0")
        self._update_result_summary()

        for item in self.tree.get_children():
            self.tree.delete(item)
        self._clear_log()

        self.status_badge.configure(bg="#172743", fg="#a9c3ff")
        self.start_button.configure(state="disabled")
        self.browse_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.open_result_button.configure(state="disabled")
        self.target_entry.configure(state="disabled")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        thread = threading.Thread(
            target=self._engine_worker,
            args=(target,),
            daemon=True,
        )
        thread.start()

    def _engine_worker(self, target):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        command = [
            sys.executable,
            "-u",
            str(ROOT / "main.py"),
        ]

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0,
            )

        try:
            process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
            self.process = process

            if process.stdin is not None:
                process.stdin.write(target + "\n")
                process.stdin.flush()
                process.stdin.close()

            if process.stdout is not None:
                for line in process.stdout:
                    self.events.put(("line", line.rstrip("\r\n")))

            return_code = process.wait()
            self.events.put(("done", return_code))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def cancel_scan(self):
        process = self.process
        if process is None:
            return

        self.cancel_requested = True
        self.status_var.set("중지 중")
        self.status_badge.configure(bg="#38252a", fg="#ffb8bd")
        self.current_url_var.set("실행 중인 검사 작업을 종료하고 있습니다…")
        self.cancel_button.configure(state="disabled")

        try:
            if os.name == "nt":
                subprocess.run(
                    [
                        "taskkill",
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                process.terminate()
        except Exception as exc:
            self._append_log(f"[GUI] 중지 실패: {exc}")

    def _poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()

                if kind == "line":
                    self._handle_line(payload)
                elif kind == "done":
                    self._finish_scan(payload)
                elif kind == "error":
                    self._finish_error(payload)
        except queue.Empty:
            pass

        self.after(80, self._poll_events)

    def _handle_line(self, line):
        self._append_log(line)
        event = parse_engine_line(line)

        if event["type"] == "scan":
            self.current_url_var.set(event["url"])
            return

        if event["type"] == "complete":
            self.pages_var.set(str(event["completed"]))
            self.current_url_var.set(event["url"])
            return

        if event["type"] == "autotune":
            self.autotune_var.set(event["value"])
            return

        if event["type"] != "summary":
            return

        key = event["key"]
        value = event["value"]

        if key == "분석 완료 페이지":
            self.pages_var.set(value)
        elif key == "CONFIRMED":
            self.confirmed_var.set(value)
            self._update_result_summary()
        elif key == "SUSPICIOUS":
            self.suspicious_var.set(value)
            self._update_result_summary()
        elif key == "BENIGN_LIKELY":
            self.benign_var.set(value)
            self._update_result_summary()
        elif key == "최종 findings":
            self.findings_var.set(value)
        elif key == "result.json":
            self.result_path = Path(value.strip())
        elif key == "탐지 시간":
            self.elapsed_var.set(value)

    def _finish_scan(self, return_code):
        self.process = None
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self._restore_controls()

        if self.cancel_requested:
            self.status_var.set("중지됨")
            self.status_badge.configure(bg="#38252a", fg="#ffb8bd")
            self.current_url_var.set("사용자가 검사를 중지했습니다.")
            return

        if return_code != 0:
            self.status_var.set("오류")
            self.status_badge.configure(bg="#38252a", fg="#ffb8bd")
            self.current_url_var.set(
                f"탐지 엔진이 종료 코드 {return_code}로 종료되었습니다."
            )
            return

        self.status_var.set("완료")
        self.status_badge.configure(bg="#163126", fg="#9de2ba")
        self.current_url_var.set("검사가 완료되었습니다.")
        self._load_result_table()

    def _finish_error(self, message):
        self.process = None
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self._restore_controls()
        self.status_var.set("오류")
        self.status_badge.configure(bg="#38252a", fg="#ffb8bd")
        self.current_url_var.set(message)
        self._append_log(f"[GUI] {message}")

    def _restore_controls(self):
        self.start_button.configure(state="normal")
        self.browse_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.target_entry.configure(state="normal")

    def _load_result_table(self):
        path = self.result_path

        if not path.is_absolute():
            path = ROOT / path

        if not path.exists():
            self._append_log(f"[GUI] result.json을 찾을 수 없습니다: {path}")
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._append_log(f"[GUI] result.json 읽기 실패: {exc}")
            return

        findings = data.get("findings", [])

        for item in self.tree.get_children():
            self.tree.delete(item)

        for finding in findings:
            evidence = str(finding.get("evidence_text", "")).replace("\n", " ")
            self.tree.insert(
                "",
                "end",
                values=(
                    finding.get("technique", ""),
                    evidence,
                    finding.get("url", ""),
                    finding.get("location", ""),
                ),
            )

        self.findings_var.set(str(len(findings)))
        self.open_result_button.configure(state="normal")

    def _update_result_summary(self):
        self.result_summary_label.configure(
            text=(
                f"CONFIRMED {self.confirmed_var.get()}   ·   "
                f"SUSPICIOUS {self.suspicious_var.get()}   ·   "
                f"BENIGN_LIKELY {self.benign_var.get()}"
            )
        )

    def _tick_elapsed(self):
        if self.process is not None and self.started_at is not None:
            elapsed = time.monotonic() - self.started_at
            self.elapsed_var.set(f"{elapsed:.1f}초")
        self.after(200, self._tick_elapsed)

    def _append_log(self, line):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _open_result_folder(self):
        path = self.result_path

        if not path.is_absolute():
            path = ROOT / path

        folder = path.parent
        try:
            if os.name == "nt":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            messagebox.showerror(
                "ARGUS",
                f"결과 폴더를 열 수 없습니다.\n{exc}",
            )

    def _on_close(self):
        if self.process is not None:
            close = messagebox.askyesno(
                "ARGUS",
                "검사가 진행 중입니다. 종료할까요?",
            )
            if not close:
                return

            self.cancel_scan()

        self.destroy()


def run_app():
    app = ArgusApp()
    app.mainloop()
