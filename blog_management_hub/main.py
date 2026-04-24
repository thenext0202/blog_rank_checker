"""블로그 관리 허브 — 5개 블로그 자동화 도구 통합"""

import os
import sys
import tkinter as tk
from tkinter import ttk

# EXE 경로 자동 감지
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

from shared.sheets_client import SheetsClient
from tabs.tab_comment_monitor import CommentMonitorTab
from tabs.tab_link_checker import LinkCheckerTab
from tabs.tab_reply_bot import ReplyBotTab
from tabs.tab_auto_publisher import AutoPublisherTab
from tabs.tab_comment_checker import CommentCheckerTab


class BlogManagementHub(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("블로그 관리 허브")
        self.geometry("900x700")
        self.minsize(800, 600)
        self.sheets = SheetsClient()
        self._build()

    def _build(self):
        # 상단 제목
        header = ttk.Frame(self, padding=(10, 8))
        header.pack(fill="x")
        ttk.Label(
            header,
            text="블로그 관리 허브",
            font=("맑은 고딕", 16, "bold"),
        ).pack(side="left")

        # 탭 노트북
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        # 탭 1: 대댓글 봇
        tab1 = ReplyBotTab(self.notebook, self.sheets)
        self.notebook.add(tab1, text="  대댓글&비공  ")

        # 탭 2: 댓글 알림
        tab2 = CommentMonitorTab(self.notebook)
        self.notebook.add(tab2, text="  댓글 알림  ")

        # 탭 3: MKT 링크 대조
        tab3 = LinkCheckerTab(self.notebook, self.sheets)
        self.notebook.add(tab3, text="  상품 링크 대조  ")

        # 탭 4: 자동 발행
        tab4 = AutoPublisherTab(self.notebook, self.sheets)
        self.notebook.add(tab4, text="  템플릿 자동발행  ")

        # 탭 5: 댓글 검수
        tab5 = CommentCheckerTab(self.notebook, self.sheets)
        self.notebook.add(tab5, text="  중복 누락 댓글 체크  ")

        # 대댓글 봇 탭을 기본 선택
        self.notebook.select(tab1)

        # 하단 상태바
        status = ttk.Frame(self, padding=(10, 3))
        status.pack(fill="x", side="bottom")
        ttk.Separator(self).pack(fill="x", side="bottom")
        self.status_label = ttk.Label(
            status, text="대기 중", font=("맑은 고딕", 9)
        )
        self.status_label.pack(side="left")


if __name__ == "__main__":
    app = BlogManagementHub()
    app.mainloop()
