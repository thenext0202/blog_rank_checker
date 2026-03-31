"""
가상회사 핵심 엔진
- CEO(이꼭지) → 팀장(하늘) 라우팅 → 담당 직원 호출 → 결과 취합
- 하늘은 모든 직원의 작업 결과를 기억함
- 직원들은 웹 검색 도구 사용 가능
- 대화 이력 & 업무 노트 자동 저장/로드
- 직원 이력 자동 기록 (옵시디언) + 프롬프트 주입 (학습)
"""
import json
import os
import re
from datetime import datetime
import anthropic
from config import API_KEY, MODELS, AGENTS
from tools import TOOL_DEFINITIONS, TOOL_FUNCTIONS

# 데이터 저장 폴더
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
HISTORIES_FILE = os.path.join(DATA_DIR, "histories.json")
NOTES_FILE = os.path.join(DATA_DIR, "notes.json")

# 직원 이력 저장 폴더 (옵시디언)
HISTORY_MD_DIR = os.path.join(
    os.path.expanduser("~"),
    "Desktop", "옵시디언", "효진의 창고", "05.Automation_DB", "가상회사", "직원 이력"
)

# 직원 ID → 이력 파일명
HISTORY_FILES = {
    "manager": "하늘_팀장.md",
    "seo_strategist": "사루비아_SEO.md",
    "content_director": "지수_콘텐츠.md",
    "traffic_manager": "릴리_퍼포먼스.md",
    "research_support": "피치_리서치.md",
    "sns_crm": "체리_SNS.md",
    "automation_dev": "데이지_개발.md",
}

# 프롬프트 주입 시 최근 몇 건 참고할지
HISTORY_INJECT_COUNT = 10

# 공유 지식 폴더 (모든 직원이 참고하는 파일들)
KNOWLEDGE_DIR = os.path.join(
    os.path.expanduser("~"),
    "Desktop", "옵시디언", "효진의 창고", "02.Reference", "01.메디셜 제품 가이드"
)


