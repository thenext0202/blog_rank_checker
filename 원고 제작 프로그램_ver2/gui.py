"""원고 작성기 — tkinter GUI"""
import os
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import config
from instruction_loader import (
    load_instructions, get_md_file_list,
    load_product_info_from_folder
)
from prompt_builder import build_prompt, build_product_link, parse_phases
from api_client import generate_manuscript_async, MODELS


class ManuscriptWriterApp:
    # 색상 테마 (모던라이트)
    THEME = {
        "bg": "#dcdad5",
        "frame_bg": "#e8e6e1",
        "accent": "#4a6984",
        "accent2": "#2e7d32",
        "warn": "#c62828",
        "text_bg": "#ffffff",
        "label_fg": "#333333",
        "entry_bg": "#ffffff",
        "btn_fg": "#ffffff",
    }

    def __init__(self, root):
        self.root = root
        self.root.title(f"원고 작성기 v{config.VERSION}")
        self.root.geometry("900x800")
        self.root.configure(bg=self.THEME["bg"])
        self.root.minsize(800, 700)

        # 상태 변수
        self.is_generating = False
        self.spreadsheet = None
        self.products = []  # 제품 정보 목록
        self.instructions = None  # 현재 로드된 지침
        self.last_phases = None  # 마지막 생성 결과 (Phase A/B/C 분리)

        # GUI 변수
        self.api_key_var = tk.StringVar(value=config.load_api_key())
        self.sheet_id_var = tk.StringVar(value=config.load_sheet_id())
        self.instructions_dir_var = tk.StringVar(value=config.load_instructions_dir())
        self.products_dir_var = tk.StringVar(value=config.load_products_dir())
        self.keyword_var = tk.StringVar()
        self.product_var = tk.StringVar()
        self.date_var = tk.StringVar(value=datetime.datetime.now().strftime("%y%m%d"))
        self.medium_var = tk.StringVar()
        self.product_link_var = tk.StringVar()
        self.model_var = tk.StringVar(value="Sonnet")
        self.status_var = tk.StringVar(value="준비")

        # 링크 자동 갱신 trace
        self.keyword_var.trace_add("write", self._update_product_link)
        self.product_var.trace_add("write", self._update_product_link)
        self.date_var.trace_add("write", self._update_product_link)
        self.medium_var.trace_add("write", self._update_product_link)

        self._setup_styles()
        self._build_ui()
        self._init_load()

    # ── 스타일 설정 ──
    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=self.THEME["bg"])
        style.configure("Card.TFrame", background=self.THEME["frame_bg"])
        style.configure("TLabel", background=self.THEME["bg"],
                        foreground=self.THEME["label_fg"], font=("맑은 고딕", 10))
        style.configure("Card.TLabel", background=self.THEME["frame_bg"],
                        foreground=self.THEME["label_fg"], font=("맑은 고딕", 10))
        style.configure("Header.TLabel", background=self.THEME["bg"],
                        foreground=self.THEME["accent"], font=("맑은 고딕", 11, "bold"))
        style.configure("Accent.TButton", foreground=self.THEME["btn_fg"],
                        background=self.THEME["accent"], font=("맑은 고딕", 10, "bold"))
        style.map("Accent.TButton",
                  background=[("active", "#5a7994"), ("disabled", "#999999")])
        style.configure("Green.TButton", foreground=self.THEME["btn_fg"],
                        background=self.THEME["accent2"], font=("맑은 고딕", 10, "bold"))
        style.map("Green.TButton",
                  background=[("active", "#388e3c"), ("disabled", "#999999")])
        style.configure("Status.TLabel", background=self.THEME["bg"],
                        foreground=self.THEME["accent"], font=("맑은 고딕", 9))

    # ── UI 구성 ──
    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill="both", expand=True)

        # 탭 구성
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill="both", expand=True)

        # 원고 작성 탭
        self.write_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.write_tab, text=" 원고 작성 ")

        self._build_input_frame(self.write_tab)
        self._build_result_frame(self.write_tab)
        self._build_action_frame(self.write_tab)

        # 설정 탭
        self.settings_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.settings_tab, text=" 설정 ")

        self._build_settings_frame(self.settings_tab)

        self._build_status_bar(main_frame)

    def _build_settings_frame(self, parent):
        """설정 탭: API키, 시트ID, 지침 폴더, 제품 폴더"""
        # API 키
        sec = ttk.LabelFrame(parent, text=" Claude API ", padding=10)
        sec.pack(fill="x", pady=(0, 10))
        row = ttk.Frame(sec)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="API 키:", width=10, style="Card.TLabel").pack(side="left")
        ttk.Entry(row, textvariable=self.api_key_var, show="*", width=50).pack(
            side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(row, text="저장", width=6,
                   command=self._save_api_key).pack(side="left")

        # 구글 시트
        sec = ttk.LabelFrame(parent, text=" 구글 시트 ", padding=10)
        sec.pack(fill="x", pady=(0, 10))
        row = ttk.Frame(sec)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="시트 ID:", width=10, style="Card.TLabel").pack(side="left")
        ttk.Entry(row, textvariable=self.sheet_id_var, width=50).pack(
            side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(row, text="저장", width=6,
                   command=self._save_sheet_id).pack(side="left", padx=(0, 3))
        ttk.Button(row, text="연결", width=6, style="Accent.TButton",
                   command=self._connect_sheet).pack(side="left")

        # 지침 / 제품 폴더
        sec = ttk.LabelFrame(parent, text=" 지침 및 제품 정보 ", padding=10)
        sec.pack(fill="x", pady=(0, 10))

        row = ttk.Frame(sec)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="지침 폴더:", width=10, style="Card.TLabel").pack(side="left")
        ttk.Entry(row, textvariable=self.instructions_dir_var, width=50).pack(
            side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(row, text="선택", width=6,
                   command=self._select_instructions_dir).pack(side="left", padx=(0, 3))
        ttk.Button(row, text="로드", width=6, style="Accent.TButton",
                   command=self._load_instructions).pack(side="left")

        row = ttk.Frame(sec)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="제품 폴더:", width=10, style="Card.TLabel").pack(side="left")
        ttk.Entry(row, textvariable=self.products_dir_var, width=50).pack(
            side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(row, text="선택", width=6,
                   command=self._select_products_dir).pack(side="left", padx=(0, 3))
        ttk.Button(row, text="로드", width=6, style="Accent.TButton",
                   command=self._load_products).pack(side="left")

        # 지침 파일 목록
        ttk.Label(sec, text="로드된 지침 파일:", style="Card.TLabel").pack(
            anchor="w", pady=(8, 2))
        self.instructions_listbox = tk.Listbox(sec, height=6, font=("맑은 고딕", 9),
                                                bg=self.THEME["text_bg"])
        self.instructions_listbox.pack(fill="x")

    def _build_input_frame(self, parent):
        """입력 프레임: 키워드, 제품, 날짜, medium, 모델, 제품링크"""
        frame = ttk.LabelFrame(parent, text=" 원고 정보 ", padding=8)
        frame.pack(fill="x", pady=5)

        # 키워드
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="키워드:", width=10, style="Card.TLabel").pack(side="left")
        ttk.Entry(row, textvariable=self.keyword_var, width=50,
                  font=("맑은 고딕", 11)).pack(side="left", fill="x", expand=True)

        # 제품 선택
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="제품:", width=10, style="Card.TLabel").pack(side="left")
        self.product_combo = ttk.Combobox(row, textvariable=self.product_var,
                                          width=47, state="readonly")
        self.product_combo.pack(side="left", fill="x", expand=True)

        # 날짜 + medium + 모델 선택
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="날짜:", width=10, style="Card.TLabel").pack(side="left")
        ttk.Entry(row, textvariable=self.date_var, width=12).pack(side="left", padx=(0, 15))
        ttk.Label(row, text="medium:", style="Card.TLabel").pack(side="left", padx=(0, 5))
        ttk.Entry(row, textvariable=self.medium_var, width=15).pack(side="left", padx=(0, 15))
        ttk.Label(row, text="모델:", style="Card.TLabel").pack(side="left", padx=(0, 5))
        model_combo = ttk.Combobox(row, textvariable=self.model_var,
                                   values=list(MODELS.keys()), width=10, state="readonly")
        model_combo.pack(side="left")

        # 제품 링크 (자동 생성 + 편집 가능)
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="제품링크:", width=10, style="Card.TLabel").pack(side="left")
        ttk.Entry(row, textvariable=self.product_link_var, width=50,
                  font=("맑은 고딕", 9)).pack(side="left", fill="x", expand=True)

    def _build_result_frame(self, parent):
        """결과 프레임: 완성 원고 텍스트"""
        frame = ttk.LabelFrame(parent, text=" 완성 원고 ", padding=8)
        frame.pack(fill="both", expand=True, pady=5)

        self.result_text = scrolledtext.ScrolledText(
            frame, wrap="word", font=("맑은 고딕", 10),
            bg=self.THEME["text_bg"], height=15
        )
        self.result_text.pack(fill="both", expand=True)

    def _build_action_frame(self, parent):
        """액션 버튼 프레임"""
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=5)

        self.generate_btn = ttk.Button(
            frame, text="원고 생성", style="Accent.TButton",
            command=self._generate_manuscript
        )
        self.generate_btn.pack(side="left", padx=(0, 10))

        self.sheet_btn = ttk.Button(
            frame, text="시트 기입", style="Green.TButton",
            command=self._write_to_sheet
        )
        self.sheet_btn.pack(side="left", padx=(0, 10))

        # 워드 저장 버튼 (비활성 — 서식 지침 받은 후 구현)
        self.word_btn = ttk.Button(
            frame, text="워드 저장", state="disabled",
            command=lambda: None
        )
        self.word_btn.pack(side="left", padx=(0, 10))

        ttk.Button(frame, text="초기화",
                   command=self._clear_all).pack(side="right")

    def _build_status_bar(self, parent):
        """상태바"""
        ttk.Label(parent, textvariable=self.status_var,
                  style="Status.TLabel").pack(fill="x", pady=(5, 0))

    # ── 설정 관련 ──
    def _save_api_key(self):
        config.save_api_key(self.api_key_var.get())
        self._set_status("API 키 저장 완료")

    def _save_sheet_id(self):
        config.save_sheet_id(self.sheet_id_var.get())
        self._set_status("시트 ID 저장 완료")

    def _select_instructions_dir(self):
        folder = filedialog.askdirectory(title="지침 폴더 선택")
        if folder:
            self.instructions_dir_var.set(folder)
            config.save_instructions_dir(folder)
            self._load_instructions()

    def _connect_sheet(self):
        """구글 시트 연결"""
        sheet_id = self.sheet_id_var.get().strip()
        if not sheet_id:
            messagebox.showwarning("경고", "시트 ID를 입력하세요.")
            return
        try:
            self._set_status("시트 연결 중...")
            from sheet_writer import connect_sheet
            self.spreadsheet = connect_sheet(sheet_id)
            self._set_status("시트 연결 완료")
        except Exception as e:
            self._set_status(f"시트 연결 실패: {e}")
            messagebox.showerror("오류", f"시트 연결 실패:\n{e}")

    def _select_products_dir(self):
        """제품 정보 폴더 선택"""
        folder = filedialog.askdirectory(title="제품 정보 폴더 선택")
        if folder:
            self.products_dir_var.set(folder)
            config.save_products_dir(folder)
            self._load_products()

    def _load_products(self):
        """제품 정보 MD 파일에서 제품 목록 로드"""
        folder = self.products_dir_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("경고", "유효한 제품 정보 폴더를 선택하세요.")
            return
        self.products = load_product_info_from_folder(folder)
        product_names = [p["name"] for p in self.products]
        self.product_combo["values"] = product_names
        if product_names:
            self.product_combo.current(0)
        self._set_status(f"제품 로드 완료 ({len(self.products)}개)")

    def _load_instructions(self):
        """지침 폴더에서 MD 파일 로드"""
        folder = self.instructions_dir_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("경고", "유효한 지침 폴더를 선택하세요.")
            return
        self.instructions = load_instructions(folder)
        md_files = get_md_file_list(folder)
        self.instructions_listbox.delete(0, "end")
        for fname in md_files:
            self.instructions_listbox.insert("end", fname)
        self._set_status(f"지침 로드 완료 ({len(md_files)}개 파일)")

    def _init_load(self):
        """초기 데이터 로드 (저장된 폴더가 있으면 자동 로드)"""
        folder = self.instructions_dir_var.get().strip()
        if folder and os.path.isdir(folder):
            self._load_instructions()
        products_folder = self.products_dir_var.get().strip()
        if products_folder and os.path.isdir(products_folder):
            self._load_products()

    # ── 제품 링크 자동 갱신 ──
    def _update_product_link(self, *args):
        """키워드/제품/날짜/medium 변경 시 제품 링크 자동 생성"""
        product_name = self.product_var.get()
        keyword = self.keyword_var.get()
        date = self.date_var.get()
        medium = self.medium_var.get()

        if not product_name or not keyword:
            return

        product = next((p for p in self.products if p["name"] == product_name), None)
        if not product:
            return

        link = build_product_link(
            product["base_link"], product["code"], date, keyword, medium
        )
        self.product_link_var.set(link)

    # ── 선택한 제품의 MD 파일 경로 ──
    def _get_selected_product_file(self):
        """현재 선택된 제품의 MD 파일 경로 반환"""
        product_name = self.product_var.get()
        product = next((p for p in self.products if p["name"] == product_name), None)
        if product:
            return product.get("file", "")
        return ""

    # ── 원고 생성 ──
    def _generate_manuscript(self):
        """Claude API로 원고 생성"""
        if self.is_generating:
            return

        api_key = self.api_key_var.get().strip()
        keyword = self.keyword_var.get().strip()

        if not api_key:
            messagebox.showwarning("경고", "API 키를 입력하세요.")
            return
        if not keyword:
            messagebox.showwarning("경고", "키워드를 입력하세요.")
            return
        if not self.instructions:
            messagebox.showwarning("경고", "지침을 먼저 로드하세요.")
            return

        # 프롬프트 조립 (선택 제품 MD만 포함)
        prompt = build_prompt(
            self.instructions,
            keyword,
            product_name=self.product_var.get(),
            product_link=self.product_link_var.get(),
            product_file_path=self._get_selected_product_file()
        )

        self.is_generating = True
        self.generate_btn.configure(state="disabled")
        self.result_text.delete("1.0", "end")
        self.last_phases = None

        model_key = self.model_var.get()
        self._set_status(f"원고 생성 중... (모델: {model_key})")

        def on_complete(text):
            self.root.after(0, self._on_generation_complete, text)

        def on_error(err):
            self.root.after(0, self._on_generation_error, err)

        generate_manuscript_async(api_key, prompt, on_complete, on_error,
                                  model_key=model_key)

    def _on_generation_complete(self, text):
        """원고 생성 완료 콜백"""
        self.is_generating = False
        self.generate_btn.configure(state="normal")

        # Phase A/B/C 분리
        self.last_phases = parse_phases(text)

        # 결과 텍스트에는 전체 출력 표시 (Phase C가 메인)
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text)

        # 글자수 (Phase C 기준)
        phase_c = self.last_phases["phase_c"]
        char_count = len(phase_c.replace(" ", "").replace("\n", ""))
        self._set_status(f"원고 생성 완료 (Phase C 공백제외 {char_count:,}자)")

    def _on_generation_error(self, err):
        """원고 생성 실패 콜백"""
        self.is_generating = False
        self.generate_btn.configure(state="normal")
        self._set_status(f"생성 실패: {err}")
        messagebox.showerror("오류", f"원고 생성 실패:\n{err}")

    # ── 시트 기입 ──
    def _write_to_sheet(self):
        """완성원고 탭에 Phase A/B/C 기입"""
        if not self.spreadsheet:
            messagebox.showwarning("경고", "시트를 먼저 연결하세요.")
            return

        full_text = self.result_text.get("1.0", "end-1c").strip()
        if not full_text:
            messagebox.showwarning("경고", "원고가 비어있습니다.")
            return

        keyword = self.keyword_var.get().strip()
        if not keyword:
            messagebox.showwarning("경고", "키워드를 입력하세요.")
            return

        # 텍스트 영역에서 수정했을 수 있으므로 다시 파싱
        phases = parse_phases(full_text)

        try:
            self._set_status("시트 기입 중...")
            from sheet_writer import write_manuscript

            row = write_manuscript(
                self.spreadsheet,
                keyword,
                self.product_var.get(),
                self.date_var.get(),
                self.medium_var.get(),
                self.product_link_var.get(),
                phase_c=phases["phase_c"],
                phase_a=phases["phase_a"],
                phase_b=phases["phase_b"]
            )

            self._set_status(f"시트 기입 완료 ({row}행)")

        except Exception as e:
            self._set_status(f"시트 기입 실패: {e}")
            messagebox.showerror("오류", f"시트 기입 실패:\n{e}")

    # ── 유틸리티 ──
    def _clear_all(self):
        """입력/결과 초기화"""
        self.keyword_var.set("")
        self.medium_var.set("")
        self.product_link_var.set("")
        self.date_var.set(datetime.datetime.now().strftime("%y%m%d"))
        self.result_text.delete("1.0", "end")
        self.last_phases = None
        self._set_status("초기화 완료")

    def _set_status(self, msg):
        """상태바 메시지 설정"""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.status_var.set(f"[{timestamp}] {msg}")
