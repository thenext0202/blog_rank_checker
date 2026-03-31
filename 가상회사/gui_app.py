"""
가상회사 — 사무실 GUI (pygame)
직원들이 방에 앉아있고, 업무 시 프로젝트실/회의실로 이동
직원 클릭 → 능력 팝업 + 대화하기 버튼
"""
import sys
import os
import pygame
import threading
import queue

from company import VirtualCompany
from config import AGENTS, API_KEY, save_api_key, load_api_key
import config


# ── 색상 ──────────────────────────────────────────

class C:
    BG = (35, 39, 46)
    FLOOR = (48, 53, 62)
    ROOM = (58, 64, 75)
    ROOM_BORDER = (90, 98, 115)
    MEETING = (70, 60, 82)
    PROJECT = (55, 75, 68)
    CEO = (80, 70, 50)
    CHAT_BG = (28, 31, 38)
    INPUT_BG = (45, 50, 60)
    TEXT = (210, 215, 225)
    DIM = (120, 125, 135)
    CEO_TEXT = (255, 215, 80)
    MGR_TEXT = (100, 175, 255)
    AGENT_TEXT = (190, 195, 205)
    SYS_TEXT = (140, 145, 155)
    ERR_TEXT = (255, 95, 95)
    BTN = (65, 115, 195)
    BTN_OFF = (55, 58, 68)
    WHITE = (255, 255, 255)
    GREEN = (80, 190, 80)
    YELLOW = (255, 200, 80)
    ORANGE = (255, 140, 40)
    BLUE = (80, 140, 255)


# 직원 색상
COLORS = {
    "manager": (90, 165, 245),
    "seo_strategist": (60, 200, 220),
    "content_director": (245, 140, 170),
    "traffic_manager": (245, 190, 85),
    "research_support": (130, 225, 155),
    "sns_crm": (255, 160, 120),
    "automation_dev": (185, 140, 245),
}

# 직원 짧은 이름
SHORT = {
    "manager": "하늘",
    "seo_strategist": "사루비아",
    "content_director": "지수",
    "traffic_manager": "릴리",
    "research_support": "피치",
    "sns_crm": "체리",
    "automation_dev": "데이지",
}

# 직원 직무 (캐릭터 아래 표시)
ROLE = {
    "manager": "팀장",
    "seo_strategist": "SEO 전략가",
    "content_director": "콘텐츠 마케터",
    "traffic_manager": "퍼포먼스 마케터",
    "research_support": "리서치",
    "sns_crm": "SNS/CRM",
    "automation_dev": "개발자",
}

# ── 사무실 레이아웃 (비율 기반, 기준 1100x440) ────

# 기준 해상도 (비율 계산용)
BASE_W, BASE_MAP_H = 1100, 440

# 방 정보 (비율 기반, 7명 + 회의실/프로젝트실/CEO실)
ROOMS_REL = [
    {"rx": 15/1100,  "ry": 20/440,  "rw": 140/1100, "rh": 140/440, "label": "하늘 팀장실",   "type": "personal"},
    {"rx": 170/1100, "ry": 20/440,  "rw": 140/1100, "rh": 140/440, "label": "사루비아 개인실",   "type": "personal"},
    {"rx": 325/1100, "ry": 20/440,  "rw": 140/1100, "rh": 140/440, "label": "지수 개인실",   "type": "personal"},
    {"rx": 480/1100, "ry": 20/440,  "rw": 140/1100, "rh": 140/440, "label": "릴리 개인실",   "type": "personal"},
    {"rx": 635/1100, "ry": 20/440,  "rw": 140/1100, "rh": 140/440, "label": "피치 개인실",   "type": "personal"},
    {"rx": 790/1100, "ry": 20/440,  "rw": 140/1100, "rh": 140/440, "label": "체리 개인실", "type": "personal"},
    {"rx": 945/1100, "ry": 20/440,  "rw": 140/1100, "rh": 140/440, "label": "데이지 개인실", "type": "personal"},
    {"rx": 15/1100,  "ry": 200/440, "rw": 320/1100, "rh": 210/440, "label": "회의실",        "type": "meeting"},
    {"rx": 355/1100, "ry": 200/440, "rw": 320/1100, "rh": 210/440, "label": "프로젝트실",    "type": "project"},
    {"rx": 695/1100, "ry": 200/440, "rw": 390/1100, "rh": 210/440, "label": "CEO 이꼭지",    "type": "ceo"},
]

# 직원 홈 위치 (비율 — 각 방 중앙)
HOMES_REL = {
    "manager":          (85/1100,  100/440),
    "seo_strategist":   (240/1100, 100/440),
    "content_director": (395/1100, 100/440),
    "traffic_manager":  (550/1100, 100/440),
    "research_support": (705/1100, 100/440),
    "sns_crm":          (860/1100, 100/440),
    "automation_dev":   (1015/1100, 100/440),
}

# 프로젝트실/회의실 좌석 (비율, 7명 대응)
PROJECT_SEATS_REL = [(430/1100, 290/440), (480/1100, 330/440), (530/1100, 290/440), (580/1100, 330/440), (630/1100, 290/440), (500/1100, 370/440)]
MEETING_SEATS_REL = [(80/1100, 290/440), (140/1100, 290/440), (200/1100, 290/440), (260/1100, 330/440), (140/1100, 370/440), (200/1100, 370/440)]


def scale_pos(rx, ry, w, map_h):
    """비율 좌표 → 실제 픽셀"""
    return int(rx * w), int(ry * map_h)


