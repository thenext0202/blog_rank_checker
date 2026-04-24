"""공통 GUI 위젯 — 로그 영역, 상태바, Treeview 스타일"""

import tkinter as tk
from datetime import datetime
from tkinter import scrolledtext, ttk


def create_log_area(parent, height=12):
    """로그 표시용 ScrolledText 생성. (frame, log_widget, log_fn) 반환."""
    frame = ttk.LabelFrame(parent, text="로그", padding=5)

    log_box = scrolledtext.ScrolledText(
        frame, height=height, state="disabled", font=("Consolas", 9)
    )
    log_box.pack(fill="both", expand=True)

    def log_fn(msg):
        """스레드 안전 로그 함수"""
        def _do():
            log_box.configure(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            log_box.insert("end", f"[{ts}] {msg}\n")
            log_box.see("end")
            log_box.configure(state="disabled")
        try:
            log_box.winfo_toplevel().after(0, _do)
        except Exception:
            pass

    return frame, log_box, log_fn


def create_treeview(parent, columns, height=10):
    """Treeview + 스크롤바 생성. (frame, tree) 반환.
    columns: [("col_id", "헤더명", 너비), ...]
    """
    frame = ttk.Frame(parent)

    tree = ttk.Treeview(
        frame,
        columns=[c[0] for c in columns],
        show="headings",
        height=height,
    )
    for col_id, heading, width in columns:
        tree.heading(col_id, text=heading)
        tree.column(col_id, width=width, minwidth=50)

    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    frame.grid_rowconfigure(0, weight=1)
    frame.grid_columnconfigure(0, weight=1)

    # 색상 태그
    tree.tag_configure("ok", background="#d4edda")      # 초록 (통과)
    tree.tag_configure("error", background="#f8d7da")    # 빨강 (문제)
    tree.tag_configure("warn", background="#fff3cd")     # 노랑 (경고)
    tree.tag_configure("processing", background="#cce5ff")  # 파랑 (진행중)

    return frame, tree


class StatusBar(ttk.Frame):
    """하단 상태바"""

    def __init__(self, parent):
        super().__init__(parent, padding=(10, 3))
        self.labels = {}

    def add_field(self, name, text="", side="left"):
        lbl = ttk.Label(self, text=text, font=("맑은 고딕", 9))
        lbl.pack(side=side, padx=(0, 20))
        self.labels[name] = lbl
        return lbl

    def set(self, name, text):
        if name in self.labels:
            self.labels[name].configure(text=text)
