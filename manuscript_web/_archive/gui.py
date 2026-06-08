"""블록 원고 생성기 — tkinter GUI (단건 / 배치 / 설정 3개 탭)."""
import os
import threading
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import config
from api_client import generate_async, MODELS
from prompt_builder import build_system_prompt, build_user_prompt
from output_parser import parse
from generator import to_sheet_row
from sheet_writer import write_row, write_rows_batch
from docx_writer import save_docx


THEME = {
    "bg": "#dcdad5", "frame_bg": "#e8e6e1", "accent": "#4a6984",
    "accent2": "#2e7d32", "warn": "#c62828", "text_bg": "#ffffff",
    "label_fg": "#333333", "entry_bg": "#ffffff", "btn_fg": "#ffffff",
}


class ManuscriptWebApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"블록 원고 생성기 v{config.VERSION}")
        self.root.geometry("1150x850")
        self.root.configure(bg=THEME["bg"])
        self.root.minsize(1000, 750)

        # 상태
        self.is_busy = False
        self.cancel_flag = False
        self.last_single = None        # 단건 결과 dict
        self.batch_results = []        # 배치 결과 리스트
        self._cached_system_prompt = None

        # 변수
        self.api_key_var = tk.StringVar(value=config.load_api_key())
        self.sheet_id_var = tk.StringVar(value=config.load_sheet_id())
        self.inst_dir_var = tk.StringVar(value=config.load_instructions_dir())
        self.writer_var = tk.StringVar(value=config.load_writer_name())
        kst_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        self.date_var = tk.StringVar(value=kst_now.strftime("%Y-%m-%d"))
        self.product_var = tk.StringVar(value=config.PRODUCT_NAMES[0])
        self.link_var = tk.StringVar()
        self.keyword_var = tk.StringVar()
        self.model_var = tk.StringVar(value="Opus")
        self.status_var = tk.StringVar(value="준비")

        self._setup_styles()
        self._build_ui()

    # ── 스타일 ──
    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame", background=THEME["bg"])
        s.configure("Card.TFrame", background=THEME["frame_bg"])
        s.configure("TLabel", background=THEME["bg"], foreground=THEME["label_fg"],
                    font=("맑은 고딕", 10))
        s.configure("Card.TLabel", background=THEME["frame_bg"],
                    foreground=THEME["label_fg"], font=("맑은 고딕", 10))
        s.configure("Header.TLabel", background=THEME["bg"],
                    foreground=THEME["accent"], font=("맑은 고딕", 11, "bold"))
        s.configure("Accent.TButton", foreground=THEME["btn_fg"],
                    background=THEME["accent"], font=("맑은 고딕", 10, "bold"))
        s.map("Accent.TButton", background=[("active", "#5a7994"),
                                             ("disabled", "#999999")])
        s.configure("Green.TButton", foreground=THEME["btn_fg"],
                    background=THEME["accent2"], font=("맑은 고딕", 10, "bold"))
        s.map("Green.TButton", background=[("active", "#388e3c"),
                                             ("disabled", "#999999")])
        s.configure("Warn.TButton", foreground=THEME["btn_fg"],
                    background=THEME["warn"], font=("맑은 고딕", 10, "bold"))
        s.map("Warn.TButton", background=[("active", "#d32f2f"),
                                            ("disabled", "#999999")])
        s.configure("TNotebook", background=THEME["bg"])
        s.configure("TNotebook.Tab", font=("맑은 고딕", 10), padding=(12, 6))

    # ── UI 구성 ──
    def _build_ui(self):
        top = ttk.Frame(self.root)
        top.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.nb = ttk.Notebook(top)
        self.nb.pack(fill=tk.BOTH, expand=True)

        self.tab_single = ttk.Frame(self.nb)
        self.tab_batch = ttk.Frame(self.nb)
        self.tab_settings = ttk.Frame(self.nb)
        self.nb.add(self.tab_single, text="단건 생성")
        self.nb.add(self.tab_batch, text="배치 생성")
        self.nb.add(self.tab_settings, text="설정")

        self._build_common_fields()
        self._build_single_tab()
        self._build_batch_tab()
        self._build_settings_tab()
        self._build_status_bar()

    # 공통 입력 필드 (단건/배치 탭 상단 공용)
    def _build_common_fields(self):
        # 각 탭 상단에 공통 설정 프레임 들어감
        pass

    def _common_frame(self, parent):
        """제품/담당자/날짜/모델 공통 입력 프레임."""
        frm = ttk.Frame(parent, style="Card.TFrame", padding=10)
        # 첫 줄: 제품 / 담당자 / 날짜 / 모델
        ttk.Label(frm, text="제품", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        cb = ttk.Combobox(frm, textvariable=self.product_var,
                          values=config.PRODUCT_NAMES, state="readonly", width=14)
        cb.grid(row=0, column=1, sticky="w", padx=4)

        ttk.Label(frm, text="담당자", style="Card.TLabel").grid(row=0, column=2, sticky="w", padx=4)
        ttk.Entry(frm, textvariable=self.writer_var, width=10).grid(row=0, column=3, sticky="w", padx=4)

        ttk.Label(frm, text="작성일", style="Card.TLabel").grid(row=0, column=4, sticky="w", padx=4)
        ttk.Entry(frm, textvariable=self.date_var, width=12).grid(row=0, column=5, sticky="w", padx=4)

        ttk.Label(frm, text="모델", style="Card.TLabel").grid(row=0, column=6, sticky="w", padx=4)
        ttk.Combobox(frm, textvariable=self.model_var, values=list(MODELS.keys()),
                     state="readonly", width=8).grid(row=0, column=7, sticky="w", padx=4)

        # 둘째 줄: 제품 링크
        ttk.Label(frm, text="제품 링크", style="Card.TLabel").grid(row=1, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(frm, textvariable=self.link_var, width=80).grid(
            row=1, column=1, columnspan=7, sticky="we", padx=4)
        return frm

    # ── 단건 탭 ──
    def _build_single_tab(self):
        frm = self.tab_single
        common = self._common_frame(frm)
        common.pack(fill=tk.X, padx=5, pady=5)

        # 키워드
        kf = ttk.Frame(frm, style="Card.TFrame", padding=10)
        kf.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(kf, text="키워드", style="Card.TLabel").pack(side=tk.LEFT, padx=4)
        ttk.Entry(kf, textvariable=self.keyword_var, width=40).pack(side=tk.LEFT, padx=4)

        self.btn_gen = ttk.Button(kf, text="원고 생성", style="Accent.TButton",
                                  command=self._run_single)
        self.btn_gen.pack(side=tk.LEFT, padx=8)
        self.btn_sheet = ttk.Button(kf, text="시트 기입", style="Green.TButton",
                                    command=self._write_sheet_single, state="disabled")
        self.btn_sheet.pack(side=tk.LEFT, padx=4)
        self.btn_docx = ttk.Button(kf, text="DOCX 저장", style="Accent.TButton",
                                   command=self._save_docx_single, state="disabled")
        self.btn_docx.pack(side=tk.LEFT, padx=4)

        # 결과 좌우 분할 (원고 / 분석)
        paned = ttk.PanedWindow(frm, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left = ttk.Frame(paned, style="Card.TFrame", padding=5)
        right = ttk.Frame(paned, style="Card.TFrame", padding=5)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        ttk.Label(left, text="원고 (제목 + 본문)", style="Header.TLabel").pack(anchor="w")
        self.txt_manuscript = scrolledtext.ScrolledText(
            left, wrap=tk.WORD, font=("맑은 고딕", 10), bg=THEME["text_bg"])
        self.txt_manuscript.pack(fill=tk.BOTH, expand=True, pady=4)

        ttk.Label(right, text="분석 (Phase A / B / B-2 / D)", style="Header.TLabel").pack(anchor="w")
        self.txt_analysis = scrolledtext.ScrolledText(
            right, wrap=tk.WORD, font=("맑은 고딕", 9), bg=THEME["text_bg"])
        self.txt_analysis.pack(fill=tk.BOTH, expand=True, pady=4)

    # ── 배치 탭 ──
    def _build_batch_tab(self):
        frm = self.tab_batch
        common = self._common_frame(frm)
        common.pack(fill=tk.X, padx=5, pady=5)

        kf = ttk.Frame(frm, style="Card.TFrame", padding=10)
        kf.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(kf, text="키워드 (한 줄에 하나씩)", style="Card.TLabel").pack(anchor="w")
        self.txt_batch_keywords = scrolledtext.ScrolledText(
            kf, wrap=tk.WORD, height=6, font=("맑은 고딕", 10), bg=THEME["text_bg"])
        self.txt_batch_keywords.pack(fill=tk.X, pady=4)

        bf = ttk.Frame(kf, style="Card.TFrame")
        bf.pack(fill=tk.X, pady=4)
        self.btn_batch_run = ttk.Button(bf, text="전체 생성 시작", style="Accent.TButton",
                                         command=self._run_batch)
        self.btn_batch_run.pack(side=tk.LEFT, padx=4)
        self.btn_batch_cancel = ttk.Button(bf, text="취소", style="Warn.TButton",
                                            command=self._cancel_batch, state="disabled")
        self.btn_batch_cancel.pack(side=tk.LEFT, padx=4)
        self.btn_batch_sheet = ttk.Button(bf, text="시트 일괄 기입", style="Green.TButton",
                                           command=self._write_sheet_batch, state="disabled")
        self.btn_batch_sheet.pack(side=tk.LEFT, padx=4)

        self.batch_progress = ttk.Progressbar(bf, length=300, mode="determinate")
        self.batch_progress.pack(side=tk.LEFT, padx=8)
        self.batch_status = ttk.Label(bf, text="대기", style="Card.TLabel")
        self.batch_status.pack(side=tk.LEFT, padx=4)

        # 결과 리스트
        rf = ttk.Frame(frm, style="Card.TFrame", padding=5)
        rf.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        ttk.Label(rf, text="결과", style="Header.TLabel").pack(anchor="w")
        cols = ("#", "키워드", "제목", "글자수", "심의")
        self.tree = ttk.Treeview(rf, columns=cols, show="headings", height=10)
        for c, w in zip(cols, (40, 200, 380, 80, 120)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=4)

    # ── 설정 탭 ──
    def _build_settings_tab(self):
        frm = self.tab_settings
        box = ttk.Frame(frm, style="Card.TFrame", padding=15)
        box.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(box, text="Anthropic API Key", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(box, textvariable=self.api_key_var, width=80, show="*").grid(row=0, column=1, columnspan=3, sticky="we", pady=4, padx=4)

        ttk.Label(box, text="Sheet ID", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(box, textvariable=self.sheet_id_var, width=80).grid(row=1, column=1, columnspan=3, sticky="we", pady=4, padx=4)

        ttk.Label(box, text="지침 폴더", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(box, textvariable=self.inst_dir_var, width=70).grid(row=2, column=1, columnspan=2, sticky="we", pady=4, padx=4)
        ttk.Button(box, text="찾아보기", command=self._browse_inst_dir).grid(row=2, column=3, padx=4)

        ttk.Button(box, text="저장", style="Green.TButton", command=self._save_settings).grid(
            row=3, column=1, pady=10, sticky="w")

        # 안내
        info = ttk.Label(box, style="Card.TLabel", justify="left",
                         text=f"탭명: {config.DEFAULT_TAB_NAME}\n카테고리 고정값: {config.DEFAULT_CATEGORY}\n지침 6개 파일이 폴더 안에 있어야 합니다.")
        info.grid(row=4, column=0, columnspan=4, sticky="w", pady=10)

    def _browse_inst_dir(self):
        d = filedialog.askdirectory(title="지침 폴더 선택")
        if d:
            self.inst_dir_var.set(d)

    def _save_settings(self):
        config.save_api_key(self.api_key_var.get())
        config.save_sheet_id(self.sheet_id_var.get())
        config.save_instructions_dir(self.inst_dir_var.get())
        config.save_writer_name(self.writer_var.get())
        self._set_status("설정 저장 완료", "green")
        # 캐시 무효화 (지침 경로 바뀌면)
        self._cached_system_prompt = None

    # ── 상태 바 ──
    def _build_status_bar(self):
        bar = ttk.Frame(self.root)
        bar.pack(fill=tk.X, padx=10, pady=(0, 8))
        self.status_lbl = ttk.Label(bar, textvariable=self.status_var, style="Header.TLabel")
        self.status_lbl.pack(side=tk.LEFT)

    def _set_status(self, msg, color="blue"):
        self.status_var.set(msg)
        self.status_lbl.configure(foreground={
            "blue": THEME["accent"], "green": THEME["accent2"],
            "red": THEME["warn"], "gray": "#666",
        }.get(color, THEME["accent"]))

    # ── 공통 헬퍼 ──
    def _get_system_prompt(self):
        if self._cached_system_prompt is None:
            self._cached_system_prompt = build_system_prompt()
        return self._cached_system_prompt

    def _validate_common(self):
        api = self.api_key_var.get().strip()
        if not api:
            messagebox.showerror("오류", "API Key를 설정 탭에서 먼저 입력하세요.")
            return None
        if not self.link_var.get().strip():
            messagebox.showerror("오류", "제품 링크를 입력하세요.")
            return None
        if not self.product_var.get().strip():
            messagebox.showerror("오류", "제품을 선택하세요.")
            return None
        return api

    # ── 단건 실행 ──
    def _run_single(self):
        if self.is_busy:
            return
        kw = self.keyword_var.get().strip()
        if not kw:
            messagebox.showerror("오류", "키워드를 입력하세요.")
            return
        api = self._validate_common()
        if not api:
            return

        self.is_busy = True
        self.btn_gen.configure(state="disabled")
        self.btn_sheet.configure(state="disabled")
        self.btn_docx.configure(state="disabled")
        self._set_status(f"원고 생성 중... (모델: {self.model_var.get()})", "blue")
        self.txt_manuscript.delete("1.0", tk.END)
        self.txt_analysis.delete("1.0", tk.END)

        sys_p = self._get_system_prompt()
        user_p = build_user_prompt(kw, self.product_var.get(), self.link_var.get().strip())

        def on_done(text, meta):
            self.root.after(0, self._on_single_done, kw, text, meta)

        def on_err(msg):
            self.root.after(0, self._on_single_err, msg)

        generate_async(api, sys_p, user_p, on_done, on_err,
                       model_key=self.model_var.get())

    def _on_single_done(self, keyword, text, meta):
        p = parse(text)
        p.update({
            "keyword": keyword,
            "product_name": self.product_var.get(),
            "product_link": self.link_var.get().strip(),
            "writer_name": self.writer_var.get().strip(),
            "write_date": self.date_var.get().strip(),
            "category": config.DEFAULT_CATEGORY,
            "model_key": self.model_var.get(),
            "usage": meta,
        })
        self.last_single = p
        self.txt_manuscript.insert(tk.END, f"[제목] {p['title']}\n\n{p['body']}")
        analysis = "\n\n".join([
            f"● Phase A — 페르소나\n{p['phases'].get('A', '')}",
            f"● Phase B — 블록 구성\n{p['phases'].get('B', '')}",
            f"● Phase B-2 — 심의·논문\n{p['phases'].get('B-2', '')}",
            f"● Phase D — 심의 검수\n{p['phases'].get('D', '')}",
        ])
        self.txt_analysis.insert(tk.END, analysis)

        self.is_busy = False
        self.btn_gen.configure(state="normal")
        self.btn_sheet.configure(state="normal")
        self.btn_docx.configure(state="normal")
        cache_read = (meta or {}).get("cache_read_input_tokens", 0)
        cache_create = (meta or {}).get("cache_creation_input_tokens", 0)
        cache_msg = f"(캐시 읽기 {cache_read:,} / 생성 {cache_create:,})" if meta else ""
        self._set_status(f"완료 — {p['char_count']}자, 스타일: {p['style']} {cache_msg}", "green")

    def _on_single_err(self, msg):
        self.is_busy = False
        self.btn_gen.configure(state="normal")
        self._set_status(f"실패: {msg}", "red")
        messagebox.showerror("생성 실패", msg)

    def _write_sheet_single(self):
        if not self.last_single:
            return
        try:
            row = to_sheet_row(self.last_single)
            row_num = write_row(*row, sheet_id=self.sheet_id_var.get().strip() or None)
            self._set_status(f"시트 기입 완료 — {row_num}행", "green")
            messagebox.showinfo("완료", f"{row_num}행에 기입했습니다.")
        except Exception as e:
            self._set_status(f"시트 기입 실패: {e}", "red")
            messagebox.showerror("시트 기입 실패", str(e))

    def _save_docx_single(self):
        if not self.last_single:
            return
        default = f"{self.last_single.get('keyword', 'manuscript')}.docx"
        path = filedialog.asksaveasfilename(
            defaultextension=".docx",
            filetypes=[("Word 문서", "*.docx")],
            initialfile=default,
            initialdir=config.OUTPUT_DIR,
        )
        if not path:
            return
        save_docx(self.last_single["title"], self.last_single["body"], path)
        self._set_status(f"DOCX 저장: {path}", "green")

    # ── 배치 실행 ──
    def _run_batch(self):
        if self.is_busy:
            return
        raw = self.txt_batch_keywords.get("1.0", tk.END).strip()
        keywords = [k.strip() for k in raw.splitlines() if k.strip()]
        if not keywords:
            messagebox.showerror("오류", "키워드를 한 줄에 하나씩 입력하세요.")
            return
        api = self._validate_common()
        if not api:
            return

        self.is_busy = True
        self.cancel_flag = False
        self.batch_results = []
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.batch_progress.configure(maximum=len(keywords), value=0)
        self.btn_batch_run.configure(state="disabled")
        self.btn_batch_sheet.configure(state="disabled")
        self.btn_batch_cancel.configure(state="normal")

        sys_p = self._get_system_prompt()
        model_key = self.model_var.get()
        product = self.product_var.get()
        link = self.link_var.get().strip()

        def worker():
            from api_client import call_claude_api
            for idx, kw in enumerate(keywords, start=1):
                if self.cancel_flag:
                    break
                self.root.after(0, self.batch_status.configure,
                                {"text": f"{idx}/{len(keywords)} — {kw}"})
                user_p = build_user_prompt(kw, product, link)
                holder = {"text": None, "err": None, "meta": None}

                def on_done(text, meta, h=holder):
                    h["text"] = text; h["meta"] = meta
                def on_err(msg, h=holder):
                    h["err"] = msg

                call_claude_api(api, sys_p, user_p, on_done, on_err,
                                model_key=model_key)

                if holder["err"]:
                    result = {"keyword": kw, "error": holder["err"]}
                else:
                    p = parse(holder["text"])
                    p.update({
                        "keyword": kw,
                        "product_name": product,
                        "product_link": link,
                        "writer_name": self.writer_var.get().strip(),
                        "write_date": self.date_var.get().strip(),
                        "category": config.DEFAULT_CATEGORY,
                        "model_key": model_key,
                        "usage": holder["meta"],
                    })
                    result = p

                self.batch_results.append(result)
                self.root.after(0, self._append_batch_row, idx, result)
                self.root.after(0, self.batch_progress.step, 1)

            self.root.after(0, self._finish_batch)

        threading.Thread(target=worker, daemon=True).start()

    def _append_batch_row(self, idx, result):
        if "error" in result:
            self.tree.insert("", tk.END, values=(
                idx, result["keyword"], f"[실패] {result['error'][:80]}", "-", "-"
            ))
        else:
            self.tree.insert("", tk.END, values=(
                idx, result["keyword"], result.get("title", "")[:80],
                result.get("char_count", 0),
                (result.get("review", "") or "")[:40],
            ))

    def _finish_batch(self):
        self.is_busy = False
        self.btn_batch_run.configure(state="normal")
        self.btn_batch_cancel.configure(state="disabled")
        ok = [r for r in self.batch_results if "error" not in r]
        self.btn_batch_sheet.configure(state="normal" if ok else "disabled")
        msg = f"배치 완료 — 성공 {len(ok)}건 / 실패 {len(self.batch_results) - len(ok)}건"
        self.batch_status.configure(text=msg)
        self._set_status(msg, "green" if ok else "red")

    def _cancel_batch(self):
        self.cancel_flag = True
        self._set_status("취소 요청 — 현재 작업 완료 후 중단합니다", "gray")

    def _write_sheet_batch(self):
        ok = [r for r in self.batch_results if "error" not in r]
        if not ok:
            return
        if not messagebox.askyesno("확인", f"성공한 {len(ok)}건을 시트에 일괄 기입할까요?"):
            return
        try:
            rows = [to_sheet_row(r) for r in ok]
            start, end = write_rows_batch(rows, sheet_id=self.sheet_id_var.get().strip() or None)
            self._set_status(f"시트 기입 완료 — {start}~{end}행", "green")
            messagebox.showinfo("완료", f"{start}~{end}행에 {len(ok)}건 기입")
        except Exception as e:
            self._set_status(f"시트 기입 실패: {e}", "red")
            messagebox.showerror("시트 기입 실패", str(e))


def main():
    root = tk.Tk()
    ManuscriptWebApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