# ── 메인 GUI ──────────────────────────────────────

class OfficeGUI:
    MIN_W, MIN_H = 800, 600

    def __init__(self):
        pygame.init()
        self.W, self.H = 1100, 780
        self.MAP_H = int(self.H * 0.564)  # 사무실 영역 비율 (440/780)
        self.screen = pygame.display.set_mode((self.W, self.H), pygame.RESIZABLE)
        pygame.display.set_caption("꼭지네 마케팅 인하우스")

        # 폰트 (맑은 고딕)
        fp = "C:/Windows/Fonts/malgun.ttf"
        fb = "C:/Windows/Fonts/malgunbd.ttf"
        self.f12 = pygame.font.Font(fp, 12)
        self.f14 = pygame.font.Font(fp, 14)
        self.f15 = pygame.font.Font(fp, 15)
        self.f18 = pygame.font.Font(fp, 18)
        self.fb20 = pygame.font.Font(fb, 20)

        # 회사 엔진
        self.company = VirtualCompany()

        # 직원 상태 (비율 좌표로 저장)
        self.agents = {}
        for aid, (rx, ry) in HOMES_REL.items():
            self.agents[aid] = {
                "rx": rx, "ry": ry,     # 현재 비율 좌표
                "home_rx": rx, "home_ry": ry,  # 홈 비율 좌표
                "target_rx": None, "target_ry": None,
                "status": "idle",
                "bubble": "",
                "bubble_tick": 0,
            }

        # 채팅
        self.log = []       # [(type, text), ...]
        self.input = ""
        self.composing = ""

        # 팝업
        self.popup = None   # {"agent_id", "name", "skills", "model"}

        # 처리
        self.busy = False
        self.eq = queue.Queue()
        self.cancel = False     # 중단 플래그

        # 직접 대화 모드
        self.direct = None  # agent_id 또는 None
        self._select_all = False  # Ctrl+A 전체 선택 상태
        self._scroll = 0  # 채팅 스크롤 (0=맨 아래, 양수=위로 올린 줄 수)

    # ── 실행 ──────────────────────────────

    def run(self):
        clock = pygame.time.Clock()
        pygame.key.start_text_input()
        pygame.key.set_repeat(400, 50)  # 꾹 누르기: 400ms 후 50ms 간격 반복

        # 시작 안내
        tm = sum(len(h) for h in self.company.histories.values())
        tn = len(self.company.notes)
        if tm > 0 or tn > 0:
            self.log.append(("sys", f"이전 기록 로드 — 대화 {tm}건, 업무노트 {tn}건"))
        self.log.append(("sys", "메시지를 입력하세요. 직원을 클릭하면 능력을 볼 수 있어요."))

        running = True
        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False

                elif ev.type == pygame.VIDEORESIZE:
                    self.W = max(ev.w, self.MIN_W)
                    self.H = max(ev.h, self.MIN_H)
                    self.MAP_H = int(self.H * 0.564)
                    self.screen = pygame.display.set_mode((self.W, self.H), pygame.RESIZABLE)

                elif ev.type == pygame.MOUSEWHEEL:
                    # 채팅 영역에서만 스크롤
                    mx, my = pygame.mouse.get_pos()
                    if my > self.MAP_H:
                        self._scroll = max(0, self._scroll + ev.y * 3)

                elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    self._click(ev.pos)

                elif ev.type == pygame.DROPFILE:
                    # 파일 드래그 앤 드롭
                    fpath = ev.file
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            content = f.read()
                        self._attached_file = {"name": os.path.basename(fpath), "content": content}
                        self.log.append(("sys", f"파일 첨부됨: {os.path.basename(fpath)} ({len(content)}자)"))
                        self.log.append(("sys", "다음 메시지에 이 파일 내용이 함께 전달됩니다."))
                    except Exception as e:
                        self.log.append(("err", f"파일 읽기 실패: {e}"))

                elif ev.type == pygame.TEXTINPUT:
                    if not self.popup:
                        if self._select_all:
                            self.input = ""
                            self._select_all = False
                        self.input += ev.text
                        self.composing = ""

                elif ev.type == pygame.TEXTEDITING:
                    if not self.popup:
                        self.composing = ev.text

                elif ev.type == pygame.KEYDOWN:
                    if self.popup:
                        if ev.key == pygame.K_ESCAPE:
                            self.popup = None
                    else:
                        if ev.key == pygame.K_BACKSPACE:
                            if self._select_all:
                                self.input = ""
                                self.composing = ""
                                self._select_all = False
                            elif self.composing:
                                self.composing = ""
                            elif self.input:
                                # Ctrl+Backspace: 단어 단위 삭제
                                if ev.mod & pygame.KMOD_CTRL:
                                    t = self.input.rstrip()
                                    while t and t[-1] != " ":
                                        t = t[:-1]
                                    self.input = t
                                else:
                                    self.input = self.input[:-1]
                        elif ev.key == pygame.K_a and (ev.mod & pygame.KMOD_CTRL):
                            self._select_all = True
                        elif ev.key == pygame.K_v and (ev.mod & pygame.KMOD_CTRL):
                            # Ctrl+V: 붙여넣기 (Windows API 직접 사용)
                            try:
                                pasted = self._get_clipboard()
                                if pasted:
                                    if self._select_all:
                                        self.input = ""
                                        self._select_all = False
                                    self.input += pasted.replace("\r\n", " ").replace("\n", " ")
                            except Exception:
                                pass
                        elif ev.key == pygame.K_RETURN:
                            self._send()
                        elif ev.key == pygame.K_ESCAPE:
                            if self.direct:
                                self.direct = None
                                self.log.append(("sys", "기본 모드로 복귀 (하늘 팀장이 업무 배정)"))

            self._drain_queue()
            self._animate()
            self._draw()
            clock.tick(60)

        self.company.save()
        pygame.quit()

    # ── 클릭 ──────────────────────────────

    def _click(self, pos):
        # 팝업 열려있으면
        if self.popup:
            # "대화하기" 버튼 클릭?
            pw, ph = 480, 380
            px = (self.W - pw) // 2
            py = (self.H - ph) // 2
            btn = pygame.Rect(px + pw - 130, py + ph - 50, 110, 35)
            if btn.collidepoint(pos):
                aid = self.popup["agent_id"]
                self.direct = aid
                name = SHORT[aid]
                self.log.append(("sys", f"{name}에게 직접 대화 모드 (ESC로 복귀)"))
                self.popup = None
                return
            self.popup = None
            return

        # 전송/중단 버튼
        input_h = self._input_height()
        btn = pygame.Rect(self.W - 85, self.H - input_h - 7, 70, 38)
        if btn.collidepoint(pos):
            if self.busy:
                self._cancel()
            else:
                self._send()
            return

        # 복사 버튼 (채팅 영역 우상단)
        copy_btn = pygame.Rect(self.W - 135, self.MAP_H + 5, 55, 24)
        if copy_btn.collidepoint(pos):
            self._copy_log()
            return

        # 업무노트 버튼
        notes_btn = pygame.Rect(self.W - 70, self.MAP_H + 5, 60, 24)
        if notes_btn.collidepoint(pos):
            self._open_notes()
            return

        # 직원 클릭 (사무실 영역)
        if pos[1] < self.MAP_H:
            for aid, ag in self.agents.items():
                ax, ay = scale_pos(ag["rx"], ag["ry"], self.W, self.MAP_H)
                if (pos[0] - ax) ** 2 + (pos[1] - ay) ** 2 < 28 ** 2:
                    self._popup(aid)
                    return

    def _popup(self, aid):
        """직원 능력 팝업"""
        cfg = AGENTS[aid]
        skills = []
        capture = False
        for line in cfg["system_prompt"].split("\n"):
            if any(k in line for k in ["전문 분야", "핵심 규정", "## 역할"]):
                capture = True
                continue
            if capture:
                if line.startswith("##"):
                    break
                s = line.strip()
                if s.startswith("-"):
                    skills.append(s[2:].strip())
                elif s and s[0].isdigit():
                    skills.append(s)
        self.popup = {
            "agent_id": aid,
            "name": cfg["name"],
            "skills": skills[:10],
            "model": cfg["model"],
        }

    # ── 클립보드 (Windows API) ────────────

    def _get_clipboard(self) -> str:
        """Windows API로 클립보드 텍스트 읽기 (한글 깨짐 방지)"""
        import ctypes
        import ctypes.wintypes
        CF_UNICODETEXT = 13
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        # 64비트 포인터 타입 명시
        user32.GetClipboardData.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        if not user32.OpenClipboard(0):
            return ""
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return ""
            try:
                return ctypes.wstring_at(ptr)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    # ── 이모지 → 텍스트 태그 변환 ────────

    EMOJI_MAP = {
        "📋": "[팀장]", "🔍": "[SEO]", "✍️": "[콘텐츠]", "📊": "[퍼포먼스]",
        "🔬": "[리서치]", "🤝": "[SNS]", "⚙️": "[개발]",
    }

    def _clean_emoji(self, text: str) -> str:
        """이모지를 텍스트 태그로 변환 (폰트 미지원 대응)"""
        for emoji, tag in self.EMOJI_MAP.items():
            text = text.replace(emoji, tag)
        return text

    # ── 응답 메모장 열기 ─────────────────

    def _open_response(self, text: str):
        """응답 내용을 메모장으로 열기"""
        import tempfile, subprocess
        # 마크다운 기호 제거
        clean = text.replace("**", "").replace("##", "").replace("```", "")
        try:
            tmp = os.path.join(tempfile.gettempdir(), "꼭지네_응답.txt")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(clean)
            subprocess.Popen(["notepad", tmp])
        except Exception:
            self.log.append(("err", "메모장 열기 실패"))

    # ── 대화 복사 ─────────────────────────

    def _copy_log(self):
        """대화 내역을 메모장으로 열기 (드래그 복사 가능)"""
        import tempfile, subprocess
        lines = []
        for mtype, text in self.log:
            if not text:
                lines.append("")
            else:
                lines.append(text)
        try:
            tmp = os.path.join(tempfile.gettempdir(), "꼭지네_대화내역.txt")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            subprocess.Popen(["notepad", tmp])
            self.log.append(("sys", "메모장에서 대화 내역을 열었습니다. 드래그로 복사하세요."))
        except Exception:
            self.log.append(("err", "메모장 열기 실패"))

    def _open_notes(self):
        """업무 노트를 메모장으로 열기"""
        import tempfile, subprocess
        notes = self.company.get_notes(last_n=50)
        if not notes:
            self.log.append(("sys", "아직 업무 노트가 없습니다."))
            return
        lines = ["═══ 업무 노트 (최근 50건) ═══", ""]
        for n in notes:
            lines.append(f"[{n['date']}] {n['agent']}")
            lines.append(f"  업무: {n['task']}")
            lines.append(f"  결과: {n['result_summary']}")
            lines.append("")
        try:
            tmp = os.path.join(tempfile.gettempdir(), "꼭지네_업무노트.txt")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            subprocess.Popen(["notepad", tmp])
            self.log.append(("sys", "메모장에서 업무 노트를 열었습니다."))
        except Exception:
            self.log.append(("err", "메모장 열기 실패"))

    # ── 입력창 높이 ──────────────────────

    def _input_height(self):
        """입력 텍스트 줄 수에 따른 입력창 높이 (최대 5줄)"""
        disp = self.input + self.composing
        if not disp:
            return 38
        input_w = self.W - 120  # 입력창 내부 너비
        lines = self._wrap_input(disp, input_w)
        n = min(len(lines), 5)  # 최대 5줄
        return max(38, n * 22 + 16)

    def _wrap_input(self, text, max_w):
        """입력 텍스트를 줄바꿈 (f15 폰트 기준)"""
        lines = []
        cur = ""
        for ch in text:
            if self.f15.size(cur + ch)[0] > max_w:
                if cur:
                    lines.append(cur)
                cur = ch
            else:
                cur += ch
        if cur:
            lines.append(cur)
        return lines if lines else [""]

    # ── 중단 ─────────────────────────────

    def _cancel(self):
        """작업 중단"""
        self.cancel = True
        self.log.append(("sys", "중단 요청! 현재 진행 중인 작업이 끝나면 멈춥니다."))
        # 모든 직원 즉시 복귀
        for ag in self.agents.values():
            if ag["status"] not in ("idle",):
                ag["target_rx"] = ag["home_rx"]
                ag["target_ry"] = ag["home_ry"]
                ag["status"] = "returning"
                ag["bubble"] = "중단됨"

    # ── 메시지 전송 ──────────────────────

    def _send(self):
        text = (self.input + self.composing).strip()
        if not text or self.busy:
            return
        self.input = ""
        self.composing = ""
        self._scroll = 0  # 새 메시지 → 맨 아래로

        # 명령어
        if text == "/메모":
            notes = self.company.get_notes(last_n=10)
            if not notes:
                self.log.append(("sys", "아직 업무 노트가 없습니다."))
            else:
                self.log.append(("sys", "─── 최근 업무 노트 ───"))
                for n in notes:
                    self.log.append(("sys", f"  {n['date']} {n['agent']}: {n['task'][:60]}"))
            return
        if text == "/리셋":
            self.company.reset_history()
            self.log.append(("sys", "대화 이력 초기화 완료 (업무 노트는 유지)"))
            return
        if text.startswith("/파일 "):
            # 파일 첨부: /파일 경로 → 파일 내용을 다음 메시지에 포함
            fpath = text[4:].strip().strip('"')
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                self._attached_file = {"name": os.path.basename(fpath), "content": content}
                self.log.append(("sys", f"파일 첨부됨: {os.path.basename(fpath)} ({len(content)}자)"))
                self.log.append(("sys", "다음 메시지에 이 파일 내용이 함께 전달됩니다."))
            except Exception as e:
                self.log.append(("err", f"파일 읽기 실패: {e}"))
            return

        # 첨부 파일이 있으면 메시지에 포함
        if hasattr(self, '_attached_file') and self._attached_file:
            af = self._attached_file
            text = f"[첨부 파일: {af['name']}]\n{af['content']}\n\n[지시사항]\n{text}"
            self._attached_file = None

        # 채팅에 표시
        if self.direct:
            self.log.append(("ceo", f"이꼭지 → {SHORT[self.direct]}: {text}"))
        else:
            self.log.append(("ceo", f"이꼭지: {text}"))

        self.busy = True
        self.cancel = False
        threading.Thread(target=self._api, args=(text,), daemon=True).start()

    def _api(self, text):
        """별도 스레드: API 호출"""
        def on_event(e):
            self.eq.put(e)

        def on_status(msg):
            self.eq.put({"type": "status", "message": msg})

        def is_cancelled():
            return self.cancel

        try:
            if self.cancel:
                return

            if self.direct == "manager":
                resp = self.company.ask_manager(text)
            elif self.direct:
                aid = self.direct
                self.eq.put({"type": "routing", "agents": [aid], "message": ""})
                self.eq.put({"type": "agent_start", "agent_id": aid, "task": text})
                resp = self.company.direct_chat(aid, text, callback=on_status)
                self.eq.put({"type": "agent_done", "agent_id": aid})
            else:
                resp = self.company.chat(
                    text, callback=on_status, on_event=on_event,
                    is_cancelled=is_cancelled
                )

            if not self.cancel:
                self.eq.put({"type": "response", "text": resp})
            self.company.save()
        except Exception as e:
            if not self.cancel:
                self.eq.put({"type": "error", "text": str(e)})
        finally:
            self.eq.put({"type": "done"})

    def _drain_queue(self):
        """이벤트 큐 처리 (메인 스레드)"""
        while not self.eq.empty():
            try:
                e = self.eq.get_nowait()
            except queue.Empty:
                break
            t = e.get("type")

            if t == "routing":
                agents = e.get("agents", [])
                msg = e.get("message", "")
                if msg:
                    self.log.append(("mgr", f"하늘: {self._clean_emoji(msg)}"))
                # 이동 목적지 결정 (비율 좌표)
                seats = MEETING_SEATS_REL if len(agents) > 1 else PROJECT_SEATS_REL
                for i, aid in enumerate(agents):
                    if aid in self.agents:
                        srx, sry = seats[i % len(seats)]
                        self.agents[aid]["target_rx"] = srx
                        self.agents[aid]["target_ry"] = sry
                        self.agents[aid]["status"] = "moving"
                        self.agents[aid]["bubble"] = "이동 중..."
                        self.agents[aid]["bubble_tick"] = pygame.time.get_ticks()

            elif t == "agent_start":
                aid = e.get("agent_id")
                task = e.get("task", "")
                if aid and aid in self.agents:
                    self.agents[aid]["status"] = "working"
                    # 업무 내용을 말풍선에 표시 (짧게 자름)
                    short_task = task[:30] + "..." if len(task) > 30 else task
                    self.agents[aid]["bubble"] = short_task
                    self.agents[aid]["bubble_tick"] = pygame.time.get_ticks()

            elif t == "agent_done":
                aid = e.get("agent_id")
                if aid and aid in self.agents:
                    self.agents[aid]["target_rx"] = self.agents[aid]["home_rx"]
                    self.agents[aid]["target_ry"] = self.agents[aid]["home_ry"]
                    self.agents[aid]["status"] = "returning"
                    self.agents[aid]["bubble"] = "완료!"
                    self.agents[aid]["bubble_tick"] = pygame.time.get_ticks()

            elif t == "status":
                msg = e.get("message", "")
                self.log.append(("sys", msg))
                # 검색 중 메시지를 해당 직원 말풍선에 표시
                if "검색 중" in msg:
                    # 현재 working 상태인 직원에게 표시
                    for aid, ag in self.agents.items():
                        if ag["status"] == "working":
                            short = msg.replace("  🔍 ", "").replace("검색 중: ", "")
                            self.agents[aid]["bubble"] = "검색: " + short[:20]
                            self.agents[aid]["bubble_tick"] = pygame.time.get_ticks()

            elif t == "response":
                self._scroll = 0  # 응답 도착 → 맨 아래로
                txt = e.get("text", "")
                if txt:
                    # 자동 메모장 열기 (전체 내용)
                    self._open_response(txt)
                    # 채팅에는 요약만 표시
                    clean = txt.replace("**", "").replace("##", "").replace("```", "")
                    clean = self._clean_emoji(clean)
                    lines = clean[:10000].split("\n")
                    # 첫 15줄만 채팅에 표시 + 안내
                    shown = 0
                    for line in lines:
                        stripped = line.strip()
                        if not stripped:
                            self.log.append(("agent", ""))
                        else:
                            self.log.append(("agent", stripped[:500]))
                        shown += 1
                        if shown >= 15:
                            break
                    if len(lines) > 15:
                        self.log.append(("sys", f"(전체 응답은 메모장에서 확인하세요 — 총 {len(clean)}자)"))

            elif t == "error":
                self.log.append(("err", f"오류: {e.get('text', '')}"))

            elif t == "done":
                self.busy = False
                for ag in self.agents.values():
                    if ag["status"] not in ("idle",):
                        ag["target_rx"] = ag["home_rx"]
                        ag["target_ry"] = ag["home_ry"]
                        ag["status"] = "returning"
                    ag["bubble"] = ""

    # ── 애니메이션 ────────────────────────

    def _animate(self):
        spd = 0.005  # 비율 기반 이동 속도
        for ag in self.agents.values():
            if ag["target_rx"] is not None:
                dx = ag["target_rx"] - ag["rx"]
                dy = ag["target_ry"] - ag["ry"]
                d = (dx * dx + dy * dy) ** 0.5
                if d < spd:
                    ag["rx"] = ag["target_rx"]
                    ag["ry"] = ag["target_ry"]
                    ag["target_rx"] = None
                    ag["target_ry"] = None
                    if ag["status"] == "returning":
                        ag["status"] = "idle"
                else:
                    ag["rx"] += dx / d * spd
                    ag["ry"] += dy / d * spd

    # ── 그리기 ────────────────────────────

    def _draw(self):
        self.screen.fill(C.BG)
        self._draw_map()
        self._draw_agents()
        self._draw_mode_bar()
        self._draw_chat()
        if self.popup:
            self._draw_popup()
        pygame.display.flip()

    def _draw_map(self):
        pygame.draw.rect(self.screen, C.FLOOR, (0, 0, self.W, self.MAP_H))

        for room in ROOMS_REL:
            rt = room["type"]
            clr = {
                "personal": C.ROOM,
                "meeting": C.MEETING,
                "project": C.PROJECT,
                "ceo": C.CEO,
            }.get(rt, C.ROOM)

            rx = int(room["rx"] * self.W)
            ry = int(room["ry"] * self.MAP_H)
            rw = int(room["rw"] * self.W)
            rh = int(room["rh"] * self.MAP_H)
            rect = pygame.Rect(rx, ry, rw, rh)

            # 활성 표시 (직원이 안에 있으면 밝게)
            if rt in ("meeting", "project"):
                for ag in self.agents.values():
                    ax, ay = scale_pos(ag["rx"], ag["ry"], self.W, self.MAP_H)
                    if rect.collidepoint(ax, ay) and ag["status"] in ("working", "moving"):
                        clr = tuple(min(255, c + 20) for c in clr)
                        break

            pygame.draw.rect(self.screen, clr, rect, border_radius=8)
            pygame.draw.rect(self.screen, C.ROOM_BORDER, rect, 2, border_radius=8)

            # 라벨
            lbl = self.f12.render(room["label"], True, C.DIM)
            self.screen.blit(lbl, (rx + 10, ry + 8))

    def _draw_agents(self):
        for aid, ag in self.agents.items():
            x, y = scale_pos(ag["rx"], ag["ry"], self.W, self.MAP_H)
            clr = COLORS[aid]
            st = ag["status"]

            # 작업 중 후광
            if st == "working":
                # 깜빡이는 효과
                alpha = 40 + int(20 * abs((pygame.time.get_ticks() % 1000) / 500 - 1))
                glow = pygame.Surface((70, 70), pygame.SRCALPHA)
                pygame.draw.circle(glow, (*clr, alpha), (35, 35), 35)
                self.screen.blit(glow, (x - 35, y - 35))

            # 몸통
            pygame.draw.circle(self.screen, clr, (x, y), 22)
            pygame.draw.circle(self.screen, C.WHITE, (x, y), 22, 2)

            # 이름 (원 안)
            ns = self.f12.render(SHORT[aid], True, C.WHITE)
            self.screen.blit(ns, (x - ns.get_width() // 2, y - ns.get_height() // 2))

            # 직무 (원 아래)
            rs = self.f12.render(ROLE[aid], True, clr)
            self.screen.blit(rs, (x - rs.get_width() // 2, y + 25))

            # 상태 표시등
            sc = {"idle": C.GREEN, "moving": C.YELLOW, "working": C.ORANGE,
                  "searching": C.BLUE, "returning": C.YELLOW}.get(st, C.GREEN)
            pygame.draw.circle(self.screen, sc, (x + 16, y - 16), 5)
            pygame.draw.circle(self.screen, C.WHITE, (x + 16, y - 16), 5, 1)

            # 말풍선 (현재 하는 일 표시)
            bubble = ag.get("bubble", "")
            if bubble:
                # 말풍선 배경
                btxt = self.f12.render(bubble, True, C.TEXT)
                bw = btxt.get_width() + 16
                bh = 24
                bx = x - bw // 2
                by = y - 50
                # 화면 밖으로 나가지 않게
                bx = max(5, min(bx, self.W - bw - 5))
                by = max(5, by)
                # 배경 + 테두리
                pygame.draw.rect(self.screen, (50, 55, 68), (bx, by, bw, bh), border_radius=6)
                pygame.draw.rect(self.screen, clr, (bx, by, bw, bh), 1, border_radius=6)
                # 꼬리 (삼각형)
                pygame.draw.polygon(self.screen, (50, 55, 68), [
                    (x - 4, by + bh), (x + 4, by + bh), (x, by + bh + 6)
                ])
                # 텍스트
                self.screen.blit(btxt, (bx + 8, by + 4))

    def _draw_mode_bar(self):
        """직접 대화 모드 표시 바"""
        if self.direct:
            name = SHORT[self.direct]
            clr = COLORS.get(self.direct, C.TEXT)
            bar = pygame.Rect(0, self.MAP_H - 28, self.W, 28)
            pygame.draw.rect(self.screen, (40, 45, 55), bar)
            txt = self.f14.render(f"  {name}에게 직접 대화 중  |  ESC: 기본 모드 복귀", True, clr)
            self.screen.blit(txt, (10, self.MAP_H - 24))
        elif self.busy:
            bar = pygame.Rect(0, self.MAP_H - 28, self.W, 28)
            pygame.draw.rect(self.screen, (40, 45, 55), bar)
            # 처리 중 점 애니메이션
            dots = "." * ((pygame.time.get_ticks() // 500) % 4)
            txt = self.f14.render(f"  처리 중{dots}", True, C.ORANGE)
            self.screen.blit(txt, (10, self.MAP_H - 24))

    def _draw_chat(self):
        cy = self.MAP_H
        ch = self.H - cy
        input_h = self._input_height()

        # 배경
        pygame.draw.rect(self.screen, C.CHAT_BG, (0, cy, self.W, ch))
        pygame.draw.line(self.screen, C.ROOM_BORDER, (0, cy), (self.W, cy), 2)

        # 복사 / 업무노트 버튼 (채팅 영역 우상단)
        copy_btn = pygame.Rect(self.W - 135, cy + 5, 55, 24)
        pygame.draw.rect(self.screen, (55, 60, 72), copy_btn, border_radius=4)
        pygame.draw.rect(self.screen, C.ROOM_BORDER, copy_btn, 1, border_radius=4)
        ct = self.f12.render("대화복사", True, C.DIM)
        self.screen.blit(ct, (copy_btn.centerx - ct.get_width() // 2,
                              copy_btn.centery - ct.get_height() // 2))

        notes_btn = pygame.Rect(self.W - 70, cy + 5, 60, 24)
        pygame.draw.rect(self.screen, (55, 60, 72), notes_btn, border_radius=4)
        pygame.draw.rect(self.screen, C.ROOM_BORDER, notes_btn, 1, border_radius=4)
        nt = self.f12.render("업무노트", True, C.DIM)
        self.screen.blit(nt, (notes_btn.centerx - nt.get_width() // 2,
                              notes_btn.centery - nt.get_height() // 2))

        # 로그 (아래에서 위로)
        log_h = ch - input_h - 17
        y = cy + log_h - 5
        color_map = {
            "ceo": C.CEO_TEXT, "mgr": C.MGR_TEXT, "agent": C.AGENT_TEXT,
            "sys": C.SYS_TEXT, "err": C.ERR_TEXT,
        }
        # 스크롤 오프셋 적용 (위로 올린 만큼 y를 아래로 밀어줌)
        y += self._scroll * 20
        max_scroll = 0
        for mtype, text in reversed(self.log):
            clr = color_map.get(mtype, C.TEXT)
            if not text:
                y -= 8
                max_scroll += 1
                continue
            lines = self._wrap(text, self.W - 30)
            for line in reversed(lines):
                y -= 20
                max_scroll += 1
                if cy + 5 <= y <= cy + log_h:
                    self.screen.blit(self.f14.render(line, True, clr), (15, y))
            if y < cy - 200:  # 충분히 위로 나가면 중단
                break
        # 스크롤 상한 제한
        self._scroll = min(self._scroll, max(0, max_scroll - log_h // 20))

        # 입력창 (멀티라인)
        iy = self.H - input_h - 7
        ir = pygame.Rect(10, iy, self.W - 100, input_h)
        pygame.draw.rect(self.screen, C.INPUT_BG, ir, border_radius=6)
        pygame.draw.rect(self.screen, C.ROOM_BORDER, ir, 1, border_radius=6)

        # 입력 텍스트
        disp = self.input + self.composing
        input_w = ir.w - 20
        if disp:
            wrapped = self._wrap_input(disp, input_w)
            # 최대 5줄만 표시 (아래쪽 우선)
            visible = wrapped[-5:]
            for i, line in enumerate(visible):
                ly = iy + 8 + i * 22
                # 마지막 줄에서 조합 중인 글자 표시
                if i == len(visible) - 1 and self.composing:
                    # 확정 부분 (마지막 줄에서 조합 문자 제거)
                    confirmed_part = line[:-len(self.composing)] if self.composing and line.endswith(self.composing) else line
                    cs = self.f15.render(confirmed_part, True, C.TEXT)
                    self.screen.blit(cs, (20, ly))
                    # 조합 중 (밑줄)
                    comp = self.f15.render(self.composing, True, (255, 255, 150))
                    cx = 20 + cs.get_width()
                    self.screen.blit(comp, (cx, ly))
                    pygame.draw.line(self.screen, (255, 255, 150),
                                    (cx, ly + 20), (cx + comp.get_width(), ly + 20), 1)
                else:
                    self.screen.blit(self.f15.render(line, True, C.TEXT), (20, ly))

            # 커서 깜빡임 (마지막 줄 끝)
            if not self.busy and not self.composing:
                if (pygame.time.get_ticks() // 500) % 2 == 0:
                    last_line = visible[-1]
                    cw = self.f15.size(last_line)[0]
                    cursor_y = iy + 8 + (len(visible) - 1) * 22
                    pygame.draw.line(self.screen, C.TEXT,
                                    (22 + cw, cursor_y), (22 + cw, cursor_y + 20), 1)
        else:
            if self.busy:
                ph = "처리 중..."
            elif self.direct:
                ph = f"{SHORT[self.direct]}에게 메시지 입력... (Enter 전송)"
            else:
                ph = "메시지 입력... (Enter 전송)"
            self.screen.blit(self.f15.render(ph, True, C.DIM), (20, iy + 10))

            # 빈 입력창 커서
            if not self.busy and not self.composing:
                if (pygame.time.get_ticks() // 500) % 2 == 0:
                    pygame.draw.line(self.screen, C.TEXT, (22, iy + 8), (22, iy + 28), 1)

        # 전송/중단 버튼 (입력창 오른쪽, 하단 정렬)
        br = pygame.Rect(self.W - 85, self.H - 45, 70, 38)
        if self.busy:
            bc = (195, 65, 65)
            label = "중단"
        else:
            bc = C.BTN
            label = "전송"
        pygame.draw.rect(self.screen, bc, br, border_radius=6)
        bt = self.f15.render(label, True, C.WHITE)
        self.screen.blit(bt, (br.centerx - bt.get_width() // 2, br.centery - bt.get_height() // 2))

    def _draw_popup(self):
        # 오버레이
        ov = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 160))
        self.screen.blit(ov, (0, 0))

        pw, ph = 480, 380
        px = (self.W - pw) // 2
        py = (self.H - ph) // 2
        aid = self.popup["agent_id"]
        clr = COLORS[aid]

        # 박스
        pygame.draw.rect(self.screen, (45, 50, 62), (px, py, pw, ph), border_radius=12)

        # 헤더 바
        pygame.draw.rect(self.screen, clr, (px, py, pw, 55),
                        border_top_left_radius=12, border_top_right_radius=12)
        self.screen.blit(self.fb20.render(self.popup["name"], True, C.WHITE), (px + 20, py + 14))

        # 모델
        mdl = self.f12.render(f"모델: {self.popup['model'].upper()}", True, (200, 200, 200))
        self.screen.blit(mdl, (px + pw - mdl.get_width() - 20, py + 20))

        # 능력
        y = py + 70
        self.screen.blit(self.f15.render("전문 분야", True, clr), (px + 20, y))
        y += 28
        for skill in self.popup["skills"]:
            self.screen.blit(self.f12.render(f"  • {skill[:55]}", True, C.TEXT), (px + 20, y))
            y += 22

        # "대화하기" 버튼
        br = pygame.Rect(px + pw - 130, py + ph - 50, 110, 35)
        pygame.draw.rect(self.screen, clr, br, border_radius=6)
        bt = self.f15.render("대화하기", True, C.WHITE)
        self.screen.blit(bt, (br.centerx - bt.get_width() // 2, br.centery - bt.get_height() // 2))

        # 닫기 안내
        self.screen.blit(self.f12.render("ESC 또는 바깥 클릭으로 닫기", True, C.DIM),
                         (px + 20, py + ph - 40))

        # 테두리
        pygame.draw.rect(self.screen, clr, (px, py, pw, ph), 2, border_radius=12)

    def _wrap(self, text, max_w):
        """텍스트 줄바꿈"""
        lines = []
        for para in text.split("\n"):
            if not para.strip():
                lines.append("")
                continue
            cur = ""
            for ch in para:
                if self.f14.size(cur + ch)[0] > max_w:
                    if cur:
                        lines.append(cur)
                    cur = ch
                else:
                    cur += ch
            if cur:
                lines.append(cur)
        return lines if lines else [""]


# ── API 키 입력 화면 ─────────────────────────────

def ask_api_key() -> str:
    """API 키가 없을 때 GUI에서 입력받기"""
    pygame.init()
    screen = pygame.display.set_mode((600, 280))
    pygame.display.set_caption("꼭지네 — API 키 설정")
    fp = "C:/Windows/Fonts/malgun.ttf"
    fb = "C:/Windows/Fonts/malgunbd.ttf"
    font = pygame.font.Font(fp, 15)
    font_sm = pygame.font.Font(fp, 12)
    font_title = pygame.font.Font(fb, 18)

    key_text = ""
    composing = ""
    clock = pygame.time.Clock()
    pygame.key.start_text_input()

    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                return ""
            elif ev.type == pygame.TEXTINPUT:
                key_text += ev.text
                composing = ""
            elif ev.type == pygame.TEXTEDITING:
                composing = ev.text
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_BACKSPACE:
                    if composing:
                        composing = ""
                    elif key_text:
                        key_text = key_text[:-1]
                elif ev.key == pygame.K_RETURN:
                    k = key_text.strip()
                    if k.startswith("sk-ant"):
                        save_api_key(k)
                        config.API_KEY = k
                        pygame.quit()
                        return k
                elif ev.key == pygame.K_ESCAPE:
                    pygame.quit()
                    return ""
                # Ctrl+V 붙여넣기
                elif ev.key == pygame.K_v and (ev.mod & pygame.KMOD_CTRL):
                    try:
                        import ctypes
                        ctypes.windll.user32.OpenClipboard(0)
                        handle = ctypes.windll.user32.GetClipboardData(13)  # CF_UNICODETEXT
                        if handle:
                            pasted = ctypes.c_wchar_p(handle).value
                            key_text += pasted
                        ctypes.windll.user32.CloseClipboard()
                    except Exception:
                        pass
            elif ev.type == pygame.MOUSEBUTTONDOWN:
                # 확인 버튼 클릭
                btn = pygame.Rect(430, 210, 100, 38)
                if btn.collidepoint(ev.pos):
                    k = key_text.strip()
                    if k.startswith("sk-ant"):
                        save_api_key(k)
                        config.API_KEY = k
                        pygame.quit()
                        return k

        # 그리기
        screen.fill((35, 39, 46))

        # 제목
        screen.blit(font_title.render("꼭지네 — API 키 설정", True, (210, 215, 225)), (30, 25))

        # 안내
        screen.blit(font_sm.render("Anthropic API 키를 입력해주세요. (최초 1번만 입력하면 저장됩니다)", True, (150, 155, 165)), (30, 65))
        screen.blit(font_sm.render("console.anthropic.com 에서 발급받을 수 있어요.", True, (120, 125, 135)), (30, 88))

        # 입력창
        ir = pygame.Rect(30, 120, 540, 42)
        pygame.draw.rect(screen, (45, 50, 60), ir, border_radius=6)
        pygame.draw.rect(screen, (90, 98, 115), ir, 1, border_radius=6)

        disp = key_text + composing
        if disp:
            # 마스킹 (앞 8글자만 보여주고 나머지 *)
            if len(disp) > 8:
                masked = disp[:8] + "*" * (len(disp) - 8)
            else:
                masked = disp
            # 너무 길면 뒤쪽만
            ts = font.render(masked, True, (210, 215, 225))
            mw = ir.w - 20
            if ts.get_width() > mw:
                visible = masked[-(mw // 10):]
                ts = font.render(visible, True, (210, 215, 225))
            screen.blit(ts, (40, 132))
        else:
            screen.blit(font.render("sk-ant-... (붙여넣기: Ctrl+V)", True, (100, 105, 115)), (40, 132))

        # 상태 메시지
        k = key_text.strip()
        if k and not k.startswith("sk-ant"):
            screen.blit(font_sm.render("sk-ant 로 시작하는 키를 입력해주세요.", True, (255, 95, 95)), (30, 172))
        elif k:
            screen.blit(font_sm.render("Enter 또는 확인 버튼을 누르면 저장됩니다.", True, (80, 190, 80)), (30, 172))

        # 확인 버튼
        btn = pygame.Rect(430, 210, 100, 38)
        bc = (65, 115, 195) if k.startswith("sk-ant") else (55, 58, 68)
        pygame.draw.rect(screen, bc, btn, border_radius=6)
        screen.blit(font.render("확인", True, (255, 255, 255)),
                    (btn.centerx - font.size("확인")[0] // 2, btn.centery - font.size("확인")[1] // 2))

        # ESC 안내
        screen.blit(font_sm.render("ESC: 취소", True, (100, 105, 115)), (30, 220))

        pygame.display.flip()
        clock.tick(60)


# ── 진입점 ────────────────────────────────────────

def main():
    if not API_KEY:
        key = ask_api_key()
        if not key:
            return

    app = OfficeGUI()
    app.run()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        input("\n오류가 발생했습니다. Enter를 누르면 종료됩니다...")
