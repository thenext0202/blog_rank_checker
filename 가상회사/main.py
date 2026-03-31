"""
🏢 꼭지네 마케팅 인하우스 AI 팀
CEO: 이꼭지 (사용자) / 팀장: 하늘 (AI 관리자)
터미널에서 실행: python main.py
"""
import sys
import io

# Windows 터미널 한글/이모지 깨짐 방지
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')

from company import VirtualCompany
from config import AGENTS, API_KEY

# 색상 코드 (터미널 출력용)
class C:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    END = "\033[0m"


def print_banner():
    print(f"""
{C.BOLD}{C.CYAN}╔══════════════════════════════════════════════════╗
║           🏢 꼭지네 마케팅 인하우스             ║
║               Core 7 AI Team                    ║
╠══════════════════════════════════════════════════╣
║  👑 이꼭지 (CEO)        — 그건 바로 나!         ║
║  📋 하늘 (팀장)         — 업무 배정/품질 관리   ║
║  🔍 사루비아 (SEO 전략가)   — 키워드/검색 최적화   ║
║  ✍️  지수 (콘텐츠 마케터) — 블로그/카피 작성     ║
║  📊 릴리 (퍼포먼스 마케터) — 광고/퍼널 최적화   ║
║  🔬 피치 (리서치)       — 규제/트렌드/레퍼런스  ║
║  🤝 체리 (SNS/CRM)   — 채널 운영/고객 소통   ║
║  ⚙️  데이지 (개발자)     — 자동화/도구 제작      ║
╠══════════════════════════════════════════════════╣
║  /팀  /하늘  /사루비아  /지수  /릴리                ║
║  /피치  /체리  /데이지  /메모  /리셋  /종료   ║
╚══════════════════════════════════════════════════╝{C.END}
""")


# 이름 → agent_id 매핑
NAME_MAP = {
    "하늘": "manager",
    "사루비아": "seo_strategist",
    "지수": "content_director",
    "릴리": "traffic_manager",
    "피치": "research_support",
    "체리": "sns_crm",
    "데이지": "automation_dev",
}


def main():
    # API 키 확인
    if not API_KEY:
        print(f"{C.RED}⚠️  ANTHROPIC_API_KEY 환경변수를 설정해주세요.{C.END}")
        print(f"   설정 방법: set ANTHROPIC_API_KEY=sk-ant-...")
        return

    company = VirtualCompany()
    print_banner()

    # 이전 대화 이력이 있으면 안내
    total_msgs = sum(len(h) for h in company.histories.values())
    total_notes = len(company.notes)
    if total_msgs > 0 or total_notes > 0:
        print(f"{C.GREEN}💾 이전 기록 로드 완료 — 대화 {total_msgs}건, 업무노트 {total_notes}건{C.END}")
        print(f"{C.CYAN}   (초기화하려면 /리셋){C.END}\n")

    direct_mode = None  # 직접 대화 모드 (None이면 하늘 라우팅)

    while True:
        # 프롬프트 표시
        if direct_mode:
            if direct_mode == "manager":
                prompt_text = "📋 하늘 팀장"
            else:
                agent = AGENTS[direct_mode]
                prompt_text = f"{agent['emoji']} {agent['name']}"
        else:
            prompt_text = "👑 이꼭지 CEO"

        try:
            user_input = input(f"\n{C.BOLD}{C.GREEN}{prompt_text} > {C.END}").strip()
        except (KeyboardInterrupt, EOFError):
            company.save()
            print(f"\n{C.GREEN}💾 대화 이력 저장 완료{C.END}")
            print(f"{C.CYAN}👋 수고하셨습니다, 이꼭지 CEO님!{C.END}")
            break

        if not user_input:
            continue

        # 명령어 처리
        if user_input == "/종료":
            company.save()
            print(f"{C.GREEN}💾 대화 이력 저장 완료{C.END}")
            print(f"{C.CYAN}👋 수고하셨습니다, 이꼭지 CEO님!{C.END}")
            break

        elif user_input == "/팀":
            print(f"\n{C.BOLD}📋 직원 현황:{C.END}")
            print(f"  👑 이꼭지 (CEO) — 나!")
            for aid, agent in AGENTS.items():
                print(f"  {agent['emoji']} {agent['name']}")
            direct_mode = None
            print(f"\n{C.CYAN}기본 모드로 복귀 (하늘 팀장이 업무 배정){C.END}")
            continue

        elif user_input == "/메모":
            notes = company.get_notes(last_n=10)
            if not notes:
                print(f"{C.YELLOW}📝 아직 업무 노트가 없습니다.{C.END}")
            else:
                print(f"\n{C.BOLD}📝 최근 업무 노트 (최대 10건):{C.END}")
                for n in notes:
                    print(f"  {C.CYAN}{n['date']}{C.END} {n['agent']}")
                    print(f"    📌 {n['task'][:80]}")
                    print(f"    → {n['result_summary'][:100]}...")
                    print()
            continue

        elif user_input == "/리셋":
            company.reset_history()
            print(f"{C.YELLOW}🔄 대화 이력 초기화 완료 (업무 노트는 유지됨){C.END}")
            continue

        elif user_input.startswith("/"):
            name = user_input[1:]
            if name in NAME_MAP:
                direct_mode = NAME_MAP[name]
                if direct_mode == "manager":
                    print(f"{C.CYAN}💬 하늘 팀장에게 직접 질문 모드 (/팀 으로 복귀){C.END}")
                else:
                    agent = AGENTS[direct_mode]
                    print(f"{C.CYAN}💬 {agent['name']}에게 직접 대화 모드 (/팀 으로 복귀){C.END}")
                continue
            else:
                print(f"{C.YELLOW}알 수 없는 명령어입니다. /팀, /하늘, /사루비아, /지수, /릴리, /피치, /체리, /데이지, /메모, /리셋, /종료{C.END}")
                continue

        # 메시지 처리
        print(f"\n{C.CYAN}⏳ 처리 중...{C.END}")

        # 검색 중 실시간 표시 콜백
        def on_status(msg):
            print(f"{C.YELLOW}{msg}{C.END}")

        try:
            if direct_mode == "manager":
                # 하늘에게 직접 질문 (현황 보고, 업무 확인 등)
                response = company.ask_manager(user_input)
            elif direct_mode:
                response = company.direct_chat(direct_mode, user_input, callback=on_status)
            else:
                response = company.chat(user_input, callback=on_status)

            print(f"\n{response}")

            # 대화 후 자동 저장
            company.save()

        except Exception as e:
            print(f"{C.RED}❌ 오류 발생: {e}{C.END}")


if __name__ == "__main__":
    main()