class VirtualCompany:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=API_KEY)
        # 검색 도구를 사용할 수 있는 직원 (팀장은 라우팅만)
        self.tool_enabled = {"seo_strategist", "content_director", "traffic_manager", "research_support", "sns_crm", "automation_dev"}
        # 데이터 폴더 생성
        os.makedirs(DATA_DIR, exist_ok=True)
        # 저장된 이력 로드 (없으면 빈 이력)
        self.histories = self._load_histories()
        # 업무 노트 로드
        self.notes = self._load_notes()
        # 공유 지식 로드 (제품 가이드 등)
        self._knowledge = self._load_knowledge()

    # ── 저장/로드 ──────────────────────────────────────

    def _load_histories(self) -> dict:
        """저장된 대화 이력 로드"""
        if os.path.exists(HISTORIES_FILE):
            try:
                with open(HISTORIES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 새로 추가된 에이전트가 있으면 빈 이력 보충
                for aid in AGENTS:
                    if aid not in data:
                        data[aid] = []
                return data
            except (json.JSONDecodeError, IOError):
                pass
        return {agent_id: [] for agent_id in AGENTS}

    def _save_histories(self):
        """대화 이력 파일로 저장"""
        # 각 직원당 최근 20개만 저장 (파일 비대화 방지)
        trimmed = {}
        for aid, hist in self.histories.items():
            trimmed[aid] = hist[-20:]
        with open(HISTORIES_FILE, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)

    def _load_notes(self) -> list:
        """업무 노트 로드"""
        if os.path.exists(NOTES_FILE):
            try:
                with open(NOTES_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return []

    def _load_knowledge(self) -> dict:
        """공유 지식 폴더에서 모든 .md 파일을 읽어서 딕셔너리로 저장
        _공통.md는 별도 키("_common")로 저장, 나머지는 제품명을 키로"""
        guides = {}
        if not os.path.exists(KNOWLEDGE_DIR):
            return guides
        for fname in sorted(os.listdir(KNOWLEDGE_DIR)):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(KNOWLEDGE_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                if fname.startswith("_"):
                    # 공통 파일 → 항상 주입
                    guides["_common"] = content
                else:
                    # 제품 가이드 → 제품명 언급 시만 주입
                    key = fname.replace(" 가이드.md", "").replace(".md", "")
                    guides[key] = content
            except IOError:
                continue
        return guides

    def _get_relevant_knowledge(self, message: str) -> str:
        """공통 가이드(항상) + 메시지에서 언급된 제품 가이드를 합쳐서 반환"""
        if not self._knowledge:
            return ""

        parts = []

        # 1. 공통 가이드 (항상 주입)
        if "_common" in self._knowledge:
            parts.append(self._knowledge["_common"])

        # 2. 메시지에서 언급된 제품 가이드만 추가
        matched_products = []
        msg_lower = message.lower()
        for product_name, content in self._knowledge.items():
            if product_name == "_common":
                continue
            if product_name.lower() in msg_lower:
                matched_products.append(f"### {product_name} 제품 상세 가이드\n{content}")

        if matched_products:
            parts.append("## 해당 제품 상세 가이드 (참고 필수)\n\n" + "\n\n".join(matched_products))
        else:
            # 제품명 안 나오면 목록만
            product_list = [name for name in self._knowledge if name != "_common"]
            if product_list:
                listing = "## 자사 제품 목록\n특정 제품명이 언급되면 해당 가이드를 자동으로 참고해.\n"
                for name in product_list:
                    listing += f"→ {name}\n"
                parts.append(listing)

        return "\n\n".join(parts) if parts else ""

    def _save_note(self, agent_id: str, task: str, result: str):
        """업무 노트 저장 (직원이 작업 완료할 때마다)"""
        agent = AGENTS[agent_id]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.notes.append({
            "date": now_str,
            "agent": agent["name"],
            "agent_id": agent_id,
            "task": task[:500],
            "result_summary": result[:2000],
        })
        # 최근 100건만 유지
        self.notes = self.notes[-100:]
        with open(NOTES_FILE, "w", encoding="utf-8") as f:
            json.dump(self.notes, f, ensure_ascii=False, indent=2)

        # 옵시디언 이력 파일에도 기록 (영구 보관, 용량 제한 없음)
        self._append_history_md(agent_id, now_str, task, result)

    def _append_history_md(self, agent_id: str, date_str: str, task: str, result: str):
        """직원 이력을 옵시디언 마크다운 파일에 추가 (영구 기록)"""
        filename = HISTORY_FILES.get(agent_id)
        if not filename:
            return
        filepath = os.path.join(HISTORY_MD_DIR, filename)
        os.makedirs(HISTORY_MD_DIR, exist_ok=True)

        # 파일이 없으면 헤더 생성
        agent = AGENTS[agent_id]
        if not os.path.exists(filepath):
            header = f"# {agent['emoji']} {agent['name']} — 업무 이력\n\n"
            header += f"> 자동 기록 파일 — 작업 완료 시 자동 추가됨\n\n---\n\n"
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(header)

        # 이력 항목 추가
        entry = f"### {date_str}\n"
        entry += f"**업무:** {task[:500]}\n\n"
        entry += f"**결과:**\n{result[:2000]}\n\n---\n\n"
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(entry)

    def _load_history_md(self, agent_id: str) -> str:
        """직원의 최근 이력을 읽어서 프롬프트 주입용 텍스트 반환"""
        filename = HISTORY_FILES.get(agent_id)
        if not filename:
            return ""
        filepath = os.path.join(HISTORY_MD_DIR, filename)
        if not os.path.exists(filepath):
            return ""

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except IOError:
            return ""

        # "### 날짜" 기준으로 항목 분리 → 최근 N건만 추출
        entries = re.split(r'(?=^### \d{4}-\d{2}-\d{2})', content, flags=re.MULTILINE)
        entries = [e.strip() for e in entries if e.strip().startswith("### ")]

        if not entries:
            return ""

        recent = entries[-HISTORY_INJECT_COUNT:]
        header = "## 지금까지 내가 한 업무 이력 (참고용)\n"
        header += "아래 이력을 참고해서 이전에 했던 작업과 일관성을 유지하고, 더 나은 결과를 만들어줘.\n\n"
        return header + "\n".join(recent)

    def get_notes(self, agent_id: str = None, last_n: int = 10) -> list:
        """업무 노트 조회 (전체 또는 특정 직원)"""
        notes = self.notes
        if agent_id:
            notes = [n for n in notes if n["agent_id"] == agent_id]
        return notes[-last_n:]

    def save(self):
        """대화 이력 저장 (외부 호출용)"""
        self._save_histories()

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """도구 실행"""
        func = TOOL_FUNCTIONS.get(tool_name)
        if not func:
            return f"알 수 없는 도구: {tool_name}"
        return func(**tool_input)

    def _call_agent(self, agent_id: str, user_message: str, callback=None) -> str:
        """특정 직원에게 메시지 보내고 응답 받기 (도구 사용 포함)"""
        agent = AGENTS[agent_id]
        model = MODELS[agent["model"]]
        use_tools = agent_id in self.tool_enabled

        # 대화 이력에 추가
        self.histories[agent_id].append({"role": "user", "content": user_message})

        # 이력이 너무 길면 최근 10개만 유지 (비용 절감)
        history = self.histories[agent_id][-10:]

        # 시스템 프롬프트 구성: 기본 프롬프트 + 관련 제품 가이드 + 업무 이력
        system_text = agent["system_prompt"]

        # 제품 가이드 주입 (팀장 제외, 메시지에서 언급된 제품만)
        if agent_id != "manager" and self._knowledge:
            knowledge = self._get_relevant_knowledge(user_message)
            if knowledge:
                system_text += "\n\n" + knowledge

        # 업무 이력 주입 (학습용)
        past_history = self._load_history_md(agent_id)
        if past_history:
            system_text += "\n\n" + past_history

        # API 호출 파라미터
        params = {
            "model": model,
            "max_tokens": 4096,
            "system": [{
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"}
            }],
            "messages": history,
        }
        if use_tools:
            params["tools"] = TOOL_DEFINITIONS

        response = self.client.messages.create(**params)

        # 도구 사용 루프 (최대 5회 — 검색 충분히 가능)
        tool_round = 0
        while response.stop_reason == "tool_use" and tool_round < 5:
            tool_round += 1

            # 응답에서 도구 호출 추출
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    if callback:
                        callback(f"  🔍 검색 중: {block.input.get('query', block.name)}")

                    result = self._execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })

            # 도구 결과를 포함해서 다시 호출
            history.append({"role": "assistant", "content": response.content})
            history.append({"role": "user", "content": tool_results})

            response = self.client.messages.create(**params | {"messages": history})

        # 최종 텍스트 응답 추출
        result = ""
        for block in response.content:
            if hasattr(block, "text"):
                result += block.text

        # 응답을 이력에 저장
        self.histories[agent_id].append({"role": "assistant", "content": result})

        return result

    def _feed_manager(self, agent_id: str, task: str, result: str):
        """하늘(팀장)에게 직원 작업 결과를 보고 — 하늘이 모든 걸 알고 있게"""
        agent = AGENTS[agent_id]
        report = f"[팀원 작업 완료 보고]\n담당: {agent['name']}\n업무: {task}\n결과 요약: {result[:500]}"
        # 하늘의 이력에 직접 추가 (API 호출 없이 — 비용 0원)
        self.histories["manager"].append({"role": "user", "content": report})
        self.histories["manager"].append({"role": "assistant", "content": "확인했습니다."})
        # 업무 노트에도 영구 저장
        self._save_note(agent_id, task, result)

    def _route(self, user_message: str) -> dict:
        """팀장 하늘이 메시지를 분석하여 라우팅 결정"""
        raw = self._call_agent("manager", user_message)

        # JSON 파싱 (하늘 응답에서 JSON 추출)
        try:
            if "```" in raw:
                json_str = raw.split("```")[1]
                if json_str.startswith("json"):
                    json_str = json_str[4:]
                return json.loads(json_str.strip())
            return json.loads(raw.strip())
        except (json.JSONDecodeError, IndexError):
            return {"routing": [], "message": raw}

    def chat(self, user_message: str, callback=None, on_event=None,
             is_cancelled=None) -> str:
        """CEO(이꼭지) 메시지 처리 — 하늘 라우팅 → 직원 실행 → 결과 취합
        on_event: GUI용 콜백 — {"type": "routing|agent_start|agent_done", ...}
        is_cancelled: 중단 여부 확인 함수 (GUI에서 전달)
        """
        # 1단계: 팀장 하늘이 라우팅 결정
        route = self._route(user_message)
        outputs = []

        # 하늘 보고 메시지
        manager = AGENTS["manager"]
        if route.get("message"):
            outputs.append(f"{manager['emoji']} **{manager['name']}**: {route['message']}")

        # GUI에 라우팅 결과 전달
        if on_event:
            agent_ids = [t["agent"] for t in route.get("routing", [])
                        if t["agent"] in AGENTS and t["agent"] != "manager"]
            on_event({"type": "routing", "agents": agent_ids,
                      "message": route.get("message", "")})

        # 2단계: 배정된 직원들이 순서대로 작업
        prev_result = ""
        for task_info in route.get("routing", []):
            # 중단 체크 — 다음 직원 호출 전에 확인
            if is_cancelled and is_cancelled():
                outputs.append("\n(중단됨)")
                break

            agent_id = task_info["agent"]
            task = task_info["task"]

            if agent_id not in AGENTS or agent_id == "manager":
                continue

            agent = AGENTS[agent_id]

            # GUI에 작업 시작 알림
            if on_event:
                on_event({"type": "agent_start", "agent_id": agent_id, "task": task})

            # 이전 직원의 결과가 있으면 맥락으로 전달
            if prev_result:
                full_task = f"[이전 팀원 작업 결과]\n{prev_result}\n\n[당신의 업무]\n{task}"
            else:
                full_task = f"[CEO(이꼭지) 원본 요청]\n{user_message}\n\n[팀장 하늘 지시]\n{task}"

            result = self._call_agent(agent_id, full_task, callback=callback)
            prev_result = result

            # 하늘에게 결과 보고 (API 호출 없이 이력에만 저장)
            self._feed_manager(agent_id, task, result)

            # GUI에 작업 완료 알림
            if on_event:
                on_event({"type": "agent_done", "agent_id": agent_id})

            outputs.append(f"\n{agent['emoji']} **{agent['name']}**:\n{result}")

        return "\n".join(outputs) if outputs else "처리할 수 없는 요청입니다."

    def direct_chat(self, agent_id: str, message: str, callback=None) -> str:
        """특정 직원에게 직접 대화 (하늘 거치지 않음)"""
        if agent_id not in AGENTS or agent_id == "manager":
            return "존재하지 않는 직원입니다."

        agent = AGENTS[agent_id]
        result = self._call_agent(agent_id, message, callback=callback)

        # 직접 대화 결과도 하늘에게 보고
        self._feed_manager(agent_id, message[:100], result)

        return f"{agent['emoji']} **{agent['name']}**:\n{result}"

    def ask_manager(self, message: str) -> str:
        """하늘에게 직접 질문 (현황 파악, 보고 요청 등)"""
        result = self._call_agent("manager", message)
        manager = AGENTS["manager"]
        return f"{manager['emoji']} **{manager['name']}**:\n{result}"

    def reset_history(self, agent_id: str = None):
        """대화 이력 초기화 (비용 절감) — 업무 노트는 유지"""
        if agent_id:
            self.histories[agent_id] = []
        else:
            self.histories = {aid: [] for aid in AGENTS}
        self._save_histories()
