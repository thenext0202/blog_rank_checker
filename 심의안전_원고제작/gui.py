"""
심의안전 원고제작기 — GUI (tkinter)
"""
import os
import re
import json
import threading
import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox

from config import VERSION, THEME, OUTPUT_DIR, LOG_FILE, REFERENCES_DIR
from claude_api import call_claude_api
from sheets_loader import (
    connect_sheet, load_all_from_sheet, load_refs_for_product,
    save_sheet_id, load_sheet_id, save_api_key, load_api_key,
    get_product_code,
)
from prompt_builder import build_prompt
from word_export import save_as_docx


class SafetyManuscriptApp:

    def __init__(self, root):
        self.root = root
        self.root.title(f"심의안전 원고제작기 v{VERSION}")
        self.root.geometry("1400x960")
        self.root.minsize(1100, 750)
        self.root.configure(bg=THEME["bg"])

        self.sheet_data = {
            "prompts": {}, "styles": {}, "guidelines": [],
            "products": {}, "product_links": {}, "product_codes": {},
            "format_instructions": "", "papers": {},
            "safety_prompts": {}, "safety_appeals": {},
        }
        self.reference_files = {}
        self.is_generating = False
        self.spreadsheet = None
        self._setup_styles()
        self._build_ui()
        self._bind_shortcuts()
        self._init_load()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        if self.is_generating:
            if not messagebox.askyesno("생성 중", "원고 생성이 진행 중입니다.\n정말 종료하시겠습니까?"):
                return
        self.root.destroy()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Generate.TButton', font=('맑은 고딕', 10, 'bold'))
        style.configure('Refresh.TButton', font=('맑은 고딕', 9))

    def _bind_shortcuts(self):
        self.root.bind('<Control-g>', lambda e: self._on_generate())
        self.root.bind('<Control-G>', lambda e: self._on_generate())
        self.root.bind('<Control-s>', lambda e: self._on_save_docx())
        self.root.bind('<Control-S>', lambda e: self._on_save_docx())
        self.root.bind('<Control-p>', lambda e: self._on_preview())
        self.root.bind('<Control-P>', lambda e: self._on_preview())
        self.root.bind('<Control-r>', lambda e: self._on_refresh_sheet())
        self.root.bind('<Control-R>', lambda e: self._on_refresh_sheet())
        self.root.bind('<F5>', lambda e: self._on_refresh_sheet())

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # UI 빌드
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _build_ui(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ══ 탭1: 원고 제작 ══
        tab1 = ttk.Frame(notebook)
        notebook.add(tab1, text="  원고 제작  ")

        paned = tk.PanedWindow(tab1, orient=tk.VERTICAL, sashwidth=8,
                               sashrelief=tk.RAISED, bg=THEME["sash"], bd=1)
        paned.pack(fill=tk.BOTH, expand=True)

        # 상단: 설정 (스크롤) — 초기에 설정 영역이 크게 보이도록
        top_pane = ttk.Frame(paned)
        paned.add(top_pane, stretch="always", minsize=300, height=600)

        canvas = tk.Canvas(top_pane, highlightthickness=0, bg=THEME["bg"])
        scrollbar = ttk.Scrollbar(top_pane, orient=tk.VERTICAL, command=canvas.yview)
        self.scroll_frame = ttk.Frame(canvas)
        self.scroll_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas.find_all()[0], width=e.width))

        sf = self.scroll_frame

        # 하단: 버튼+결과
        bottom_pane = ttk.Frame(paned)
        paned.add(bottom_pane, stretch="never", minsize=200)

        sc = ttk.Frame(sf)
        sc.pack(fill=tk.X, padx=0, pady=0)

        # ── 기본 설정 ──
        row1 = ttk.LabelFrame(sc, text="기본 설정", padding=10)
        row1.pack(fill=tk.X, padx=10, pady=(10, 5))

        ttk.Label(row1, text="제품:").grid(row=0, column=0, sticky='e', padx=(0, 5))
        self.product_var = tk.StringVar()
        self.product_combo = ttk.Combobox(row1, textvariable=self.product_var, state='readonly', width=18)
        self.product_combo.grid(row=0, column=1, sticky='w', padx=(0, 15))
        self.product_var.trace_add('write', lambda *a: self._on_product_changed())

        ttk.Label(row1, text="원고유형:").grid(row=0, column=2, sticky='e', padx=(0, 5))
        self.prompt_var = tk.StringVar()
        self.prompt_combo = ttk.Combobox(row1, textvariable=self.prompt_var, state='readonly', width=18)
        self.prompt_combo.grid(row=0, column=3, sticky='w', padx=(0, 15))

        ttk.Label(row1, text="작가스타일:").grid(row=0, column=4, sticky='e', padx=(0, 5))
        self.style_var = tk.StringVar()
        self.style_combo = ttk.Combobox(row1, textvariable=self.style_var, state='readonly', width=18)
        self.style_combo.grid(row=0, column=5, sticky='w')

        ttk.Label(row1, text="작가명:").grid(row=1, column=0, sticky='e', padx=(0, 5), pady=(5, 0))
        self.author_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.author_var, width=12).grid(row=1, column=1, sticky='w', padx=(0, 15), pady=(5, 0))

        ttk.Label(row1, text="날짜:").grid(row=1, column=2, sticky='e', padx=(0, 5), pady=(5, 0))
        self.date_var = tk.StringVar(value=datetime.datetime.now().strftime("%y%m%d"))
        ttk.Entry(row1, textvariable=self.date_var, width=10).grid(row=1, column=3, sticky='w', padx=(0, 15), pady=(5, 0))

        # ── 키워드 ──
        row3 = ttk.LabelFrame(sc, text="키워드", padding=10)
        row3.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(row3, text="메인:").grid(row=0, column=0, sticky='e', padx=(0, 5))
        self.keyword_entry = ttk.Entry(row3, width=40)
        self.keyword_entry.grid(row=0, column=1, sticky='w', padx=(0, 15))

        ttk.Label(row3, text="연관:").grid(row=0, column=2, sticky='e', padx=(0, 5))
        self.sub_keyword_entry = ttk.Entry(row3, width=40)
        self.sub_keyword_entry.grid(row=0, column=3, sticky='w')

        ttk.Label(row3, text="상품 링크:").grid(row=1, column=0, sticky='e', padx=(0, 5), pady=(5, 0))
        self.link_entry = ttk.Entry(row3, width=40)
        self.link_entry.grid(row=1, column=1, sticky='w', pady=(5, 0))

        ttk.Label(row3, text="nt_medium:").grid(row=1, column=2, sticky='e', padx=(0, 5), pady=(5, 0))
        self.nt_medium_var = tk.StringVar()
        ttk.Entry(row3, textvariable=self.nt_medium_var, width=20).grid(row=1, column=3, sticky='w', pady=(5, 0))

        # 날짜/nt_medium/키워드 변경 시 상품 링크 자동 업데이트
        self.date_var.trace_add('write', lambda *a: self._update_product_link())
        self.nt_medium_var.trace_add('write', lambda *a: self._update_product_link())
        self.keyword_entry.bind('<FocusOut>', lambda e: self._update_product_link())

        # ── 서식 옵션 ──
        row2 = ttk.LabelFrame(sc, text="서식 옵션", padding=10)
        row2.pack(fill=tk.X, padx=10, pady=5)

        col = 0
        ttk.Label(row2, text="문체:").grid(row=0, column=col, sticky='e', padx=(0, 5)); col += 1
        self.tone_var = tk.StringVar(value="존댓말")
        ttk.Combobox(row2, textvariable=self.tone_var, state='readonly', width=8,
                     values=["존댓말", "반말"]).grid(row=0, column=col, sticky='w', padx=(0, 15)); col += 1

        ttk.Label(row2, text="글자크기:").grid(row=0, column=col, sticky='e', padx=(0, 5)); col += 1
        self.fontsize_var = tk.StringVar(value="16")
        ttk.Combobox(row2, textvariable=self.fontsize_var, state='readonly', width=6,
                     values=["11", "13", "15", "16", "19", "24", "28"]).grid(row=0, column=col, sticky='w', padx=(0, 15)); col += 1

        ttk.Label(row2, text="정렬:").grid(row=0, column=col, sticky='e', padx=(0, 5)); col += 1
        self.align_var = tk.StringVar(value="가운데정렬")
        ttk.Combobox(row2, textvariable=self.align_var, state='readonly', width=10,
                     values=["가운데정렬", "왼쪽정렬"]).grid(row=0, column=col, sticky='w', padx=(0, 15)); col += 1

        ttk.Label(row2, text="인용구:").grid(row=0, column=col, sticky='e', padx=(0, 5)); col += 1
        self.quote_var = tk.StringVar(value="3")
        ttk.Combobox(row2, textvariable=self.quote_var, state='readonly', width=5,
                     values=["1", "2", "3", "4", "5", "6"]).grid(row=0, column=col, sticky='w', padx=(0, 15)); col += 1

        self.toc_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="목차 포함", variable=self.toc_var).grid(row=0, column=col, sticky='w', padx=(0, 15)); col += 1

        self.title_repeat_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="제목 3번 반복", variable=self.title_repeat_var).grid(row=0, column=col, sticky='w')

        # ── 심의안전: 키워드그룹 & 강조점 ──
        safety_frame = ttk.LabelFrame(sc, text="심의안전 — 소구점 (Claude가 키워드에 맞게 선택)", padding=10)
        safety_frame.pack(fill=tk.X, padx=10, pady=5)

        # 소구점 미리보기
        safety_preview_frame = ttk.Frame(safety_frame)
        safety_preview_frame.pack(fill=tk.X)
        self.safety_preview = tk.Text(safety_preview_frame, height=5, font=('맑은 고딕', 9),
                                       wrap=tk.WORD, state='disabled', bg='#F5F5F5')
        safety_preview_sb = ttk.Scrollbar(safety_preview_frame, orient=tk.VERTICAL,
                                           command=self.safety_preview.yview)
        self.safety_preview.configure(yscrollcommand=safety_preview_sb.set)
        safety_preview_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.safety_preview.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ── 원고 옵션 ──
        row4 = ttk.LabelFrame(sc, text="원고 옵션", padding=10)
        row4.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(row4, text="글자수:").grid(row=0, column=0, sticky='e', padx=(0, 5))
        self.charcount_var = tk.StringVar(value="2000~2300")
        ttk.Combobox(row4, textvariable=self.charcount_var, state='readonly', width=12,
                     values=["1500~1800", "2000~2300", "2500~2800", "3000~3300",
                             "3500~3800", "4000~4300", "4500~4800", "5100~5400"]).grid(row=0, column=1, sticky='w', padx=(0, 15))

        ttk.Label(row4, text="이미지:").grid(row=0, column=2, sticky='e', padx=(0, 5))
        self.imgcount_var = tk.StringVar(value="자동")
        ttk.Entry(row4, textvariable=self.imgcount_var, width=6).grid(row=0, column=3, sticky='w', padx=(0, 15))

        ttk.Label(row4, text="강조 크기:").grid(row=0, column=4, sticky='e', padx=(0, 5))
        self.emphasis_fontsize_var = tk.StringVar(value="16")
        ttk.Combobox(row4, textvariable=self.emphasis_fontsize_var, state='readonly', width=5,
                     values=["11", "13", "15", "16", "19", "24", "28"]).grid(row=0, column=5, sticky='w')

        # ── 색상 규칙 ──
        row5 = ttk.LabelFrame(sc, text="색상 규칙", padding=10)
        row5.pack(fill=tk.X, padx=10, pady=5)
        colors = ["없음", "빨간색", "파란색", "청록색", "초록색", "보라색", "주황색"]
        highlights = ["없음", "노란 형광펜", "파란 형광펜", "초록 형광펜", "빨간 형광펜"]

        ttk.Label(row5, text="긍정:").grid(row=0, column=0, sticky='e', padx=(0, 5))
        self.color_positive_var = tk.StringVar(value="파란색")
        ttk.Combobox(row5, textvariable=self.color_positive_var, state='readonly', width=8, values=colors).grid(row=0, column=1, sticky='w', padx=(0, 10))

        ttk.Label(row5, text="부정:").grid(row=0, column=2, sticky='e', padx=(0, 5))
        self.color_negative_var = tk.StringVar(value="빨간색")
        ttk.Combobox(row5, textvariable=self.color_negative_var, state='readonly', width=8, values=colors).grid(row=0, column=3, sticky='w', padx=(0, 10))

        ttk.Label(row5, text="강조 형광:").grid(row=0, column=4, sticky='e', padx=(0, 5))
        self.highlight_emphasis_var = tk.StringVar(value="노란 형광펜")
        ttk.Combobox(row5, textvariable=self.highlight_emphasis_var, state='readonly', width=12, values=highlights).grid(row=0, column=5, sticky='w', padx=(0, 10))

        ttk.Label(row5, text="제품색:").grid(row=0, column=6, sticky='e', padx=(0, 5))
        self.color_product_var = tk.StringVar(value="없음")
        ttk.Combobox(row5, textvariable=self.color_product_var, state='readonly', width=8, values=colors).grid(row=0, column=7, sticky='w', padx=(0, 10))

        ttk.Label(row5, text="제품 형광:").grid(row=0, column=8, sticky='e', padx=(0, 5))
        self.highlight_product_var = tk.StringVar(value="없음")
        ttk.Combobox(row5, textvariable=self.highlight_product_var, state='readonly', width=12, values=highlights).grid(row=0, column=9, sticky='w')

        # ── 추가 지시사항 ──
        row6 = ttk.LabelFrame(sc, text="추가 지시사항", padding=10)
        row6.pack(fill=tk.X, padx=10, pady=(5, 10))

        self.extra_text = tk.Text(row6, height=3, font=('맑은 고딕', 10), wrap=tk.WORD)
        self.extra_text.pack(fill=tk.X)

        # ━━ 하단: 버튼 + 결과 ━━
        btn = ttk.Frame(bottom_pane)
        btn.pack(fill=tk.X, padx=10, pady=5)

        self.generate_btn = ttk.Button(btn, text="원고 생성 (Ctrl+G)", style='Generate.TButton', command=self._on_generate)
        self.generate_btn.pack(side=tk.LEFT, padx=(0, 10))


        self.review_btn = ttk.Button(btn, text="검수", command=self._on_review)
        self.review_btn.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(btn, text="프롬프트 미리보기 (Ctrl+P)", command=self._on_preview).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn, text="Word 저장 (Ctrl+S)", command=self._on_save_docx).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn, text="텍스트 저장", command=self._on_save_txt).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn, text="시트 새로고침 (F5)", style='Refresh.TButton',
                   command=self._on_refresh_sheet).pack(side=tk.LEFT, padx=(5, 0))

        # 상태바
        self.status_var = tk.StringVar(value="준비")
        ttk.Label(bottom_pane, textvariable=self.status_var, font=('맑은 고딕', 9)).pack(
            fill=tk.X, padx=10, pady=(0, 3))

        # 결과 영역
        self.result_text = scrolledtext.ScrolledText(bottom_pane, font=('맑은 고딕', 11),
                                                      wrap=tk.WORD, bg=THEME["text_bg"])
        self.result_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))
        self.result_text.tag_configure("annotation", foreground="#008000")
        self.result_text.tag_configure("img_num", foreground="#0070C0", justify='center')
        self.result_text.tag_configure("blogger_req", foreground="#CC0000", font=('맑은 고딕', 11, 'bold'))

        # ══ 탭2: 설정 ══
        tab2 = ttk.Frame(notebook)
        notebook.add(tab2, text="  설정  ")
        self._build_settings_tab(tab2)

    def _build_settings_tab(self, tab):
        sf = ttk.Frame(tab, padding=15)
        sf.pack(fill=tk.BOTH, expand=True)

        # API Key
        api_frame = ttk.LabelFrame(sf, text="Claude API Key", padding=10)
        api_frame.pack(fill=tk.X, pady=(0, 10))
        self.api_key_var = tk.StringVar()
        ttk.Entry(api_frame, textvariable=self.api_key_var, width=60, show='*').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(api_frame, text="저장", command=self._save_api_key).pack(side=tk.LEFT)

        # Sheets
        sheet_frame = ttk.LabelFrame(sf, text="Google Sheets", padding=10)
        sheet_frame.pack(fill=tk.X, pady=(0, 10))
        self.sheet_id_var = tk.StringVar()
        ttk.Entry(sheet_frame, textvariable=self.sheet_id_var, width=50).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(sheet_frame, text="저장 & 연결", command=self._connect_sheet).pack(side=tk.LEFT, padx=(0, 10))
        self.sheet_status_var = tk.StringVar(value="미연결")
        ttk.Label(sheet_frame, textvariable=self.sheet_status_var, font=('맑은 고딕', 9)).pack(side=tk.LEFT)

        # 설정 미리보기
        preview_frame = ttk.LabelFrame(sf, text="현재 설정 미리보기", padding=10)
        preview_frame.pack(fill=tk.BOTH, expand=True)
        self.config_preview = tk.Text(preview_frame, font=('맑은 고딕', 9), state='disabled', wrap=tk.WORD)
        self.config_preview.pack(fill=tk.BOTH, expand=True)

        # 버전 정보
        ttk.Label(sf, text=f"v{VERSION} | Claude Sonnet 4 | python-docx | gspread",
                  font=('맑은 고딕', 8), foreground='#999').pack(pady=(5, 0))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 데이터 연결
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _init_load(self):
        key = load_api_key()
        if key:
            self.api_key_var.set(key)
        sid = load_sheet_id()
        if sid:
            self.sheet_id_var.set(sid)
            self._connect_sheet(silent=True)

    def _save_api_key(self):
        key = self.api_key_var.get().strip()
        if key:
            save_api_key(key)
            messagebox.showinfo("저장", "API Key가 저장되었습니다.")

    def _connect_sheet(self, silent=False):
        sid = self.sheet_id_var.get().strip()
        if not sid:
            if not silent:
                messagebox.showwarning("시트 ID", "스프레드시트 ID를 입력해주세요.")
            return
        save_sheet_id(sid)
        self.status_var.set("시트 연결 중...")
        self.root.update()
        sp = connect_sheet(sid)
        if sp:
            self.spreadsheet = sp
            self.sheet_data = load_all_from_sheet(sp)
            self._update_combos()
            self._update_config_preview()
            self.sheet_status_var.set("연결됨 ✓")
            safety_count = len(self.sheet_data.get("safety_appeals", {}))
            self.status_var.set(f"시트 연결 완료! (심의안전 소구점: {safety_count}개 제품)")
        else:
            self.sheet_status_var.set("연결 실패")
            if not silent:
                messagebox.showerror("연결 실패", "스프레드시트 연결에 실패했습니다.\ncredentials.json과 시트 ID를 확인해주세요.")

    def _on_refresh_sheet(self):
        if not self.spreadsheet:
            messagebox.showinfo("시트 미연결", "스프레드시트가 연결되어 있지 않습니다.\n설정 탭에서 먼저 연결해주세요.")
            return
        self.status_var.set("시트 새로고침 중...")
        self.root.update()
        self.sheet_data = load_all_from_sheet(self.spreadsheet)
        self._update_combos()
        self._update_config_preview()
        self.status_var.set("새로고침 완료!")

    def _update_combos(self):
        products = list(self.sheet_data["products"].keys())
        self.product_combo['values'] = products
        if products:
            self.product_combo.current(0)
            self._on_product_changed()

        # 심의안전 프롬프트만 사용
        safety_types = list(self.sheet_data.get("safety_prompts", {}).keys())
        self.prompt_combo['values'] = safety_types
        if safety_types:
            self.prompt_combo.current(0)

        styles = ["(스타일 없음)"] + list(self.sheet_data["styles"].keys())
        self.style_combo['values'] = styles
        self.style_combo.current(0)

    def _on_product_changed(self):
        self._update_safety_preview()
        self._update_refs()
        self._update_product_link()

    def _update_product_link(self):
        """상품 링크 자동 생성 (추적 파라미터 포함)"""
        product = self.product_var.get()
        base_link = self.sheet_data.get("product_links", {}).get(product, "")
        if not base_link:
            self.link_entry.delete(0, tk.END)
            return

        product_code = get_product_code(product, self.sheet_data)

        # nt_detail: 날짜 + 키워드 (띄어쓰기 제거)
        date = self.date_var.get().strip()
        keyword = self.keyword_entry.get().strip().split(',')[0].strip()
        nt_detail = f"{date}{keyword}".replace(" ", "")

        # nt_medium
        nt_medium = self.nt_medium_var.get().strip()

        # 링크 조립
        params = "nt_source=blog"
        if nt_medium:
            params += f"&nt_medium={nt_medium}"
        if nt_detail:
            params += f"&nt_detail={nt_detail}"
        if product_code:
            params += f"&nt_keyword={product_code}"

        full_link = f"{base_link}?{params}"
        self.link_entry.delete(0, tk.END)
        self.link_entry.insert(0, full_link)

    def _build_product_link(self):
        """상품링크 입력값 그대로 반환 (이미 _update_product_link에서 조립됨)"""
        return self.link_entry.get().strip()

    def _update_safety_preview(self):
        product = self.product_var.get()
        points = self.sheet_data.get("safety_appeals", {}).get(product, [])
        self.safety_preview.config(state='normal')
        self.safety_preview.delete('1.0', tk.END)
        if points:
            lines = [f"{i+1}. {p}" for i, p in enumerate(points)]
            self.safety_preview.insert('1.0', "\n".join(lines))
        else:
            self.safety_preview.insert('1.0', "(이 제품의 소구점이 없습니다)")
        self.safety_preview.config(state='disabled')

    def _update_refs(self):
        product = self.product_var.get()
        self.reference_files = load_refs_for_product(product)

    def _update_config_preview(self):
        self.config_preview.config(state='normal')
        self.config_preview.delete('1.0', tk.END)
        d = self.sheet_data
        lines = []

        lines.append(f"══ 제품 ({len(d['products'])}개) ══")
        for name in d['products']:
            lines.append(f"  ▶ {name}")

        # 심의안전 정보
        sa = d.get('safety_appeals', {})
        sp = d.get('safety_prompts', {})
        lines.append(f"\n══ 심의안전 프롬프트 ({len(sp)}개) ══")
        for name in sp:
            lines.append(f"  ▶ {name}")
        lines.append(f"\n══ 심의안전 소구점 ({len(sa)}개 제품) ══")
        for pname, points in sa.items():
            lines.append(f"  ▶ {pname}: {len(points)}개 소구점")

        lines.append(f"\n══ 스타일 ({len(d['styles'])}개) ══")
        paper_count = sum(len(v) for v in d.get('papers', {}).values())
        lines.append(f"══ 참고논문 ({paper_count}건) ══")

        self.config_preview.insert('1.0', "\n".join(lines))
        self.config_preview.config(state='disabled')

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 원고 생성 흐름
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _gather_inputs(self):
        product = self.product_var.get()
        prompt_type = self.prompt_var.get()
        if not product or not prompt_type:
            if not self.spreadsheet:
                messagebox.showwarning("시트 미연결", "설정 탭에서 스프레드시트를 먼저 연결해주세요.")
            else:
                messagebox.showwarning("입력 확인", "제품과 원고유형을 선택해주세요.")
            return None

        style_name = self.style_var.get()
        if style_name == "(스타일 없음)":
            style_name = ""

        return {
            "product": product,
            "prompt_type": prompt_type,
            "style_name": style_name,
            "tone": self.tone_var.get(),
            "font_size": self.fontsize_var.get(),
            "alignment": self.align_var.get(),
            "quote_num": self.quote_var.get(),
            "keywords": self.keyword_entry.get().strip(),
            "sub_keywords": self.sub_keyword_entry.get().strip(),
            "extra": self.extra_text.get('1.0', tk.END).strip(),
            "selected_refs": self.reference_files,
            "include_toc": self.toc_var.get(),
            "product_link": self._build_product_link(),
            "char_count": self.charcount_var.get(),
            "img_count": self.imgcount_var.get().strip(),
            "color_positive": self.color_positive_var.get(),
            "color_negative": self.color_negative_var.get(),
            "highlight_emphasis": self.highlight_emphasis_var.get(),
            "color_product": self.color_product_var.get(),
            "highlight_product": self.highlight_product_var.get(),
            "title_repeat": self.title_repeat_var.get(),
            "emphasis_fontsize": self.emphasis_fontsize_var.get(),
            "safety_appeal_points": self.sheet_data.get("safety_appeals", {}).get(self.product_var.get(), []),
        }

    def _on_preview(self):
        inp = self._gather_inputs()
        if not inp:
            return
        prompt, sample_used = self._build_prompt_from_inputs(inp)
        self.result_text.delete('1.0', tk.END)
        self.result_text.insert('1.0', prompt)
        self._highlight_result()
        self.status_var.set(f"프롬프트 미리보기 ({len(prompt):,}자)")

    def _build_prompt_from_inputs(self, inp):
        """inp 딕셔너리로 build_prompt 호출"""
        return build_prompt(
            self.sheet_data, inp["product"], inp["prompt_type"], inp["style_name"],
            inp["tone"], inp["font_size"], inp["alignment"], inp["quote_num"],
            inp["keywords"], inp["sub_keywords"],
            inp["selected_refs"], inp["extra"], inp["include_toc"],
            product_link=inp["product_link"],
            char_count=inp["char_count"],
            img_count=inp["img_count"],
            color_positive=inp["color_positive"], color_negative=inp["color_negative"],
            highlight_emphasis=inp["highlight_emphasis"],
            color_product=inp["color_product"], highlight_product=inp["highlight_product"],
            title_repeat=inp["title_repeat"],
            emphasis_fontsize=inp["emphasis_fontsize"],
            safety_appeal_points=inp.get("safety_appeal_points"),
        )

    def _on_generate(self):
        """바로 원고 생성 (페르소나/제목 단계 없음 — 프롬프트에 제목 패턴 포함)"""
        if self.is_generating:
            messagebox.showinfo("진행 중", "생성이 진행 중입니다.")
            return
        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning("API Key", "설정 탭에서 Claude API Key를 입력해주세요.")
            return
        inp = self._gather_inputs()
        if not inp:
            return

        prompt, sample_used = self._build_prompt_from_inputs(inp)

        self.is_generating = True
        self._set_buttons_state('disabled')
        self.result_text.delete('1.0', tk.END)

        self.result_text.insert('1.0', "원고 생성 중... (30초~2분)")
        self.status_var.set("원고 생성 중...")

        def on_complete(result):
            def update():
                clean = result.replace('**', '')
                clean = re.sub(r'^ㄴ\s*\([^)]+\)\s*$', '', clean, flags=re.MULTILINE)
                clean = re.sub(r'^0(\d)$', r'\1', clean, flags=re.MULTILINE)

                self.result_text.delete('1.0', tk.END)
                self.result_text.insert('1.0', clean)
                self._highlight_result()
                self.is_generating = False
                self._set_buttons_state('normal')

                auto_path = self._auto_save(clean, inp)
                char_count = len(clean)
                self.status_var.set(f"생성 완료! ({char_count:,}자) — {os.path.basename(auto_path)}")

            self.root.after(0, update)

        def on_error(err):
            def update():
                self.result_text.delete('1.0', tk.END)
                self.result_text.insert('1.0', f"오류:\n{err}")
                self.is_generating = False
                self._set_buttons_state('normal')
            self.root.after(0, update)

        threading.Thread(target=call_claude_api,
                         args=(api_key, prompt, on_complete, on_error),
                         daemon=True).start()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 세트 배치 생성
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 저장
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _auto_save(self, text, inp):
        """output/ 폴더에 자동 저장 (txt)"""
        date = self.date_var.get().strip() or datetime.datetime.now().strftime("%y%m%d")
        kw = inp.get("keywords", "").replace(" ", "")[:20]
        product_code = get_product_code(inp["product"], self.sheet_data)
        fname = f"심의_{date}_{kw}_{product_code}.txt"
        fpath = os.path.join(OUTPUT_DIR, fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(text)
        return fpath

    def _make_filename(self, ext):
        """파일명 생성: 이름_날짜키워드_원고유형"""
        author = self.author_var.get().strip() or "작가"
        date = self.date_var.get().strip()
        keyword = self.keyword_entry.get().strip().split(',')[0].strip().replace(' ', '')
        # 원고유형 축약 (긴 이름에서 핵심만)
        ptype = self.prompt_var.get().strip()
        short_type_map = {
            '심의 안전형': '심의형',
            '정보 탐색 큐레이션형': '큐레이션형',
            '제3자 관찰형': '제3자형',
        }
        ptype_short = short_type_map.get(ptype, ptype)
        return f"{author}_{date}{keyword[:15]}_{ptype_short}{ext}"

    def _on_save_docx(self):
        content = self.result_text.get('1.0', tk.END).strip()
        if not content or len(content) < 50:
            messagebox.showwarning("저장", "저장할 원고가 없습니다.")
            return
        fpath = filedialog.asksaveasfilename(
            initialdir=OUTPUT_DIR,
            defaultextension=".docx",
            filetypes=[("Word 문서", "*.docx")],
            initialfile=self._make_filename(".docx")
        )
        if fpath:
            save_as_docx(content, fpath)
            self.status_var.set(f"Word 저장 완료: {os.path.basename(fpath)}")
            os.startfile(fpath)

    def _on_save_txt(self):
        content = self.result_text.get('1.0', tk.END).strip()
        if not content or len(content) < 50:
            messagebox.showwarning("저장", "저장할 원고가 없습니다.")
            return
        fpath = filedialog.asksaveasfilename(
            initialdir=OUTPUT_DIR,
            defaultextension=".txt",
            filetypes=[("텍스트", "*.txt")],
            initialfile=self._make_filename(".txt")
        )
        if fpath:
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(content)
            self.status_var.set(f"텍스트 저장 완료: {os.path.basename(fpath)}")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 유틸리티
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _set_buttons_state(self, state):
        self.generate_btn.config(state=state)
        self.review_btn.config(state=state)

    def _highlight_result(self):
        """결과 텍스트에 색상 태그 적용"""
        content = self.result_text.get('1.0', tk.END)
        for tag in ("annotation", "img_num", "blogger_req"):
            self.result_text.tag_remove(tag, '1.0', tk.END)

        for i, line in enumerate(content.split('\n'), 1):
            stripped = line.strip()
            if stripped.startswith('ㄴ'):
                self.result_text.tag_add("annotation", f"{i}.0", f"{i}.end")
            elif re.match(r'^\d{1,2}$', stripped):
                self.result_text.tag_add("img_num", f"{i}.0", f"{i}.end")
            elif '★' in stripped:
                self.result_text.tag_add("blogger_req", f"{i}.0", f"{i}.end")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 검수 (소구점/어색한 표현/서식 누락 체크)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _on_review(self):
        content = self.result_text.get('1.0', tk.END).strip()
        if not content or len(content) < 100:
            messagebox.showwarning("검수", "검수할 원고가 없습니다.\n원고를 먼저 생성해주세요.")
            return
        if self.is_generating:
            messagebox.showinfo("진행 중", "생성이 진행 중입니다.")
            return

        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning("API Key", "설정 탭에서 Claude API Key를 입력해주세요.")
            return

        product = self.product_var.get()
        product_guide = self.sheet_data["products"].get(product, "")
        keywords = self.keyword_entry.get().strip()
        sub_keywords = self.sub_keyword_entry.get().strip()

        # 심의안전 소구점 정보도 포함
        safety_points = self.sheet_data.get("safety_appeals", {}).get(product, [])
        review_prompt = self._build_review_prompt(content, product, product_guide,
                                                   keywords, sub_keywords, safety_points)

        self.is_generating = True
        self._set_buttons_state('disabled')
        self.status_var.set("검수 중... (10~30초 소요)")

        def on_review_complete(result):
            def update():
                self.is_generating = False
                self._set_buttons_state('normal')
                self.status_var.set("검수 완료")
                self._show_review_dialog(result)
            self.root.after(0, update)

        def on_review_error(err):
            def update():
                self.is_generating = False
                self._set_buttons_state('normal')
                self.status_var.set("검수 오류")
                messagebox.showerror("검수 오류", f"검수 중 오류가 발생했습니다:\n{err}")
            self.root.after(0, update)

        threading.Thread(target=call_claude_api,
                         args=(api_key, review_prompt, on_review_complete, on_review_error, 4096),
                         daemon=True).start()

    def _build_review_prompt(self, manuscript, product, product_guide,
                              keywords, sub_keywords, safety_points=None):
        parts = [
            "당신은 건강/의학 마케팅 블로그 원고 검수 전문가입니다.",
            "아래 원고를 검수하여 문제점을 찾아주세요.",
            "이 원고는 '심의안전' 원고로, 제품명을 직접 언급하지 않고 간접적으로 소구하는 방식입니다.",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "■ 검수 항목",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "【1. 소구점 반영 검수】",
            "- 제품 가이드에 명시된 핵심 소구점이 원고에 빠짐없이 반영되었는지 확인",
            "- 심의안전 강조점이 자연스럽게 녹아들었는지 확인",
            "- 누락된 소구점이 있으면 구체적으로 어떤 소구점이 빠졌는지 지적",
            "",
            "【2. 어색한 표현 검수】",
            "- 문맥상 어색하거나 부자연스러운 표현 지적",
            "- 과장되거나 비현실적인 표현 지적",
            "- 맞춤법/문법 오류 지적",
            "- 같은 표현이 과도하게 반복되는 부분 지적",
            "- 문장 간 논리적 흐름이 어색한 부분 지적",
            "",
            "【3. 서식 누락 검수】",
            "- 'ㄴ' 서식 지시가 적절히 들어갔는지 확인",
            "- 이미지 번호(0, 1, 2...)가 순서대로 있는지 확인",
            "- ★블로거 요청사항★ 섹션이 있는지 확인",
            "- 인용구, 볼드, 색상 등 서식 지시가 누락된 곳이 있는지 확인",
            "- 해시태그가 원고 어디에도 포함되지 않았는지 확인",
            "",
            "【4. 심의안전 검수】",
            "- 제품명이 본문에 직접 노출되지 않았는지 확인",
            "- 의약품/건기식 심의 위반 표현이 없는지 확인 (확정적 효능 표현, 진단/치료 암시 등)",
            "- 병원 진료 권고가 적절히 포함되었는지 확인",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "■ 검수 대상 정보",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]

        if product:
            parts.append(f"\n[제품명] {product}")
        if product_guide:
            parts.append(f"\n[제품 가이드 (소구점 기준)]\n{product_guide[:5000]}")
        if safety_points:
            parts.append("\n[심의안전 소구점]")
            for i, pt in enumerate(safety_points, 1):
                parts.append(f"  {i}. {pt}")
        if keywords:
            parts.append(f"\n[메인 키워드] {keywords}")
        if sub_keywords:
            parts.append(f"\n[연관 키워드] {sub_keywords}")

        parts.append(f"\n[원고 전문]\n{manuscript}")

        parts.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "■ 검수 결과 작성 형식",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "아래 형식으로 검수 결과를 작성해주세요:",
            "",
            "【1. 소구점 반영 검수】",
            "✅ 반영된 소구점: (목록)",
            "❌ 누락된 소구점: (목록, 없으면 '없음')",
            "💡 개선 제안: (있으면 작성)",
            "",
            "【2. 어색한 표현 검수】",
            "각 문제마다:",
            "- 위치: (해당 문장 인용)",
            "- 문제: (어떤 점이 어색한지)",
            "- 수정안: (개선된 문장)",
            "",
            "【3. 서식 누락 검수】",
            "- 이미지 번호: (순서 확인 결과)",
            "- ㄴ 서식 지시: (누락 여부)",
            "- ★블로거 요청사항★: (존재 여부)",
            "- 기타 서식 문제: (있으면 작성)",
            "",
            "【4. 심의안전 검수】",
            "- 제품명 노출: (있으면 위치 지적)",
            "- 심의 위반 표현: (있으면 지적 + 수정안)",
            "- 병원 진료 권고: (포함 여부)",
            "",
            "【종합 평가】",
            "- 총점: __/100",
            "- 한줄 요약: (원고의 전반적 품질 평가)",
        ])

        return "\n".join(parts)

    def _show_review_dialog(self, review_result):
        dialog = tk.Toplevel(self.root)
        dialog.title("검수 결과")
        dialog.geometry("900x700")
        dialog.transient(self.root)

        ttk.Label(dialog, text="검수 결과",
                  font=('맑은 고딕', 13, 'bold')).pack(pady=(15, 10), padx=15)

        text_frame = ttk.Frame(dialog)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))

        review_text = scrolledtext.ScrolledText(text_frame, wrap=tk.WORD,
                                                 font=('맑은 고딕', 10), height=30)
        review_text.pack(fill=tk.BOTH, expand=True)
        review_text.insert('1.0', review_result)

        # 검수 결과 하이라이트
        for tag_name, pattern, fg_color in [
            ("header", r'【.+?】', '#1a237e'),
            ("pass", r'✅.*', '#2e7d32'),
            ("fail", r'❌.*', '#c62828'),
            ("tip", r'💡.*', '#e65100'),
        ]:
            review_text.tag_configure(tag_name, foreground=fg_color, font=('맑은 고딕', 10, 'bold'))
            content = review_text.get('1.0', tk.END)
            for m in re.finditer(pattern, content):
                line_num = content[:m.start()].count('\n') + 1
                col_start = m.start() - content.rfind('\n', 0, m.start()) - 1
                col_end = col_start + len(m.group())
                review_text.tag_add(tag_name, f"{line_num}.{col_start}", f"{line_num}.{col_end}")

        ttk.Label(dialog, text="검수 내용을 직접 수정한 후 '수정 재생성'을 누르세요",
                  font=('맑은 고딕', 9), foreground='#666').pack(padx=15, pady=(0, 5))

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=15, pady=(0, 15))

        def copy_result():
            content = review_text.get('1.0', tk.END).strip()
            dialog.clipboard_clear()
            dialog.clipboard_append(content)
            messagebox.showinfo("복사", "검수 결과가 클립보드에 복사되었습니다.", parent=dialog)

        def on_revise():
            edited_review = review_text.get('1.0', tk.END).strip()
            if not edited_review:
                messagebox.showwarning("검수", "검수 내용이 비어있습니다.", parent=dialog)
                return
            dialog.destroy()
            self._revise_manuscript(edited_review)

        ttk.Button(btn_frame, text="수정 재생성", style='Generate.TButton',
                   command=on_revise).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn_frame, text="결과 복사", command=copy_result).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn_frame, text="닫기", command=dialog.destroy).pack(side=tk.LEFT)

    def _revise_manuscript(self, review_result):
        """검수 결과를 기반으로 원고 수정 재생성"""
        original = self.result_text.get('1.0', tk.END).strip()
        api_key = self.api_key_var.get().strip()

        if not original or not api_key:
            return

        revise_prompt = self._build_revise_prompt(original, review_result)

        self.is_generating = True
        self._set_buttons_state('disabled')
        self.result_text.delete('1.0', tk.END)
        self.result_text.insert('1.0', "검수 기반 수정 재생성 중... (30초~2분 소요)")
        self.status_var.set("수정 재생성 중...")

        def on_complete(result):
            def update():
                clean = result.replace('**', '')
                clean = re.sub(r'^ㄴ\s*\([^)]+\)\s*$', '', clean, flags=re.MULTILINE)
                clean = re.sub(r'^0(\d)$', r'\1', clean, flags=re.MULTILINE)

                self.result_text.delete('1.0', tk.END)
                self.result_text.insert('1.0', clean)
                self._highlight_result()
                self.is_generating = False
                self._set_buttons_state('normal')

                auto_path = self._auto_save(clean, {"product": self.product_var.get(),
                                                      "prompt_type": self.prompt_var.get()})
                char_count = len(clean)
                self.status_var.set(f"수정 완료! ({char_count:,}자) — {os.path.basename(auto_path)}")
            self.root.after(0, update)

        def on_error(err):
            def update():
                self.result_text.delete('1.0', tk.END)
                self.result_text.insert('1.0', f"수정 재생성 오류:\n{err}")
                self.status_var.set("오류 발생")
                self.is_generating = False
                self._set_buttons_state('normal')
            self.root.after(0, update)

        threading.Thread(target=call_claude_api,
                         args=(api_key, revise_prompt, on_complete, on_error, 8192),
                         daemon=True).start()

    def _build_revise_prompt(self, original_manuscript, review_result):
        parts = [
            "당신은 건강/의학 마케팅 블로그 원고 수정 전문가입니다.",
            "",
            "아래 원고를 검수 결과에 따라 수정해주세요.",
            "이 원고는 '심의안전' 원고로, 제품명을 직접 언급하지 않고 간접적으로 소구하는 방식입니다.",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "■ 수정 규칙",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "1. 검수에서 지적된 문제점만 수정합니다.",
            "2. 문제가 없는 부분은 원문 그대로 유지합니다.",
            "3. 원고의 전체 구조, 서식(ㄴ 지시, 이미지 번호, ★블로거 요청사항★)을 그대로 유지합니다.",
            "4. 누락된 소구점이 있으면 자연스럽게 녹여 넣습니다.",
            "5. 어색한 표현은 검수의 수정안을 참고하여 고칩니다.",
            "6. 서식 누락이 있으면 보완합니다.",
            "7. 제품명을 직접 노출하지 않습니다 (심의안전 원칙).",
            "8. 수정된 원고 전문만 출력합니다. 설명이나 주석은 붙이지 마세요.",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "■ 검수 결과 (수정해야 할 사항)",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            review_result,
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "■ 원본 원고 (이것을 수정해주세요)",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            original_manuscript,
        ]
        return "\n".join(parts)
