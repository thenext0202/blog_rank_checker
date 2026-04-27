"""
효하 가계부 v1.0
- 엑셀/CSV 파일 업로드 → 수입/지출 자동 정리
- 대분류/소분류 드릴다운
- 막대그래프 + 원그래프 시각화
- 정산/피드백/개선점/지난달 반영 메모
- DB 파일 바로 열기
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime

# 드래그 정렬 — 없으면 fallback 처리
try:
    from streamlit_sortables import sort_items as _sort_items
    _HAS_SORTABLE = True
except ImportError:
    _HAS_SORTABLE = False

# ─── 설정 ───
st.set_page_config(
    page_title="효하 가계부",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 메모 저장 경로
MEMO_DIR = Path(__file__).parent / "data"
MEMO_DIR.mkdir(exist_ok=True)
MEMO_FILE = MEMO_DIR / "memos.json"
SAVED_DATA_DIR = MEMO_DIR / "saved_files"
SAVED_DATA_DIR.mkdir(exist_ok=True)

# ─── 스타일 ───
st.markdown("""
<style>
    /* 메인 헤더 */
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        text-align: center;
        padding: 0.5rem 0 1rem 0;
    }
    /* 요약 카드 */
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 16px;
        padding: 1.2rem;
        color: white;
        text-align: center;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    .metric-card.income {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
    }
    .metric-card.expense {
        background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%);
    }
    .metric-card.balance {
        background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
    }
    .metric-card.saving {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
    }
    .metric-card.unpaid {
        background: linear-gradient(135deg, #f7971e 0%, #ffd200 100%);
    }
    .metric-label { font-size: 1rem; opacity: 0.9; }
    .metric-value { font-size: 2rem; font-weight: 700; margin-top: 0.3rem; }
    /* 구분선 */
    .divider { border-top: 2px solid #e0e0e0; margin: 2rem 0; }
    /* 섹션 간 여백 */
    .section-gap { margin-top: 1.5rem; }
    .section-gap-lg { margin-top: 2.5rem; }
    /* 요약 카드 하단 여백 */
    .metric-card { margin-bottom: 0.5rem; }
    /* 탭 내부 상단 여백 */
    .stTabs [data-baseweb="tab-panel"] { padding-top: 1rem; }
    /* expander 사이 여백 */
    .streamlit-expanderHeader { margin-top: 0.3rem; }
    /* expander 내부 테이블 — 글자 크기 키움 (30년 로드맵 표와 동일 1.2rem) */
    .dataframe { font-size: 1.2rem !important; }
    [data-testid="stDataFrame"] { font-size: 1.2rem !important; }
    [data-testid="stDataFrame"] div[role="gridcell"],
    [data-testid="stDataFrame"] div[role="columnheader"] {
        font-size: 1.2rem !important;
    }
    [data-testid="stDataFrame"] [role="gridcell"] { padding: 8px 12px !important; }
    /* 메모 입력란 — 글자 크기 키움 */
    .stTextArea textarea {
        font-size: 1.25rem !important;
        line-height: 1.65 !important;
    }
    /* 메모 라벨도 살짝 키움 */
    .stTextArea label p { font-size: 1.1rem !important; font-weight: 600; }
</style>
""", unsafe_allow_html=True)


# ─── 유틸 함수 ───
def format_won(amount):
    """금액을 한국 원화 형식으로"""
    if amount >= 0:
        return f"+{amount:,.0f}원"
    return f"{amount:,.0f}원"


def format_won_abs(amount):
    """금액을 절대값 원화 형식으로"""
    return f"{abs(amount):,.0f}원"


def format_input_won(value):
    """입력창 표시용: 정수 → '1,000,000' (단위 없이 쉼표만)"""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def parse_won(text):
    """입력창 파싱: '1,000,000원' / '1000000' / ' 1,000,000 ' → int. 실패 시 None"""
    if text is None:
        return None
    s = str(text).strip()
    if s == "":
        return 0
    # 쉼표·공백·'원' 제거 후 숫자만 남기기
    s = s.replace(",", "").replace(" ", "").replace("원", "")
    # 음수 허용 (이벤트 금액 등)
    if not re.fullmatch(r"-?\d+", s):
        return None
    return int(s)


def load_memo(month_key):
    """월별 메모 로드"""
    if MEMO_FILE.exists():
        with open(MEMO_FILE, "r", encoding="utf-8") as f:
            memos = json.load(f)
        m = memos.get(month_key, {})
    else:
        m = {}
    # 누락 키 보정 — 구버전 호환
    m.setdefault("정산", "")
    m.setdefault("피드백", "")
    m.setdefault("개선점", "")
    m.setdefault("지난 달 반영 내역", "")
    if not isinstance(m.get("목표 회고"), dict):
        m["목표 회고"] = {}
    return m


def save_memo(month_key, memo_data):
    """월별 메모 저장"""
    memos = {}
    if MEMO_FILE.exists():
        with open(MEMO_FILE, "r", encoding="utf-8") as f:
            memos = json.load(f)
    memos[month_key] = memo_data
    with open(MEMO_FILE, "w", encoding="utf-8") as f:
        json.dump(memos, f, ensure_ascii=False, indent=2)


# 로드맵 설정 파일
BUDGET_GOALS_FILE = MEMO_DIR / "budget_goals.json"
ROADMAP_FILE = MEMO_DIR / "roadmap_config.json"
PAYMENT_STATUS_FILE = MEMO_DIR / "payment_status.json"
ASSETS_DETAIL_FILE = MEMO_DIR / "assets_detail.json"


# 이모지 제거 패턴 (유니코드 이모지 + 특수문자)
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # 이모티콘
    "\U0001F300-\U0001F5FF"  # 기호/픽토그램
    "\U0001F680-\U0001F6FF"  # 교통/지도
    "\U0001F1E0-\U0001F1FF"  # 국기
    "\U00002702-\U000027B0"  # 딩뱃
    "\U000024C2-\U00002BFF"  # 기호 (한글 이전 범위)
    "\U0001F000-\U0001F251"  # 마작/도미노/기타 기호
    "\U0001F900-\U0001F9FF"  # 보충 이모지
    "\U0001FA00-\U0001FA6F"  # 체스
    "\U0001FA70-\U0001FAFF"  # 기타 보충
    "\U00002600-\U000026FF"  # 기타 기호
    "\U0000FE00-\U0000FE0F"  # 변형 선택자
    "\U0000200D"             # ZWJ
    "\U00002B50"             # 별
    "]+", flags=re.UNICODE
)


def strip_emoji(text):
    """이모지/특수문자 제거 후 텍스트만 반환"""
    return _EMOJI_PATTERN.sub("", str(text)).strip()


def normalize_categories(df, col="대분류"):
    """같은 텍스트명의 대분류를 하나로 병합 (첫 번째 등장한 이모지+이름을 대표값으로)"""
    # 텍스트만 추출한 키 생성
    stripped = df[col].apply(strip_emoji)
    # 텍스트별 첫 번째 등장 원본을 대표값으로
    repr_map = {}
    for original, text_only in zip(df[col], stripped):
        if text_only not in repr_map:
            repr_map[text_only] = original
    # 모든 행을 대표값으로 통일
    df[col] = stripped.map(repr_map)
    return df


def load_payment_status():
    """미결제→결제 토글 상태 로드"""
    if PAYMENT_STATUS_FILE.exists():
        with open(PAYMENT_STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"paid_items": []}


def save_payment_status(status):
    """미결제→결제 토글 상태 저장"""
    with open(PAYMENT_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def load_budget_goals():
    """카테고리별 예산 목표 로드"""
    if BUDGET_GOALS_FILE.exists():
        with open(BUDGET_GOALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_budget_goals(goals):
    """카테고리별 예산 목표 저장"""
    with open(BUDGET_GOALS_FILE, "w", encoding="utf-8") as f:
        json.dump(goals, f, ensure_ascii=False, indent=2)


def load_roadmap_config():
    """로드맵 설정 전체 로드 (구버전 자동 마이그레이션)"""
    if ROADMAP_FILE.exists():
        with open(ROADMAP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        events = data.get("events", [])
        rate_changes = data.get("rate_changes", [])
        settings = data.get("settings", {})
        # 구버전 호환: year → year_start/year_end 마이그레이션
        migrated = False
        for rc in rate_changes:
            if "year" in rc and "year_start" not in rc:
                rc["year_start"] = rc.pop("year")
                rc["year_end"] = rc["year_start"] + 10
                migrated = True
        if migrated:
            save_roadmap_config(events, rate_changes, settings)
        return events, rate_changes, settings
    return [], [], {}


def save_roadmap_config(events, rate_changes, settings=None):
    """로드맵 설정 전체 저장"""
    data = {"events": events, "rate_changes": rate_changes}
    if settings:
        data["settings"] = settings
    elif ROADMAP_FILE.exists():
        with open(ROADMAP_FILE, "r", encoding="utf-8") as f:
            old = json.load(f)
        data["settings"] = old.get("settings", {})
    with open(ROADMAP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_assets_detail():
    """재산 내역 전체 로드 — {'monthly': {'YYYY-MM': [{'category','subcategory','amount'}, ...]}}"""
    if ASSETS_DETAIL_FILE.exists():
        with open(ASSETS_DETAIL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 누락 키 보정
        if "monthly" not in data:
            data["monthly"] = {}
        return data
    return {"monthly": {}}


def save_assets_detail(data):
    """재산 내역 저장"""
    with open(ASSETS_DETAIL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def latest_month_key(detail):
    """가장 최근(사전순 가장 큰) 월 키. 없으면 None"""
    months = list(detail.get("monthly", {}).keys())
    if not months:
        return None
    return sorted(months)[-1]


def latest_nonempty_month_key(detail):
    """데이터가 있는 가장 최근 월 키. 없으면 None — 동기화는 이 값을 사용"""
    monthly = detail.get("monthly", {})
    candidates = [m for m, rows in monthly.items() if rows]
    if not candidates:
        return None
    return sorted(candidates)[-1]


def total_of_month(detail, month_key):
    """해당 월의 모든 행 합계 (amount 합)"""
    rows = detail.get("monthly", {}).get(month_key, [])
    return sum(int(r.get("amount", 0) or 0) for r in rows)


def next_month_key(month_key):
    """'YYYY-MM' → 다음 달 'YYYY-MM'"""
    y, m = map(int, month_key.split("-"))
    m += 1
    if m > 12:
        m = 1
        y += 1
    return f"{y:04d}-{m:02d}"


def sync_start_asset_from_detail():
    """재산 내역의 데이터가 있는 가장 최근 월 합계를 roadmap_config의 start_asset에 반영"""
    detail = load_assets_detail()
    latest = latest_nonempty_month_key(detail)
    if latest is None:
        return None
    total = total_of_month(detail, latest)
    events, rate_changes, settings = load_roadmap_config()
    settings["roadmap_start_asset"] = int(total)
    save_roadmap_config(events, rate_changes, settings)
    return total


def calc_roadmap(birth_year, start_asset, annual_savings, default_rate, events, rate_changes, years=30):
    """복리 자산 로드맵 계산 (년도별 수익률 변경 지원)"""
    current_year = datetime.now().year
    rows = []
    asset = start_asset

    # 수익률 변경을 년도 기준 정렬 (구버전 호환: year → year_start)
    sorted_rates = sorted(rate_changes, key=lambda r: r.get("year_start", r.get("year", 0)))

    for i in range(years):
        year = current_year + i
        age = year - birth_year + 1  # 한국 나이

        # 해당 년도 적용 수익률 결정 (범위 매칭)
        year_rate = default_rate
        for rc in sorted_rates:
            rc_start = rc.get("year_start", rc.get("year", 0))
            rc_end = rc.get("year_end", 9999)
            if rc_start <= year <= rc_end:
                year_rate = rc["rate"]

        # 해당 년도 이벤트 합산
        year_events = [e for e in events if e["year"] == year]
        event_amount = sum(e["amount"] for e in year_events)
        event_desc = ", ".join(e["desc"] for e in year_events) if year_events else ""

        # 합계 = 보유 자산 × (1 + 수익률) + 저축액 + 이벤트
        total = asset * (1 + year_rate / 100) + annual_savings + event_amount

        rows.append({
            "년도": year,
            "나이": age,
            "보유 자산": asset,
            "저축액": annual_savings,
            "수익률": year_rate,
            "이벤트": event_desc,
            "이벤트 금액": event_amount,
            "합계": total,
        })
        asset = total

    return rows


def parse_data(df):
    """데이터 전처리"""
    # 컬럼명 정리 (BOM 제거)
    df.columns = [c.strip().replace("\ufeff", "") for c in df.columns]

    # 필수 컬럼 확인
    required = ["이름", "날짜", "대분류", "소분류", "순수입(부호)"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.error(f"필수 컬럼이 없습니다: {missing}")
        st.info(f"현재 컬럼: {list(df.columns)}")
        return None

    # 순수입 숫자 변환
    df["순수입(부호)"] = pd.to_numeric(df["순수입(부호)"], errors="coerce").fillna(0)

    # 실 사용 컬럼 (없으면 절대값으로 생성)
    if "실 사용" in df.columns:
        df["실 사용"] = pd.to_numeric(df["실 사용"], errors="coerce").fillna(0)
    else:
        df["실 사용"] = df["순수입(부호)"].abs()

    # 월 컬럼 생성/정리
    if "월" in df.columns and df["월"].notna().any():
        df["월"] = df["월"].astype(str).str.strip()
    else:
        # 날짜에서 추출
        df["월"] = df["날짜"].apply(extract_month)

    # 수입/지출 구분
    df["구분"] = df["순수입(부호)"].apply(lambda x: "수입" if x > 0 else "지출")

    # 사용처 컬럼 (없으면 빈 값)
    if "사용처" not in df.columns:
        df["사용처"] = ""

    # 결제 여부 (없으면 빈 값)
    if "결제 여부" not in df.columns:
        df["결제 여부"] = ""

    # 결제 방법 (없으면 빈 값)
    if "결제 방법" not in df.columns:
        df["결제 방법"] = ""

    # 필수 여부 (없으면 빈 값)
    if "필수 여부" not in df.columns:
        df["필수 여부"] = ""

    # 대분류 이모지 병합 (같은 텍스트명 → 첫 번째 이모지+이름으로 통일)
    df = normalize_categories(df, "대분류")

    return df


def extract_month(date_str):
    """날짜 문자열에서 월 추출"""
    try:
        date_str = str(date_str)
        if "년" in date_str and "월" in date_str:
            year = date_str.split("년")[0].strip()
            month = date_str.split("년")[1].split("월")[0].strip()
            return f"{year}-{int(month):02d}"
    except Exception:
        pass
    return "알 수 없음"


def parse_dates_kr(series):
    """한글/표준 날짜 모두 처리 — '2026년 5월 15일', '2026-05-15', '2026/5/15' 등"""
    s = series.astype(str).str.strip()
    # 한글 토큰 정리
    cleaned = (s
               .str.replace(r"\s+", "", regex=True)
               .str.replace("년", "-", regex=False)
               .str.replace("월", "-", regex=False)
               .str.replace("일", "", regex=False)
               .str.rstrip("-"))
    # 빈 문자열·NaN 처리
    cleaned = cleaned.replace({"": None, "nan": None, "NaT": None})
    return pd.to_datetime(cleaned, errors="coerce")


def open_file(file_path):
    """파일/폴더를 기본 프로그램으로 열기 (한글·공백 경로 지원)"""
    p = os.path.normpath(str(file_path))
    if not os.path.exists(p):
        st.error(f"경로가 없습니다: {p}")
        return False
    try:
        if sys.platform == "win32":
            # 1차: explorer로 시도 (한글 경로·공백에 가장 안정적)
            try:
                subprocess.Popen(["explorer", p])
            except Exception:
                # 2차: os.startfile 폴백
                os.startfile(p)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
        st.toast(f"📂 폴더 열기: {p}", icon="✅")
        return True
    except Exception as e:
        st.error(f"파일 열기 실패: {e}")
        return False


# ─── 메인 앱 ───
st.markdown('<div class="main-header">💰 효하 가계부</div>', unsafe_allow_html=True)

# ─── 사이드바: 설정 (위) → 데이터 업로드 (아래) ───
with st.sidebar:
    # 저장된 설정 불러오기
    _, _, _saved = load_roadmap_config()

    # 목표 자산 설정
    st.header("🎯 목표 자산")

    # 쉼표 입력창 헬퍼 — 잘못 입력 시 이전 값 유지
    def _money_input(label, saved_value, default, key, help_text=None, disabled=False):
        text = st.text_input(
            label,
            value=format_input_won(saved_value if saved_value is not None else default),
            key=key,
            help=help_text,
            disabled=disabled,
        )
        parsed = parse_won(text)
        if parsed is None:
            st.error(f"{label}: 숫자만 입력해 주세요 (쉼표 OK)")
            return int(saved_value if saved_value is not None else default)
        if parsed < 0:
            st.error(f"{label}: 0 이상이어야 합니다")
            return int(saved_value if saved_value is not None else default)
        if parsed > 0:
            st.caption(f"= {parsed:,}원")
        return parsed

    # 마이그레이션: 기존 target_asset 값이 있으면 yearly_target으로 이전
    _legacy_target = _saved.get("target_asset")
    _migrated_yearly = _saved.get("yearly_target")
    if _migrated_yearly is None and _legacy_target:
        _migrated_yearly = _legacy_target

    yearly_target = _money_input(
        "이번 년 목표 (보유 자산 기준)",
        _migrated_yearly, 200_000_000,
        key="ti_yearly_target",
        help_text="재산 내역 가장 최근 월 합계와 비교할 연간 목표",
    )

    # ─── 월별 예산 ───
    st.markdown("**📅 월별 예산**")
    _monthly_targets = dict(_saved.get("monthly_targets", {}))

    # 레거시 마이그레이션: 단일 monthly_target → 이번 달 키로 1회 이전
    _legacy_mt = _saved.get("monthly_target")
    if _legacy_mt and not _monthly_targets:
        _now_key = datetime.now().strftime("%Y-%m")
        _monthly_targets[_now_key] = int(_legacy_mt)

    # 사용자 직접 입력 — 연도/월 자유롭게 (몇 년 후에도 수정 없이 사용 가능)
    _today = datetime.now()
    _ti_y_col, _ti_m_col = st.columns(2)
    with _ti_y_col:
        _ti_year = st.number_input(
            "연도",
            min_value=1900, max_value=9999,
            value=int(st.session_state.get("ti_target_year", _today.year)),
            step=1, key="ti_target_year",
        )
    with _ti_m_col:
        _ti_month = st.number_input(
            "월",
            min_value=1, max_value=12,
            value=int(st.session_state.get("ti_target_month_num", _today.month)),
            step=1, key="ti_target_month_num",
        )
    selected_target_month = f"{int(_ti_year):04d}-{int(_ti_month):02d}"

    _cur_amt = _monthly_targets.get(selected_target_month, 0)
    _mt_text = st.text_input(
        f"{selected_target_month} 목표 금액",
        value=format_input_won(_cur_amt),
        key=f"ti_mt_amt_{selected_target_month}",
        help="0원으로 두면 해당 월 목표 미설정",
    )
    _parsed_mt = parse_won(_mt_text)
    if _parsed_mt is None:
        st.error(f"{selected_target_month} 목표: 숫자만 입력해 주세요 (쉼표 OK)")
    elif _parsed_mt < 0:
        st.error(f"{selected_target_month} 목표: 0 이상이어야 합니다")
    else:
        if _parsed_mt > 0:
            st.caption(f"= {_parsed_mt:,}원")
            _monthly_targets[selected_target_month] = int(_parsed_mt)
        elif selected_target_month in _monthly_targets:
            del _monthly_targets[selected_target_month]

    # 설정된 월 목록 — 펼쳐서 한눈에 + 개별 삭제
    if _monthly_targets:
        with st.expander(f"📋 설정된 월 예산 ({len(_monthly_targets)}개)", expanded=False):
            for _mk in sorted(_monthly_targets.keys(), reverse=True):
                _mc1, _mc2 = st.columns([4, 1])
                with _mc1:
                    st.markdown(f"<small><b>{_mk}</b> — {_monthly_targets[_mk]:,}원</small>",
                                unsafe_allow_html=True)
                with _mc2:
                    if st.button("🗑️", key=f"del_mt_{_mk}", help="이 월 예산 삭제"):
                        del _monthly_targets[_mk]
                        _ev2, _rc2, _s2 = load_roadmap_config()
                        _s2["monthly_targets"] = _monthly_targets
                        save_roadmap_config(_ev2, _rc2, _s2)
                        st.rerun()

    # 현재 화면 비교용 — 시트의 최신 월(or 사용자가 보는 월)이 결정. 일단 selectbox 값으로 선설정.
    monthly_target = int(_monthly_targets.get(selected_target_month, 0))

    # 기존 호환을 위한 변수 (하위 코드에서 사용 시 yearly_target로 대체됨)
    target_asset = yearly_target
    current_asset = 0  # 메인에서 balance/latest_total로 동적 계산

    st.markdown("---")

    # 장기 로드맵 설정
    st.header("🗺️ 장기 로드맵")
    birth_year = st.number_input(
        "출생 년도",
        min_value=1950, max_value=2010, value=_saved.get("birth_year", 1992), step=1
    )

    # 재산 내역에 데이터가 있으면 시작 보유 자산은 자동 동기화 (입력창 비활성)
    _detail_for_sync = load_assets_detail()
    _latest_month = latest_nonempty_month_key(_detail_for_sync)
    if _latest_month is not None:
        _auto_start = total_of_month(_detail_for_sync, _latest_month)
        # 저장된 값과 다르면 즉시 동기화 (재산 내역만 수정하고 새로고침했을 때 반영)
        if int(_saved.get("roadmap_start_asset", -1)) != int(_auto_start):
            sync_start_asset_from_detail()
        roadmap_start_asset = int(_auto_start)
        st.text_input(
            "시작 보유 자산 (원) — 자동",
            value=format_input_won(roadmap_start_asset),
            disabled=True,
            help=f"재산 내역 {_latest_month} 합계로 자동 계산됩니다",
            key="ti_start_asset_auto",
        )
        st.caption(f"📌 재산 내역 **{_latest_month}** 합계 기준 — 수정은 아래 '💎 재산 내역'에서")
    else:
        roadmap_start_asset = _money_input(
            "시작 보유 자산 (원)", _saved.get("roadmap_start_asset"), 170_000_000,
            key="ti_start_asset",
            help_text="재산 내역에 데이터를 넣으면 자동 계산됩니다"
        )

    annual_savings = _money_input(
        "연 저축액 (원)", _saved.get("annual_savings"), 20_000_000, key="ti_annual_savings"
    )
    return_rate = st.number_input(
        "예상 연 수익률 (%)",
        min_value=0.0, max_value=50.0, value=float(_saved.get("return_rate", 13.0)), step=0.5
    )
    roadmap_years = st.number_input(
        "시뮬레이션 기간 (년)",
        min_value=5, max_value=50, value=_saved.get("roadmap_years", 30), step=5
    )

    # 설정 변경 감지 → 자동 저장
    _new_settings = {
        "target_asset": yearly_target,  # 하위 호환 — 동일하게 보존
        "current_asset": 0,
        "monthly_target": monthly_target,  # 하위 호환 — 현재 보고 있는 월의 예산
        "monthly_targets": _monthly_targets,  # 월별 예산 사전
        "yearly_target": yearly_target,
        "birth_year": birth_year,
        "roadmap_start_asset": roadmap_start_asset,
        "annual_savings": annual_savings,
        "return_rate": return_rate,
        "roadmap_years": roadmap_years,
        # 사이드바와 무관한 필드 보존 (덮어쓰기 방지)
        "roadmap_memo": _saved.get("roadmap_memo", ""),
    }
    if _new_settings != _saved:
        _ev, _rc, _ = load_roadmap_config()
        save_roadmap_config(_ev, _rc, _new_settings)

    st.markdown("---")

    # ─── 데이터 업로드 ───
    st.header("📂 데이터 업로드")
    uploaded_file = st.file_uploader(
        "가계부 CSV 또는 엑셀 파일",
        type=["csv", "xlsx", "xls"],
        help="노션에서 내보낸 CSV 또는 엑셀 파일을 올려주세요"
    )

    # 업로드한 파일 저장 — 같은 이름 있으면 기존 파일을 _백업_{타임스탬프}로 보존
    if uploaded_file is not None:
        save_path = SAVED_DATA_DIR / uploaded_file.name
        if save_path.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = SAVED_DATA_DIR / f"{save_path.stem}_백업_{ts}{save_path.suffix}"
            save_path.rename(backup_path)
            st.info(f"📦 기존 파일을 '{backup_path.name}'(으)로 백업했어요")
        with open(save_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.success(f"✅ '{uploaded_file.name}' 저장됨")

    # 저장된 파일 목록 — 클릭(expander)해서 펼쳐 보기
    _all_files = (
        sorted(SAVED_DATA_DIR.glob("*.csv"))
        + sorted(SAVED_DATA_DIR.glob("*.xlsx"))
        + sorted(SAVED_DATA_DIR.glob("*.xls"))
    )
    saved_files = [f for f in _all_files if "_백업_" not in f.name]
    backup_files = [f for f in _all_files if "_백업_" in f.name]

    selected_saved = None  # 단일 선택은 더 이상 안 쓰지만 호환 유지
    selected_savedlist = []
    if saved_files:
        with st.expander(f"📁 저장된 파일 ({len(saved_files)}개)", expanded=False):
            st.caption("여러 개 선택하면 합쳐서 보여줘요 (기본: 전체 선택)")
            saved_names = [f.name for f in saved_files]
            selected_savedlist = st.multiselect(
                "파일 선택",
                saved_names,
                default=saved_names,  # 기본값: 모두 선택 → 누적 데이터로 자동 합산
                label_visibility="collapsed",
            )
            if selected_savedlist:
                selected_saved = selected_savedlist[-1]
            # 삭제 버튼 (마지막 선택 파일)
            if selected_savedlist and st.button(f"🗑️ '{selected_savedlist[-1]}' 삭제", use_container_width=True):
                (SAVED_DATA_DIR / selected_savedlist[-1]).unlink()
                st.rerun()
            st.caption(f"💾 저장 위치: `data/saved_files/`")
    else:
        # 저장된 파일이 없어도 업로더가 작동하려면 multiselect 기본값이 비어 있어야 함
        saved_names = []

    if backup_files:
        with st.expander(f"📦 자동 백업 ({len(backup_files)}개)", expanded=False):
            for bf in backup_files:
                bcol1, bcol2 = st.columns([4, 1])
                with bcol1:
                    st.markdown(f"<small>{bf.name}</small>", unsafe_allow_html=True)
                with bcol2:
                    if st.button("🗑️", key=f"del_bk_{bf.name}", help="백업 삭제"):
                        bf.unlink()
                        st.rerun()

    st.markdown("---")

    # DB 파일 열기
    st.header("📁 DB 파일 열기")
    db_path = st.text_input(
        "파일 경로",
        value=str(SAVED_DATA_DIR),
        help="가계부 CSV/엑셀 파일이 저장되는 폴더"
    )
    if st.button("📂 DB 폴더 열기", use_container_width=True):
        open_file(db_path)

# ─── 데이터 로드 (여러 파일 합치기) ───
df = None
# 로드 대상 파일들 — 새 업로드 우선, 없으면 multiselect로 선택된 파일 모두
_load_paths = []
if uploaded_file is not None:
    _load_paths = [SAVED_DATA_DIR / uploaded_file.name]
elif selected_savedlist:
    _load_paths = [SAVED_DATA_DIR / n for n in selected_savedlist]

if _load_paths:
    try:
        _frames = []
        for _p in _load_paths:
            if not _p.exists():
                continue
            if _p.suffix == ".csv":
                _frames.append(pd.read_csv(_p, encoding="utf-8-sig"))
            else:
                _frames.append(pd.read_excel(_p))
        if _frames:
            df = pd.concat(_frames, ignore_index=True)
            df = parse_data(df)
            # 동일 행 중복 제거 (같은 데이터를 여러 파일에 가지고 있을 수 있음)
            if df is not None:
                _key_cols = [c for c in ["날짜", "이름", "대분류", "소분류", "순수입(부호)"] if c in df.columns]
                if _key_cols:
                    df = df.drop_duplicates(subset=_key_cols, keep="first").reset_index(drop=True)
                # 미결제→결제 토글 상태 적용
                ps = load_payment_status()
                for item in ps.get("paid_items", []):
                    mask = (
                        (df["날짜"].astype(str) == str(item["날짜"])) &
                        (df["이름"] == item["이름"]) &
                        (df["순수입(부호)"] == item["금액"])
                    )
                    df.loc[mask, "결제 여부"] = "결제완료"
    except Exception as e:
        st.error(f"파일 읽기 오류: {e}")

# ─── 목표 달성률 (헤더 바로 아래, 월 선택 위) ───
_detail_for_progress = load_assets_detail()
_y_latest = latest_nonempty_month_key(_detail_for_progress)
latest_total = total_of_month(_detail_for_progress, _y_latest) if _y_latest else 0

# 이번 달 = 가계부 데이터의 가장 최근 월의 잔액
_this_month_balance = None
_this_month_label = None
if df is not None:
    _months_sorted = sorted([m for m in df["월"].unique() if m != "알 수 없음"], reverse=True)
    if _months_sorted:
        _this_month_label = _months_sorted[0]
        _mdf = df[df["월"] == _this_month_label]
        _this_month_balance = int(_mdf["순수입(부호)"].sum())

st.markdown("#### 🎯 목표 달성률")
prog_col_top1, prog_col_top2 = st.columns(2, vertical_alignment="center")

# 이번 년 이벤트 — 연간 목표 잔여 옆에 표시
_events_for_yearly, _, _ = load_roadmap_config()
_now_year_top = datetime.now().year
_this_year_events_top = [e for e in _events_for_yearly if e.get("year") == _now_year_top]
_ty_event_amt_top = sum(int(e.get("amount", 0) or 0) for e in _this_year_events_top)
_ty_event_desc_top = ", ".join(e.get("desc", "") for e in _this_year_events_top) if _this_year_events_top else ""

# 비교용 — 시트의 최신 월 우선, 없으면 사이드바 선택 월의 예산을 미리보기로 표시
_compare_month = _this_month_label or selected_target_month
_compare_target = int(_monthly_targets.get(_compare_month, 0)) if _compare_month else 0

# YYYY-MM → "YYYY년 M월" 헬퍼
def _korean_month_label(mk):
    try:
        _yy, _mm = mk.split("-")
        return f"{int(_yy)}년 {int(_mm)}월"
    except Exception:
        return mk


# 전월 키 ('2026-04' → '2026-03')
def _prev_month_key(mk):
    try:
        _y, _m = map(int, mk.split("-"))
        if _m == 1:
            return f"{_y-1:04d}-12"
        return f"{_y:04d}-{_m-1:02d}"
    except Exception:
        return None


# 전월 대비 증감 라벨 (지출 기준 — 늘면 빨강, 줄면 초록)
# 컬럼별 너비 가중치 — 같은 컬럼명이면 어느 카테고리 표든 동일한 너비
_COL_WEIGHTS = {
    "날짜": 11,
    "내용": 26,
    "금액": 13,
    "사용처": 12,
    "결제 방법": 13,
    "결제 여부": 11,
    "소분류": 14,
    "대분류": 14,
    "비중": 8,
    "카테고리": 16,
    "예산": 13,
    "실제 사용": 13,
    "차이": 18,
    "집행률": 9,
    "상태": 10,
    "회차": 8,
    "년도": 8,
    "나이": 7,
    "보유 자산": 14,
    "저축액": 12,
    "수익률": 8,
    "이벤트": 16,
    "이벤트 금액": 13,
    "합계": 14,
}


def _render_html_table(df, font_rem=1.15, header_bg="#f0f2f6"):
    """st.dataframe 대체용 HTML 표 렌더 — 컬럼명 기준으로 너비 통일"""
    if df is None or df.empty:
        return ""
    cols = list(df.columns)
    # 각 컬럼 weight → 퍼센트
    weights = [_COL_WEIGHTS.get(c, 12) for c in cols]
    total = sum(weights)
    widths = [w / total * 100 for w in weights]

    td = (f"padding:10px 12px; border-bottom:1px solid #eee; "
          f"font-size:{font_rem}rem; word-wrap:break-word; overflow-wrap:break-word; "
          f"vertical-align:middle;")
    th = (f"padding:12px 12px; border-bottom:2px solid #ddd; "
          f"font-size:{font_rem}rem; font-weight:bold; background:{header_bg}; "
          f"text-align:left; word-wrap:break-word;")

    html = '<table style="width:100%; border-collapse:collapse; table-layout:fixed;">'
    html += '<colgroup>'
    for w in widths:
        html += f'<col style="width:{w:.2f}%;">'
    html += '</colgroup>'
    html += '<thead><tr>'
    for c in cols:
        html += f'<th style="{th}">{c}</th>'
    html += '</tr></thead><tbody>'
    for _, row in df.iterrows():
        html += '<tr>'
        for c in cols:
            html += f'<td style="{td}">{row[c]}</td>'
        html += '</tr>'
    html += '</tbody></table>'
    return html


def _to_korean_won(v):
    """금액을 한글 단위로 (예: 100만원, 1.5억원, 5,000원)"""
    v = abs(int(v))
    if v == 0:
        return "0원"
    if v >= 100_000_000:
        n = v / 100_000_000
        return f"{n:.0f}억원" if n == int(n) else f"{n:.1f}억원"
    if v >= 10_000:
        n = v / 10_000
        return f"{int(n)}만원" if n == int(n) else f"{n:.1f}만원"
    return f"{v:,}원"


def _korean_y_ticks(max_val):
    """그래프 y축용 한글 단위 tick — (tickvals, ticktext) 반환"""
    if max_val <= 0:
        return [0], ["0원"]
    # 자릿수 기반 step 자동 결정 (4~6개 정도의 tick이 나오도록)
    import math
    _exp = int(math.floor(math.log10(max_val)))
    _base = 10 ** _exp
    # base 기준으로 step 후보: 0.1, 0.2, 0.5, 1, 2, 5
    for _m in [0.1, 0.2, 0.5, 1, 2, 5]:
        _step = _base * _m
        _n = int(max_val // _step) + 1
        if 4 <= _n <= 7:
            break
    else:
        _step = _base
    _step = int(_step) if _step >= 1 else 1
    vals = list(range(0, int(max_val * 1.1) + _step, _step))
    return vals, [_to_korean_won(v) for v in vals]


def _expense_emoji(pct):
    """지출 증감율에 따른 이모지 — 양수=많이 씀(나쁨), 음수=절약(좋음)"""
    if pct >= 30:  return "🤬"
    if pct >= 15:  return "🥺"
    if pct >= 5:   return "😐"
    if pct <= -30: return "🎉"
    if pct <= -10: return "🥰"
    return ""


def _delta_label_plain(this_amt, prev_amt, expense=True):
    """expander 라벨용 — 평문 (지출이면 이모지 추가)"""
    if prev_amt <= 0:
        return "🆕 신규" if this_amt > 0 else ""
    pct = (this_amt - prev_amt) / prev_amt * 100
    if abs(pct) < 0.1:
        return "(전월 동일)"
    arrow = "▲" if pct > 0 else "▼"
    emj = f" {_expense_emoji(pct)}" if expense else ""
    return f"{arrow} {pct:+.1f}% (전월 {prev_amt:,.0f}원){emj}"


def _delta_label_html(this_amt, prev_amt, expense=True):
    """HTML 색상 라벨 — expense=True면 증가=빨강+이모지, expense=False(수입)면 증가=초록"""
    if prev_amt <= 0:
        if this_amt > 0:
            return "<span style='color:#888; font-size:0.85em; font-weight:500;'>🆕 신규 (전월 0원)</span>"
        return ""
    pct = (this_amt - prev_amt) / prev_amt * 100
    if abs(pct) < 0.1:
        return "<span style='color:#888; font-size:0.85em; font-weight:500;'>(전월 동일)</span>"
    if expense:
        color = "#d32f2f" if pct > 0 else "#2e7d32"
        emj = f" {_expense_emoji(pct)}"
    else:
        color = "#2e7d32" if pct > 0 else "#d32f2f"
        emj = ""
    arrow = "▲" if pct > 0 else "▼"
    return (f"<span style='color:{color}; font-size:0.85em; font-weight:600;'>"
            f"{arrow} {pct:+.1f}% (전월 {prev_amt:,.0f}원){emj}</span>")

# 달성률 → 색상 + 이모지
def _pct_color(pct_ratio):
    """100% 이상 파란색, 미만 빨간색"""
    return "#2563eb" if pct_ratio >= 1.0 else "#ef4444"

def _pct_emoji(pct_ratio):
    """달성률에 따른 이모지"""
    if pct_ratio >= 1.5:
        return "🎊"
    if pct_ratio >= 1.0:
        return "🎉"
    if pct_ratio >= 0.8:
        return "😊"
    if pct_ratio >= 0.5:
        return "🙂"
    if pct_ratio >= 0.3:
        return "😐"
    if pct_ratio > 0:
        return "😢"
    return "😭"

with prog_col_top1:
    if _compare_target > 0 and _this_month_balance is not None:
        _m_remain = max(_compare_target - _this_month_balance, 0)
        _m_ratio = _this_month_balance / _compare_target
        m_pct_clamped = max(min(_m_ratio, 1.0), 0.0)
        _m_color = _pct_color(_m_ratio)
        _m_emoji = _pct_emoji(_m_ratio)
        st.markdown(f"**📅 {_korean_month_label(_this_month_label)}**")
        st.markdown(
            f"<div style='color:{_m_color}; font-weight:700; font-size:1.05rem; margin:4px 0;'>"
            f"{_m_emoji} {_m_ratio:.1%} "
            f"<span style='font-weight:500'>(잔여 {format_won_abs(_m_remain)} / 목표 {format_won_abs(_compare_target)})</span>"
            f"</div>",
            unsafe_allow_html=True
        )
        st.progress(m_pct_clamped)
    elif _compare_target > 0:
        st.markdown(f"**📅 {_korean_month_label(_compare_month)}**")
        st.progress(
            0.0,
            text=f"예산 {format_won_abs(_compare_target)} 설정됨 — 가계부 파일 업로드 필요"
        )
    elif _this_month_label is not None:
        st.markdown(f"**📅 {_korean_month_label(_this_month_label)}**")
        st.caption("이 달 예산 미설정 (사이드바 월별 예산에서 입력)")
    else:
        st.caption("📅 이번 달 목표 미설정 (사이드바 월별 예산에서 입력)")

with prog_col_top2:
    if yearly_target > 0:
        _y_remain = max(yearly_target - latest_total, 0)
        _y_ratio = latest_total / yearly_target
        y_pct_clamped = max(min(_y_ratio, 1.0), 0.0)
        # 한국 시각 오늘 기준 — "YYYY년(M월 기준)"
        _now_local = datetime.now()
        _year_label = f"{_now_local.year}년({_now_local.month}월 기준)"
        _y_color = _pct_color(_y_ratio)
        _y_emoji = _pct_emoji(_y_ratio)
        st.markdown(f"**📆 {_year_label}**")
        st.markdown(
            f"<div style='color:{_y_color}; font-weight:700; font-size:1.05rem; margin:4px 0;'>"
            f"{_y_emoji} {_y_ratio:.1%} "
            f"<span style='font-weight:500'>(목표 {format_won_abs(yearly_target)} · 잔여 {format_won_abs(_y_remain)})</span>"
            f"</div>",
            unsafe_allow_html=True
        )
        # 이번 년 이벤트 — 작은 글씨, 새 줄
        if _this_year_events_top:
            _ev_color_top = "#d32f2f" if _ty_event_amt_top < 0 else "#2e7d32" if _ty_event_amt_top > 0 else "#666"
            _ev_desc_part_top = f" ({_ty_event_desc_top})" if _ty_event_desc_top else ""
            st.markdown(
                f"<div style='color:{_ev_color_top}; font-size:0.85rem; margin:2px 0 6px 0;'>"
                f"이번 년 이벤트 {_ty_event_amt_top:+,.0f}원{_ev_desc_part_top}"
                f"</div>",
                unsafe_allow_html=True
            )
        st.progress(y_pct_clamped)
    else:
        st.caption("📆 이번 년 목표 미설정 (사이드바에서 입력)")
        if _this_year_events_top:
            _ev_color_top = "#d32f2f" if _ty_event_amt_top < 0 else "#2e7d32"
            _ev_desc_part_top = f" ({_ty_event_desc_top})" if _ty_event_desc_top else ""
            st.markdown(
                f"<div style='color:{_ev_color_top}; font-size:0.85rem;'>"
                f"이번 년 이벤트 {_ty_event_amt_top:+,.0f}원{_ev_desc_part_top}"
                f"</div>",
                unsafe_allow_html=True
            )
st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

if df is None:
    st.info("👈 사이드바에서 가계부 파일을 업로드해주세요.")
    st.markdown("""
    ### 사용 방법
    1. **CSV/엑셀 파일 업로드** — 왼쪽 사이드바에서 파일 선택
    2. **월 선택** — 보고 싶은 월 선택
    3. **카테고리 클릭** — 세부 내역 펼쳐보기
    4. **메모 작성** — 정산/피드백/개선점/반영 내역 기록

    ### 필수 컬럼
    `이름`, `날짜`, `대분류`, `소분류`, `순수입(부호)`
    """)

# ─── 월 선택 (CSV 업로드 시에만) ───
if df is not None:
    months = sorted(df["월"].unique(), reverse=True)
    months = [m for m in months if m != "알 수 없음"]

    if not months:
        st.warning("날짜 데이터를 파싱할 수 없습니다.")
    else:
        selected_month = st.selectbox("📅 월 선택", months, index=0)
        month_df = df[df["월"] == selected_month].copy()

        # ─── 수입/지출 분리 ───
        income_df = month_df[month_df["구분"] == "수입"].copy()
        expense_df = month_df[month_df["구분"] == "지출"].copy()

        total_income = income_df["순수입(부호)"].sum()
        total_expense = expense_df["순수입(부호)"].sum()
        balance = total_income + total_expense

        fixed_df = expense_df[expense_df["대분류"].str.contains("고정지출", na=False)].copy()
        variable_df = expense_df[~expense_df["대분류"].str.contains("고정지출", na=False)].copy()

        total_fixed = fixed_df["순수입(부호)"].sum()
        total_variable = variable_df["순수입(부호)"].sum()

        unpaid_df = month_df[month_df["결제 여부"] == "미결제"] if "결제 여부" in month_df.columns else pd.DataFrame()
        unpaid_count = len(unpaid_df)
        unpaid_amount = unpaid_df["실 사용"].sum() if not unpaid_df.empty else 0

        # ─── 요약 카드 ───
        st.markdown(f"### 📊 {selected_month} 요약")
        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            st.markdown(f"""
            <div class="metric-card income">
                <div class="metric-label">총 수입</div>
                <div class="metric-value">{format_won_abs(total_income)}</div>
            </div>
            """, unsafe_allow_html=True)

        with col2:
            st.markdown(f"""
            <div class="metric-card expense">
                <div class="metric-label">총 지출</div>
                <div class="metric-value">{format_won_abs(total_expense)}</div>
            </div>
            """, unsafe_allow_html=True)

        with col3:
            balance_class = "income" if balance >= 0 else "expense"
            st.markdown(f"""
            <div class="metric-card {balance_class}">
                <div class="metric-label">잔액 (수입-지출)</div>
                <div class="metric-value">{format_won(balance)}</div>
            </div>
            """, unsafe_allow_html=True)

        with col4:
            st.markdown(f"""
            <div class="metric-card unpaid">
                <div class="metric-label">미결제 ({unpaid_count}건)</div>
                <div class="metric-value">{format_won_abs(unpaid_amount)}</div>
            </div>
            """, unsafe_allow_html=True)

        with col5:
            # 이번 달 목표 카드 — 잔액 기준 (선택된 월의 예산 조회)
            _sel_target = int(_monthly_targets.get(selected_month, 0))
            if _sel_target > 0:
                m_remain = max(_sel_target - balance, 0)
                st.markdown(f"""
                <div class="metric-card saving">
                    <div class="metric-label">{selected_month} 목표까지</div>
                    <div class="metric-value">{format_won_abs(m_remain)}</div>
                </div>
                """, unsafe_allow_html=True)

        if unpaid_count > 0:
            st.warning(f"⚠️ 미결제 {unpaid_count}건 ({format_won_abs(unpaid_amount)}) — 결제 확인이 필요합니다")


        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

        st.markdown("")
        col_fixed, col_var = st.columns(2)
        with col_fixed:
            st.markdown(f"### 🧾 고정지출 — {format_won_abs(total_fixed)}")
        with col_var:
            st.markdown(f"### 🔄 변동지출 — {format_won_abs(total_variable)}")
        st.markdown("")

        # ─── 탭 ───
        tab_income, tab_fixed, tab_variable, tab_chart, tab_memo, tab_goal, tab_upload = st.tabs([
            "💰 수입", "🧾 고정지출", "🔄 변동지출", "📈 그래프", "🪞 회고", "🎯 목표", "📤 업로드용"
        ])

        with tab_income:
            if income_df.empty:
                st.info("이번 달 수입 내역이 없습니다.")
            else:
                # 전월 소분류별 수입 사전
                _prev_mk_inc = _prev_month_key(selected_month)
                _prev_inc_by_sub = {}
                if _prev_mk_inc:
                    _prev_inc_df = df[(df["월"] == _prev_mk_inc) & (df["구분"] == "수입")]
                    if not _prev_inc_df.empty:
                        _prev_inc_by_sub = _prev_inc_df.groupby("소분류")["순수입(부호)"].sum().to_dict()

                income_summary = income_df.groupby("소분류")["순수입(부호)"].sum().reset_index()
                income_summary.columns = ["소분류", "금액"]
                income_summary = income_summary.sort_values("금액", ascending=False)
                for _, row in income_summary.iterrows():
                    sub_cat = row["소분류"]
                    amount = row["금액"]
                    sub_items = income_df[income_df["소분류"] == sub_cat]
                    _prev_a = _prev_inc_by_sub.get(sub_cat, 0)
                    _delta_html = _delta_label_html(amount, _prev_a, expense=False)
                    if _delta_html:
                        st.markdown(
                            f"<div style='margin: 6px 0 2px 12px;'>{_delta_html}</div>",
                            unsafe_allow_html=True
                        )
                    with st.expander(f"💰 {sub_cat} — {format_won_abs(amount)} ({len(sub_items)}건)"):
                        display_cols = ["날짜", "이름", "순수입(부호)", "사용처"]
                        display_df = sub_items[display_cols].copy()
                        display_df.columns = ["날짜", "내용", "금액", "사용처"]
                        display_df["금액"] = display_df["금액"].apply(lambda x: f"{x:,.0f}원")
                        st.markdown(_render_html_table(display_df), unsafe_allow_html=True)

        with tab_fixed:
            if fixed_df.empty:
                st.info("이번 달 고정지출 내역이 없습니다.")
            else:
                # 전월 소분류별 고정지출 사전
                _prev_mk_fix = _prev_month_key(selected_month)
                _prev_fix_by_sub = {}
                if _prev_mk_fix:
                    _prev_fix_df = df[(df["월"] == _prev_mk_fix) &
                                      (df["구분"] == "지출") &
                                      (df["대분류"].str.contains("고정지출", na=False))]
                    if not _prev_fix_df.empty:
                        _prev_fix_by_sub = _prev_fix_df.groupby("소분류")["실 사용"].sum().to_dict()

                fixed_summary = fixed_df.groupby("소분류")["실 사용"].sum().reset_index()
                fixed_summary.columns = ["소분류", "금액"]
                fixed_summary = fixed_summary.sort_values("금액", ascending=False)
                for _, row in fixed_summary.iterrows():
                    sub_cat = row["소분류"]
                    amount = row["금액"]
                    sub_items = fixed_df[fixed_df["소분류"] == sub_cat]
                    _prev_a = _prev_fix_by_sub.get(sub_cat, 0)
                    _delta_html = _delta_label_html(amount, _prev_a, expense=True)
                    if _delta_html:
                        st.markdown(
                            f"<div style='margin: 6px 0 2px 12px;'>{_delta_html}</div>",
                            unsafe_allow_html=True
                        )
                    with st.expander(f"🧾 {sub_cat} — {format_won_abs(amount)} ({len(sub_items)}건)"):
                        display_cols = ["날짜", "이름", "실 사용", "결제 방법", "결제 여부"]
                        display_df = sub_items[display_cols].copy()
                        display_df.columns = ["날짜", "내용", "금액", "결제 방법", "결제 여부"]
                        display_df["금액"] = display_df["금액"].apply(lambda x: f"{x:,.0f}원")
                        st.markdown(_render_html_table(display_df), unsafe_allow_html=True)

        with tab_variable:
            if variable_df.empty:
                st.info("이번 달 변동지출 내역이 없습니다.")
            else:
                # 사용처 컬럼 정리 (필터 없이 그래프만)
                all_usage = variable_df["사용처"].fillna("").astype(str).str.strip()
                all_usage = all_usage.replace("", "미분류")
                variable_df = variable_df.copy()
                variable_df["사용처_표시"] = all_usage
                usage_options = sorted(variable_df["사용처_표시"].unique().tolist())

                # 사용처별 지출 요약 그래프 (필터 없이 항상 표시)
                if len(usage_options) > 1:
                    usage_summary = variable_df.groupby("사용처_표시")["실 사용"].sum().reset_index()
                    usage_summary.columns = ["사용처", "금액"]
                    usage_summary = usage_summary.sort_values("금액", ascending=False)

                    _usage_max = usage_summary["금액"].max()
                    _usage_vals, _usage_labels = _korean_y_ticks(_usage_max)

                    # 사용처별 고정 색상
                    _usage_color_map = {
                        "공용": "#fff59d",       # 연노란색
                        "효진 개인": "#f8bbd0",  # 연분홍색
                        "효진 공용": "#b3e5fc",  # 하늘색
                    }

                    ug_col1, ug_col2 = st.columns(2)
                    with ug_col1:
                        fig_usage_bar = px.bar(usage_summary, x="사용처", y="금액",
                                               text="금액", color="사용처",
                                               color_discrete_map=_usage_color_map,
                                               color_discrete_sequence=px.colors.qualitative.Set2)
                        fig_usage_bar.update_traces(
                            texttemplate=[_to_korean_won(v) for v in usage_summary["금액"]],
                            textposition="outside", textfont_size=18, cliponaxis=False)
                        fig_usage_bar.update_layout(showlegend=False, height=380,
                                                     margin=dict(l=10, r=10, t=60, b=10),
                                                     xaxis_title="", yaxis_title="",
                                                     xaxis=dict(tickfont=dict(size=16)),
                                                     yaxis=dict(tickvals=_usage_vals,
                                                                ticktext=_usage_labels,
                                                                tickfont=dict(size=15)))
                        st.plotly_chart(fig_usage_bar, use_container_width=True)
                    with ug_col2:
                        fig_usage_pie = px.pie(usage_summary, values="금액", names="사용처",
                                               color="사용처",
                                               color_discrete_map=_usage_color_map,
                                               color_discrete_sequence=px.colors.qualitative.Set2, hole=0.3)
                        fig_usage_pie.update_traces(textposition="inside", textinfo="label+percent", textfont_size=17)
                        fig_usage_pie.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10),
                                                     legend=dict(font=dict(size=15)))
                        st.plotly_chart(fig_usage_pie, use_container_width=True)
                    st.markdown("---")
                    st.markdown("")

                # 전월 대분류별 지출 사전 (증감율 비교용)
                _prev_mk_var = _prev_month_key(selected_month)
                _prev_var_by_cat = {}
                if _prev_mk_var:
                    _prev_var_df = df[(df["월"] == _prev_mk_var) &
                                      (df["구분"] == "지출") &
                                      (~df["대분류"].str.contains("고정지출", na=False))]
                    if not _prev_var_df.empty:
                        _prev_var_by_cat = _prev_var_df.groupby("대분류")["실 사용"].sum().to_dict()

                # 대분류→소분류 드릴다운
                var_major = variable_df.groupby("대분류")["실 사용"].sum().reset_index()
                var_major.columns = ["대분류", "금액"]
                var_major = var_major.sort_values("금액", ascending=False)
                for _, major_row in var_major.iterrows():
                    major_cat = major_row["대분류"]
                    major_amount = major_row["금액"]
                    major_items = variable_df[variable_df["대분류"] == major_cat]
                    _prev_amt = _prev_var_by_cat.get(major_cat, 0)
                    _delta_html = _delta_label_html(major_amount, _prev_amt, expense=True)
                    if _delta_html:
                        st.markdown(
                            f"<div style='margin: 6px 0 2px 12px;'>{_delta_html}</div>",
                            unsafe_allow_html=True
                        )
                    with st.expander(f"{major_cat} — {format_won_abs(major_amount)} ({len(major_items)}건)"):
                        sub_summary = major_items.groupby("소분류")["실 사용"].sum().reset_index()
                        sub_summary.columns = ["소분류", "금액"]
                        sub_summary = sub_summary.sort_values("금액", ascending=False)
                        for _, sub_row in sub_summary.iterrows():
                            sub_cat = sub_row["소분류"]
                            sub_amount = sub_row["금액"]
                            sub_items = major_items[major_items["소분류"] == sub_cat]
                            st.markdown(f"**{sub_cat}** — {format_won_abs(sub_amount)} ({len(sub_items)}건)")
                            display_cols = ["날짜", "이름", "실 사용", "결제 방법", "결제 여부", "사용처"]
                            display_df = sub_items[display_cols].copy()
                            display_df.columns = ["날짜", "내용", "금액", "결제 방법", "결제 여부", "사용처"]
                            display_df["금액"] = display_df["금액"].apply(lambda x: f"{x:,.0f}원")
                            st.markdown(_render_html_table(display_df), unsafe_allow_html=True)
                            st.markdown("---")

        with tab_chart:
            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                st.markdown("#### 📊 대분류별 지출 (막대그래프)")
                expense_by_major = expense_df.groupby("대분류")["실 사용"].sum().reset_index()
                expense_by_major.columns = ["대분류", "금액"]
                expense_by_major = expense_by_major.sort_values("금액", ascending=True)
                if not expense_by_major.empty:
                    fig_bar = px.bar(expense_by_major, x="금액", y="대분류", orientation="h",
                                     text="금액", color="대분류", color_discrete_sequence=px.colors.qualitative.Set2)
                    fig_bar.update_traces(texttemplate="%{text:,.0f}원", textposition="outside",
                                          textfont_size=13, cliponaxis=False)
                    fig_bar.update_layout(showlegend=False, height=400, margin=dict(l=10, r=120, t=10, b=10),
                                          xaxis_title="", yaxis_title="",
                                          yaxis=dict(tickfont=dict(size=13)))
                    st.plotly_chart(fig_bar, use_container_width=True)

            with chart_col2:
                st.markdown("#### 🥧 대분류별 지출 비율 (원그래프)")
                if not expense_by_major.empty:
                    fig_pie = px.pie(expense_by_major, values="금액", names="대분류",
                                     color_discrete_sequence=px.colors.qualitative.Set2, hole=0.3)
                    fig_pie.update_traces(textposition="inside", textinfo="label+percent", textfont_size=13)
                    fig_pie.update_layout(height=400, margin=dict(l=10, r=10, t=10, b=10),
                                          showlegend=True, legend=dict(font=dict(size=12)))
                    st.plotly_chart(fig_pie, use_container_width=True)

            st.markdown("")
            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
            st.markdown("")
            st.markdown("#### 💵 수입 vs 지출 비교")
            compare_col1, compare_col2 = st.columns(2)
            with compare_col1:
                if not income_df.empty:
                    income_by_sub = income_df.groupby("소분류")["순수입(부호)"].sum().reset_index()
                    income_by_sub.columns = ["소분류", "금액"]
                    fig_income_pie = px.pie(income_by_sub, values="금액", names="소분류", title="수입 구성",
                                            color_discrete_sequence=px.colors.qualitative.Pastel, hole=0.3)
                    fig_income_pie.update_traces(textposition="inside", textinfo="label+percent", textfont_size=13)
                    fig_income_pie.update_layout(height=350, margin=dict(l=10, r=10, t=40, b=10),
                                                  legend=dict(font=dict(size=12)))
                    st.plotly_chart(fig_income_pie, use_container_width=True)

            with compare_col2:
                compare_labels = ["수입", "고정지출", "변동지출", "미결제", "잔액"]
                compare_values = [total_income, abs(total_fixed), abs(total_variable), unpaid_amount, balance]
                compare_colors = ["#38ef7d", "#f45c43", "#ff9a76", "#ffd200", "#4facfe"]
                compare_data = pd.DataFrame({"구분": compare_labels, "금액": compare_values, "색상": compare_colors})
                fig_compare = go.Figure(data=[
                    go.Bar(x=compare_data["구분"], y=compare_data["금액"], marker_color=compare_data["색상"],
                           text=[format_won_abs(v) if i < 4 else format_won(v) for i, v in enumerate(compare_data["금액"])],
                           textposition="outside", textfont_size=13, cliponaxis=False)
                ])
                fig_compare.update_layout(title="수입 vs 지출 요약", height=380,
                                          margin=dict(l=10, r=10, t=50, b=10), yaxis_title="원",
                                          xaxis=dict(tickfont=dict(size=13)),
                                          yaxis=dict(tickfont=dict(size=12)))
                st.plotly_chart(fig_compare, use_container_width=True)

        with tab_goal:
            # 목표 데이터 로드
            all_goals = load_budget_goals()
            month_goals = all_goals.get(selected_month, {})

            # 현재 월의 대분류 목록 (지출만)
            expense_categories = sorted(expense_df["대분류"].unique().tolist()) if not expense_df.empty else []

            # ─── 목표 설정 — 다른 월 미리 입력 가능 ───
            with st.expander("⚙️ 월간 목표 설정", expanded=not bool(month_goals)):
                # 설정 대상 월 — 사용자 직접 입력 (연도/월 number_input)
                # 기본값: 현재 보고 있는 월(selected_month) "YYYY-MM" 파싱
                try:
                    _sm_y, _sm_m = map(int, selected_month.split("-"))
                except Exception:
                    _today_g = datetime.now()
                    _sm_y, _sm_m = _today_g.year, _today_g.month

                st.caption("🗓️ **목표 설정 대상 월** — 원하는 연도/월을 직접 입력하세요")
                _gy_col, _gm_col = st.columns(2)
                with _gy_col:
                    _g_year = st.number_input(
                        "연도",
                        min_value=1900, max_value=9999,
                        value=int(st.session_state.get("goal_target_year", _sm_y)),
                        step=1, key="goal_target_year",
                    )
                with _gm_col:
                    _g_month = st.number_input(
                        "월",
                        min_value=1, max_value=12,
                        value=int(st.session_state.get("goal_target_month_num", _sm_m)),
                        step=1, key="goal_target_month_num",
                    )
                goal_month = f"{int(_g_year):04d}-{int(_g_month):02d}"
                # 선택된 목표 대상 월의 저장값 다시 로드
                month_goals = all_goals.get(goal_month, {})
                if goal_month != selected_month:
                    st.caption(f"📌 지금 **{goal_month}** 예산을 미리 설정 중 — 달성률은 화면 상단의 {selected_month} 데이터 기준으로 표시됩니다.")
                st.markdown("---")

                # 전역 등록 카테고리 — 한 번 추가하면 모든 월 편집창에 표시
                _registered_raw = all_goals.get("__registered_cats__", [])
                if not isinstance(_registered_raw, list):
                    _registered_raw = []
                registered_cats = [str(c) for c in _registered_raw if str(c).strip()]

                # 사용자 정의 정렬 + 숨김 목록
                _order_raw = all_goals.get("__cat_order__", [])
                if not isinstance(_order_raw, list):
                    _order_raw = []
                cat_order = [str(c) for c in _order_raw if str(c).strip()]

                _hidden_raw = all_goals.get("__hidden_cats__", [])
                if not isinstance(_hidden_raw, list):
                    _hidden_raw = []
                hidden_cats = set(str(c) for c in _hidden_raw if str(c).strip())

                # 알려진 모든 카테고리 (등록 + 모든 월 저장값 + 현재 데이터)
                _known_cats = set(registered_cats) | set(expense_categories)
                for _mk, _mv in all_goals.items():
                    if _mk.startswith("__") or not isinstance(_mv, dict):
                        continue
                    for k in _mv.keys():
                        if not k.startswith("__"):
                            _known_cats.add(k)

                def _ordered_visible_cats():
                    """사용자 순서 적용 + 숨김 제외 + 미정의 카테고리는 알파벳 순으로 뒤에 추가"""
                    visible = _known_cats - hidden_cats
                    seen = set()
                    out = []
                    for c in cat_order:
                        if c in visible and c not in seen:
                            out.append(c)
                            seen.add(c)
                    for c in sorted(visible):
                        if c not in seen:
                            out.append(c)
                            seen.add(c)
                    return out

                with st.form("budget_goal_form", clear_on_submit=False):
                    # 전체 월간 목표
                    st.markdown(f"### 💰 {goal_month} 전체 월간 목표")
                    total_goal_input = st.number_input(
                        "전체 월간 지출 목표 (원)",
                        min_value=0,
                        value=month_goals.get("__total__", 0),
                        step=100000,
                        format="%d",
                        key=f"goal_{goal_month}___total__",
                        help="카테고리 합산과 별도로 전체 지출 목표를 설정합니다"
                    )

                    st.markdown("---")
                    st.markdown(f"### 📂 {goal_month} 카테고리별 목표")
                    goal_inputs = {}

                    # 사용자 정렬 + 숨김 적용된 표시 목록
                    all_cats = _ordered_visible_cats()
                    if not all_cats:
                        st.info("표시할 카테고리가 없습니다. 아래 '새 카테고리 추가' 또는 위 '카테고리 관리'에서 숨김 해제하세요.")

                    # 2열로 배치
                    for i in range(0, len(all_cats), 2):
                        cols = st.columns(2)
                        for j, col in enumerate(cols):
                            idx = i + j
                            if idx < len(all_cats):
                                cat = all_cats[idx]
                                with col:
                                    goal_inputs[cat] = st.number_input(
                                        f"{cat}",
                                        min_value=0,
                                        value=month_goals.get(cat, 0),
                                        step=10000,
                                        format="%d",
                                        key=f"goal_{goal_month}_{cat}"
                                    )

                    # 새 카테고리 추가 — 이름만 입력하면 등록, 금액은 위 입력창에서
                    st.markdown("**➕ 새 카테고리 추가**")
                    new_cat_name = st.text_input(
                        "새 카테고리 이름",
                        placeholder="예: 여행, 교육비",
                        key=f"new_goal_cat_{goal_month}",
                        label_visibility="collapsed",
                    )

                    if st.form_submit_button(f"💾 {goal_month} 월간 목표 저장", use_container_width=True, type="primary"):
                        # 0원이 아닌 것만 월별 저장
                        saved_goals = {k: v for k, v in goal_inputs.items() if v > 0}
                        if total_goal_input > 0:
                            saved_goals["__total__"] = total_goal_input
                        # 새 카테고리: 이름만으로 전역 등록 (금액은 다음 저장 때 위 입력창에서)
                        _new_name = new_cat_name.strip()
                        if _new_name and _new_name not in registered_cats:
                            registered_cats.append(_new_name)
                        # 새로 등록된 이름은 사용자 순서 끝에 추가 (이미 있으면 유지)
                        if _new_name and _new_name not in cat_order:
                            cat_order.append(_new_name)
                        # 기존 주간 목표 설정 유지
                        for k, v in month_goals.items():
                            if k.startswith("__weekly_"):
                                saved_goals[k] = v
                        all_goals[goal_month] = saved_goals
                        all_goals["__registered_cats__"] = sorted(set(registered_cats))
                        all_goals["__cat_order__"] = cat_order
                        save_budget_goals(all_goals)
                        if _new_name:
                            st.success(f"✅ {goal_month} 저장 + 카테고리 '{_new_name}' 등록 완료!")
                        else:
                            st.success(f"✅ {goal_month} 월간 목표가 저장되었습니다!")
                        st.rerun()

                # ─── 카테고리 관리 (드래그 — 순서 변경 + 표시/숨김 통합) ───
                # ⚠️ 외부 expander 안에서는 expander 중첩이 iframe 컴포넌트(streamlit_sortables)
                #    렌더링을 깨뜨리므로 expander 대신 토글 버튼으로 펼침 제어
                st.markdown("---")
                _show_mgr_key = f"show_cat_mgr_{goal_month}"
                if _show_mgr_key not in st.session_state:
                    st.session_state[_show_mgr_key] = False
                _mgr_label = (
                    f"🔧 카테고리 관리 닫기 ▴" if st.session_state[_show_mgr_key]
                    else f"🔧 카테고리 관리 — 끌어서 순서 변경 / 숨기기 ({len(_known_cats)}개) ▾"
                )
                if st.button(_mgr_label, key=f"toggle_mgr_{goal_month}", use_container_width=True):
                    st.session_state[_show_mgr_key] = not st.session_state[_show_mgr_key]
                    st.rerun()

                if st.session_state[_show_mgr_key]:
                    _visible_list = _ordered_visible_cats()
                    if not _known_cats:
                        st.caption("등록된 카테고리가 없습니다.")
                    elif _HAS_SORTABLE:
                        st.caption("👆 카테고리를 **끌어서(drag)** 원하는 위치로 옮기세요. 다른 칸으로 옮기면 표시/숨김이 바뀝니다.")

                        _white_style = """
                        .sortable-component {
                            background-color: #ffffff;
                            padding: 8px;
                        }
                        .sortable-container {
                            background-color: #fafafa;
                            border: 1px solid #e0e0e0;
                            border-radius: 8px;
                            padding: 10px;
                            min-height: 80px;
                        }
                        .sortable-container-header {
                            background-color: #f5f5f5;
                            color: #333;
                            border-radius: 6px;
                            padding: 8px 12px;
                            font-weight: 600;
                            margin-bottom: 8px;
                        }
                        .sortable-container-body {
                            background-color: #ffffff;
                        }
                        .sortable-item,
                        .sortable-item:hover,
                        .sortable-item:focus,
                        .sortable-item:active,
                        .sortable-item.sortable-chosen,
                        .sortable-item.sortable-ghost,
                        .sortable-item.sortable-drag {
                            color: #222 !important;
                        }
                        .sortable-item {
                            background-color: #ffffff;
                            border: 1px solid #d8d8d8;
                            border-radius: 6px;
                            padding: 8px 12px;
                            margin: 4px 0;
                            box-shadow: 0 1px 2px rgba(0,0,0,0.04);
                            cursor: grab;
                        }
                        .sortable-item:hover {
                            background-color: #eef5ff;
                            border-color: #99c2ff;
                        }
                        .sortable-item.sortable-chosen {
                            background-color: #e3f0ff;
                            border-color: #5599ff;
                        }
                        """

                        _sort_input = [
                            {"header": "👁️ 표시 중", "items": _visible_list},
                            {"header": "🔕 숨김", "items": sorted(hidden_cats)},
                        ]

                        _result = _sort_items(
                            _sort_input,
                            multi_containers=True,
                            direction="vertical",
                            custom_style=_white_style,
                            key=f"sortable_cats_{goal_month}",
                        )

                        if _result:
                            _new_visible = list(_result[0]["items"])
                            _new_hidden = list(_result[1]["items"])
                            _changed_order = (_new_visible != _visible_list)
                            _changed_hidden = (set(_new_hidden) != hidden_cats)
                            if _changed_order or _changed_hidden:
                                all_goals["__cat_order__"] = _new_visible + _new_hidden
                                all_goals["__hidden_cats__"] = sorted(_new_hidden)
                                save_budget_goals(all_goals)
                                st.rerun()
                    else:
                        st.warning("드래그 정렬 모듈이 없습니다. `pip install streamlit-sortables` 후 재실행하세요.")

                # 주간 목표 설정 (폼 밖 — 라디오 즉시 반영)
                st.markdown("---")
                st.markdown(f"### 📆 {goal_month} 주간 목표 설정")
                weekly_mode = st.radio(
                    "주간 목표 방식",
                    ["자동 (월간 목표 ÷ 주차수)", "직접 설정"],
                    index=0 if month_goals.get("__weekly_mode__", "auto") == "auto" else 1,
                    key=f"weekly_mode_{goal_month}",
                    horizontal=True
                )

                if weekly_mode == "자동 (월간 목표 ÷ 주차수)":
                    # 자동 모드 — 계산 결과 미리보기
                    cat_goals_preview = {k: v for k, v in month_goals.items() if not k.startswith("__")}
                    overall_preview = month_goals.get("__total__", 0)
                    total_preview = overall_preview if overall_preview > 0 else sum(cat_goals_preview.values())
                    if total_preview > 0:
                        st.caption("월간 목표 ÷ 4주 기준 자동 계산 결과:")
                        auto_rows = []
                        for cat, amt in sorted(cat_goals_preview.items()):
                            auto_rows.append({"카테고리": cat, "월간 목표": f"{amt:,.0f}원", "주간 목표": f"{amt / 4:,.0f}원"})
                        auto_rows.append({"카테고리": "🪙 전체", "월간 목표": f"{total_preview:,.0f}원", "주간 목표": f"{total_preview / 4:,.0f}원"})
                        st.dataframe(pd.DataFrame(auto_rows), use_container_width=True, hide_index=True)
                    else:
                        st.info("월간 목표를 먼저 설정하면 자동 계산 결과가 표시됩니다.")

                    # 자동 모드 저장
                    if month_goals.get("__weekly_mode__") != "auto":
                        month_goals["__weekly_mode__"] = "auto"
                        all_goals[goal_month] = month_goals
                        save_budget_goals(all_goals)
                        st.rerun()

                else:
                    # 직접 설정 모드
                    with st.form("weekly_goal_form", clear_on_submit=False):
                        st.caption("주간 전체 목표와 카테고리별 주간 목표를 직접 설정합니다")
                        weekly_goal_input = st.number_input(
                            "주간 전체 지출 목표 (원)",
                            min_value=0,
                            value=month_goals.get("__weekly_total__", 0),
                            step=10000,
                            format="%d",
                            key=f"weekly_total_{goal_month}"
                        )
                        # 카테고리별 주간 목표 (전체 월 + 등록 + 현재 데이터 카테고리 통합)
                        all_known_cats = set()
                        for _mk, _mv in all_goals.items():
                            if _mk.startswith("__") or not isinstance(_mv, dict):
                                continue
                            for k in _mv.keys():
                                if not k.startswith("__"):
                                    all_known_cats.add(k)
                                elif k.startswith("__weekly_cat_"):
                                    all_known_cats.add(k.replace("__weekly_cat_", ""))
                        all_known_cats.update(expense_categories)
                        all_known_cats.update(registered_cats)
                        display_cats = sorted(all_known_cats)
                        weekly_cat_inputs = {}
                        if display_cats:
                            for i in range(0, len(display_cats), 2):
                                w_cols = st.columns(2)
                                for j, w_col in enumerate(w_cols):
                                    w_idx = i + j
                                    if w_idx < len(display_cats):
                                        w_cat = display_cats[w_idx]
                                        with w_col:
                                            weekly_cat_inputs[w_cat] = st.number_input(
                                                f"{w_cat} (주간)",
                                                min_value=0,
                                                value=month_goals.get(f"__weekly_cat_{w_cat}", 0),
                                                step=5000,
                                                format="%d",
                                                key=f"wgoal_{goal_month}_{w_cat}"
                                            )

                        if st.form_submit_button(f"💾 {goal_month} 주간 목표 저장", use_container_width=True, type="primary"):
                            # 기존 월간 목표 유지 + 주간 목표 업데이트
                            saved_goals = {k: v for k, v in month_goals.items() if not k.startswith("__weekly_")}
                            saved_goals["__weekly_mode__"] = "manual"
                            if weekly_goal_input > 0:
                                saved_goals["__weekly_total__"] = weekly_goal_input
                            for w_cat, w_amt in weekly_cat_inputs.items():
                                if w_amt > 0:
                                    saved_goals[f"__weekly_cat_{w_cat}"] = w_amt
                            all_goals[goal_month] = saved_goals
                            save_budget_goals(all_goals)
                            st.success(f"✅ {goal_month} 주간 목표가 저장되었습니다!")
                            st.rerun()

            # 목표 새로 로드 (저장 후 반영)
            all_goals = load_budget_goals()
            month_goals = all_goals.get(selected_month, {})

            # 카테고리별 목표만 분리 (내부 키 제외)
            cat_goals = {k: v for k, v in month_goals.items() if not k.startswith("__")}
            overall_goal = month_goals.get("__total__", 0)
            weekly_mode_saved = month_goals.get("__weekly_mode__", "auto")

            # 사용자 정렬/숨김 적용 (저장 직후 최신값 기준)
            _order_after_raw = all_goals.get("__cat_order__", [])
            _order_after = [str(c) for c in (_order_after_raw if isinstance(_order_after_raw, list) else [])]
            _hidden_after_raw = all_goals.get("__hidden_cats__", [])
            _hidden_after_set = set(str(c) for c in (_hidden_after_raw if isinstance(_hidden_after_raw, list) else []))
            cat_goals = {k: v for k, v in cat_goals.items() if k not in _hidden_after_set}

            def _sorted_cats_for_display(cats_iter):
                _cats = set(cats_iter)
                _seen, _out = set(), []
                for _c in _order_after:
                    if _c in _cats and _c not in _seen:
                        _out.append(_c); _seen.add(_c)
                for _c in sorted(_cats):
                    if _c not in _seen:
                        _out.append(_c); _seen.add(_c)
                return _out

            if not cat_goals and not overall_goal:
                pass  # 안내 문구 없음 — 사용자 요청
            else:
                # ※ 월간 달성률은 회고 탭으로 이동되었습니다 (목표 vs 실제 + 회고 메모)
                # display_total_goal — 주간 자동 모드 계산에 필요
                display_total_goal = overall_goal if overall_goal > 0 else sum(cat_goals.values())

                # ─── 주간 달성률 ───
                st.markdown("#### 📆 주간 달성률")

                # 날짜 파싱 — 주차 계산 (한글 형식 지원)
                if not expense_df.empty and "날짜" in expense_df.columns:
                    week_df = expense_df.copy()
                    week_df["날짜_parsed"] = parse_dates_kr(week_df["날짜"])
                    week_df = week_df.dropna(subset=["날짜_parsed"])

                    if not week_df.empty:
                        # 주차 계산 (월 기준 1~5주)
                        week_df["일"] = week_df["날짜_parsed"].dt.day
                        week_df["주차"] = ((week_df["일"] - 1) // 7 + 1).astype(int)
                        week_df["주차"] = week_df["주차"].clip(upper=5)

                        weeks_in_month = sorted(week_df["주차"].unique())
                        num_weeks = max(weeks_in_month) if weeks_in_month else 4

                        # 주간 목표 결정 (직접 설정 vs 자동 계산)
                        if weekly_mode_saved == "manual":
                            # 직접 설정한 주간 목표 사용
                            weekly_total_goal = month_goals.get("__weekly_total__", 0)
                            weekly_cat_goals = {}
                            for cat in cat_goals:
                                manual_val = month_goals.get(f"__weekly_cat_{cat}", 0)
                                if manual_val > 0:
                                    weekly_cat_goals[cat] = manual_val
                                else:
                                    # 직접 설정 안 한 카테고리는 월간 목표 / 주차수
                                    weekly_cat_goals[cat] = cat_goals[cat] / num_weeks
                            if weekly_total_goal == 0:
                                weekly_total_goal = sum(weekly_cat_goals.values())
                            st.caption("📌 직접 설정한 주간 목표 적용 중")
                        else:
                            # 자동: 월간 목표 / 주차수
                            weekly_cat_goals = {cat: amt / num_weeks for cat, amt in cat_goals.items()}
                            weekly_total_goal = (display_total_goal / num_weeks) if display_total_goal > 0 else 0

                        # 전 주차 요약 테이블 (한눈에 보기)
                        st.markdown("**📋 전 주차 요약**")
                        all_week_rows = []
                        for w in weeks_in_month:
                            w_expense = week_df[week_df["주차"] == w]
                            w_spent = w_expense["실 사용"].sum() if not w_expense.empty else 0
                            w_pct = (w_spent / weekly_total_goal * 100) if weekly_total_goal > 0 else 0
                            w_status = "✅ 여유" if w_pct <= 80 else ("⚠️ 주의" if w_pct <= 100 else "🚨 초과")
                            all_week_rows.append({
                                "주차": f"{w}주차 ({(w-1)*7+1}~{min(w*7, 31)}일)",
                                "주간 목표": f"{weekly_total_goal:,.0f}원",
                                "사용": f"{w_spent:,.0f}원",
                                "잔여": f"{weekly_total_goal - w_spent:,.0f}원",
                                "달성률": f"{w_pct:.0f}%",
                                "상태": w_status
                            })
                        all_week_df = pd.DataFrame(all_week_rows)
                        st.dataframe(all_week_df, use_container_width=True, hide_index=True)

                        st.markdown("---")

                        # 특정 주차 상세 (카테고리별)
                        if weekly_cat_goals:
                            selected_week = st.selectbox(
                                "주차별 카테고리 상세",
                                weeks_in_month,
                                format_func=lambda w: f"{w}주차 ({(w-1)*7+1}일 ~ {min(w*7, 31)}일)"
                            )

                            week_expense = week_df[week_df["주차"] == selected_week]

                            week_rows = []
                            for cat, w_goal in sorted(weekly_cat_goals.items()):
                                if not week_expense.empty:
                                    w_spent = week_expense[week_expense["대분류"] == cat]["실 사용"].sum()
                                else:
                                    w_spent = 0
                                w_pct = (w_spent / w_goal * 100) if w_goal > 0 else 0
                                w_remain = w_goal - w_spent
                                w_status = "✅ 여유" if w_pct <= 80 else ("⚠️ 주의" if w_pct <= 100 else "🚨 초과")
                                week_rows.append({
                                    "카테고리": cat,
                                    "주간 목표": f"{w_goal:,.0f}원",
                                    "사용": f"{w_spent:,.0f}원",
                                    "잔여": f"{w_remain:,.0f}원",
                                    "달성률": f"{w_pct:.0f}%",
                                    "상태": w_status
                                })

                            week_goal_df = pd.DataFrame(week_rows)
                            st.dataframe(week_goal_df, use_container_width=True, hide_index=True)
                    else:
                        st.warning("날짜 데이터를 파싱할 수 없어 주간 분석이 불가합니다.")
                else:
                    st.info("지출 데이터가 없습니다.")

        with tab_memo:
            st.markdown(f"### 🪞 {selected_month} 지출 회고")

            # 회고 메모 미리 로드 (목표 회고 섹션에서도 사용)
            memo = load_memo(selected_month)

            # ─── 🎯 목표 vs 실제 ───
            _all_goals_review = load_budget_goals()
            _month_goals_review = _all_goals_review.get(selected_month, {})
            _overall_goal_review = int(_month_goals_review.get("__total__", 0) or 0)
            _cat_goals_review = {k: int(v) for k, v in _month_goals_review.items()
                                 if not k.startswith("__") and isinstance(v, (int, float)) and v > 0}

            # 숨김 카테고리 제외
            _hidden_review = _all_goals_review.get("__hidden_cats__", [])
            if not isinstance(_hidden_review, list):
                _hidden_review = []
            _hidden_review_set = set(_hidden_review)
            _cat_goals_review = {k: v for k, v in _cat_goals_review.items() if k not in _hidden_review_set}

            # 사용자 정의 순서
            _cat_order_review = _all_goals_review.get("__cat_order__", [])
            if not isinstance(_cat_order_review, list):
                _cat_order_review = []

            def _ordered_review_cats(cats_iter):
                _cats = set(cats_iter)
                _seen, _out = set(), []
                for _c in _cat_order_review:
                    if _c in _cats and _c not in _seen:
                        _out.append(_c); _seen.add(_c)
                for _c in sorted(_cats):
                    if _c not in _seen:
                        _out.append(_c); _seen.add(_c)
                return _out

            def _variance_style(spent, goal):
                """달성도(소비/목표 비율) 기반 색상·이모지·라벨"""
                if goal <= 0:
                    return "#666", "", "", 0.0
                _ratio = spent / goal
                _diff = goal - spent  # 양수=절약, 음수=초과
                if _ratio <= 0.8:
                    _emoji = "🎉"
                elif _ratio <= 1.0:
                    _emoji = "✅"
                elif _ratio <= 1.2:
                    _emoji = "⚠️"
                else:
                    _emoji = "🚨"
                _color = "#2563eb" if _ratio <= 1.0 else "#ef4444"
                if _diff >= 0:
                    _label = f"절약 {format_won_abs(_diff)}"
                else:
                    _label = f"초과 {format_won_abs(-_diff)}"
                return _color, _emoji, _label, _ratio

            if _overall_goal_review > 0 or _cat_goals_review:
                # ─── 📅 월간 달성률 (요약 + 카테고리 표 + 막대그래프) ───
                st.markdown("#### 📅 월간 달성률")
                _total_spent_month = abs(expense_df["실 사용"].sum()) if not expense_df.empty else 0
                _display_total_goal_month = (_overall_goal_review
                                             if _overall_goal_review > 0
                                             else sum(_cat_goals_review.values()))
                _total_pct_month = (_total_spent_month / _display_total_goal_month * 100) if _display_total_goal_month > 0 else 0
                _summary_color = "🟢" if _total_pct_month <= 100 else "🔴"
                _goal_label_month = "전체 목표" if _overall_goal_review > 0 else "카테고리 합산"
                st.markdown(
                    f"**{_summary_color} {_goal_label_month}: "
                    f"{format_won_abs(_total_spent_month)} / "
                    f"{format_won_abs(_display_total_goal_month)} "
                    f"({_total_pct_month:.0f}%)**"
                )
                st.progress(min(_total_pct_month / 100, 1.0))

                if _cat_goals_review:
                    _display_cats_review = _ordered_review_cats(_cat_goals_review.keys())
                    _goal_rows = []
                    _chart_rows = []
                    for _cat in _display_cats_review:
                        _g = _cat_goals_review[_cat]
                        if expense_df.empty:
                            _s = 0
                        else:
                            _s = abs(expense_df[expense_df["대분류"] == _cat]["실 사용"].sum())
                        _pct = (_s / _g * 100) if _g > 0 else 0
                        _rem = _g - _s
                        _stat = "✅ 여유" if _pct <= 80 else ("⚠️ 주의" if _pct <= 100 else "🚨 초과")
                        _goal_rows.append({
                            "카테고리": _cat,
                            "목표": f"{_g:,.0f}원",
                            "사용": f"{_s:,.0f}원",
                            "잔여": f"{_rem:,.0f}원",
                            "달성률": f"{_pct:.0f}%",
                            "상태": _stat,
                        })
                        _chart_rows.append({
                            "카테고리": _cat,
                            "달성률": min(_pct, 150),
                            "색상": "#38ef7d" if _pct <= 100 else "#f45c43",
                        })
                    st.dataframe(pd.DataFrame(_goal_rows), use_container_width=True, hide_index=True)

                    # 달성률 막대그래프
                    _chart_df = pd.DataFrame(_chart_rows)
                    _fig_goal = go.Figure()
                    _fig_goal.add_trace(go.Bar(
                        x=_chart_df["카테고리"], y=_chart_df["달성률"],
                        marker_color=_chart_df["색상"],
                        text=[f"{v:.0f}%" for v in _chart_df["달성률"]],
                        textposition="outside", textfont_size=13, cliponaxis=False,
                    ))
                    _fig_goal.add_hline(y=100, line_dash="dash", line_color="gray",
                                        annotation_text="목표 100%")
                    _fig_goal.update_layout(height=380, margin=dict(l=10, r=10, t=40, b=10),
                                            yaxis_title="달성률 (%)", xaxis_title="",
                                            xaxis=dict(tickfont=dict(size=13)),
                                            yaxis=dict(tickfont=dict(size=12)))
                    st.plotly_chart(_fig_goal, use_container_width=True)

                st.markdown("")
                st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
                st.markdown("")

                # ─── 🎯 목표 vs 실제 (카드별 회고 메모) ───
                st.markdown("#### 🎯 목표 vs 실제 (회고 메모)")
                st.caption("각 항목별로 얼마나 잘 지켰는지 / 어디서 초과됐는지 — 회고 메모에 이유를 적어두면 다음 달 개선에 도움이 됩니다")

                _goal_memo = memo.get("목표 회고", {})
                if not isinstance(_goal_memo, dict):
                    _goal_memo = {}

                # 전체 목표 vs 총 지출
                if _overall_goal_review > 0:
                    _total_spent_review = abs(expense_df["실 사용"].sum()) if not expense_df.empty else 0
                    _color, _emoji, _label, _ratio = _variance_style(_total_spent_review, _overall_goal_review)
                    with st.container(border=True):
                        _hc1, _hc2 = st.columns([3, 2])
                        with _hc1:
                            st.markdown(f"**🪙 전체** — 목표 {format_won_abs(_overall_goal_review)} · 사용 {format_won_abs(_total_spent_review)}")
                        with _hc2:
                            st.markdown(
                                f"<div style='text-align:right; color:{_color}; font-weight:700; font-size:1.05rem'>"
                                f"{_emoji} {_ratio:.1%} · {_label}</div>",
                                unsafe_allow_html=True
                            )
                        _goal_memo["__total__"] = st.text_area(
                            "회고 메모",
                            value=_goal_memo.get("__total__", ""),
                            key=f"goal_memo_total_{selected_month}",
                            height=70,
                            placeholder="왜 이렇게 됐을까? 무엇이 잘 지켜졌고 무엇이 어긋났는지...",
                            label_visibility="collapsed",
                        )

                # 카테고리별 목표 vs 실제
                for _cat in _ordered_review_cats(_cat_goals_review.keys()):
                    _g = _cat_goals_review[_cat]
                    if expense_df.empty:
                        _s = 0
                    else:
                        _s = abs(expense_df[expense_df["대분류"] == _cat]["실 사용"].sum())
                    _color, _emoji, _label, _ratio = _variance_style(_s, _g)
                    with st.container(border=True):
                        _cc1, _cc2 = st.columns([3, 2])
                        with _cc1:
                            st.markdown(f"**📂 {_cat}** — 목표 {format_won_abs(_g)} · 사용 {format_won_abs(_s)}")
                        with _cc2:
                            st.markdown(
                                f"<div style='text-align:right; color:{_color}; font-weight:700; font-size:1.05rem'>"
                                f"{_emoji} {_ratio:.1%} · {_label}</div>",
                                unsafe_allow_html=True
                            )
                        _goal_memo[_cat] = st.text_area(
                            "회고 메모",
                            value=_goal_memo.get(_cat, ""),
                            key=f"goal_memo_{_cat}_{selected_month}",
                            height=70,
                            placeholder=f"{_cat}: 왜 이런 결과가 나왔을까?",
                            label_visibility="collapsed",
                        )

                memo["목표 회고"] = _goal_memo

                st.markdown("")
                st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
                st.markdown("")
            else:
                st.info(f"💡 {selected_month}의 목표가 설정되지 않았습니다. **🎯 목표** 탭에서 예산을 잡으면 이 자리에서 목표 vs 실제 비교와 회고를 함께 작성할 수 있어요.")
                st.markdown("")

            # ─── 회고용 요약 + 그래프 ───
            # 요약 수치
            summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
            with summary_col1:
                st.metric("총 수입", format_won_abs(total_income))
            with summary_col2:
                st.metric("총 지출", format_won_abs(total_expense))
            with summary_col3:
                st.metric("잔액", format_won(balance))
            with summary_col4:
                if unpaid_count > 0:
                    st.metric("미결제", f"{unpaid_count}건 / {format_won_abs(unpaid_amount)}")
                else:
                    st.metric("미결제", "없음")

            # 그래프 2개 나란히
            memo_chart1, memo_chart2 = st.columns(2)
            with memo_chart1:
                # 대분류별 지출 원그래프
                memo_expense = expense_df.groupby("대분류")["실 사용"].sum().reset_index()
                memo_expense.columns = ["대분류", "금액"]
                if not memo_expense.empty:
                    fig_memo_pie = px.pie(memo_expense, values="금액", names="대분류",
                                          color_discrete_sequence=px.colors.qualitative.Set2, hole=0.3)
                    fig_memo_pie.update_traces(textposition="inside", textinfo="label+percent", textfont_size=13)
                    fig_memo_pie.update_layout(height=300, margin=dict(l=5, r=5, t=5, b=5),
                                               showlegend=False)
                    st.plotly_chart(fig_memo_pie, use_container_width=True)

            with memo_chart2:
                # 수입/고정/변동/잔액 막대
                memo_bar_data = pd.DataFrame({
                    "구분": ["수입", "고정지출", "변동지출", "잔액"],
                    "금액": [total_income, abs(total_fixed), abs(total_variable), balance],
                    "색상": ["#38ef7d", "#f45c43", "#ff9a76", "#4facfe"]
                })
                fig_memo_bar = go.Figure(data=[
                    go.Bar(x=memo_bar_data["구분"], y=memo_bar_data["금액"],
                           marker_color=memo_bar_data["색상"],
                           text=[format_won_abs(v) for v in memo_bar_data["금액"]],
                           textposition="outside", textfont_size=13, cliponaxis=False)
                ])
                fig_memo_bar.update_layout(height=300, margin=dict(l=5, r=5, t=40, b=5),
                                            yaxis=dict(visible=False), xaxis_title="",
                                            xaxis=dict(tickfont=dict(size=13)))
                st.plotly_chart(fig_memo_bar, use_container_width=True)

            # 대분류별 지출 순위 (텍스트)
            if not memo_expense.empty:
                memo_expense_sorted = memo_expense.sort_values("금액", ascending=False)
                rank_text = " · ".join([f"**{r['대분류']}** {format_won_abs(r['금액'])}"
                                        for _, r in memo_expense_sorted.head(5).iterrows()])
                st.markdown(f"📊 지출 TOP: {rank_text}")

            st.markdown("")
            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
            st.markdown("")

            # ─── 회고 메모 입력 (목표 회고는 위에서 이미 memo dict에 반영됨) ───
            st.markdown("#### 📝 종합 회고")
            memo_col1, memo_col2 = st.columns(2)
            with memo_col1:
                memo["정산"] = st.text_area("💰 정산", value=memo.get("정산", ""), height=200,
                    placeholder="이번 달 정산 내용을 적어주세요...\n예: 총 수입 대비 지출 비율, 예산 초과 항목 등")
                memo["개선점"] = st.text_area("🔧 개선점", value=memo.get("개선점", ""), height=200,
                    placeholder="다음 달에 개선할 점...\n예: 외식비 줄이기, 구독 정리 등")
            with memo_col2:
                memo["피드백"] = st.text_area("💬 피드백", value=memo.get("피드백", ""), height=200,
                    placeholder="이번 달 소비 패턴에 대한 피드백...\n예: 식비가 예상보다 많았음, 투자 수익 양호")
                memo["지난 달 반영 내역"] = st.text_area("✅ 지난 달 반영 내역", value=memo.get("지난 달 반영 내역", ""), height=200,
                    placeholder="지난 달 개선점을 이번 달에 어떻게 반영했는지...")
            if st.button("💾 회고 저장 (목표 회고 + 종합 회고 모두)", use_container_width=True, type="primary"):
                save_memo(selected_month, memo)
                st.success(f"✅ {selected_month} 회고가 저장되었습니다!")

        # ─── 📤 업로드용 탭 — 한 장 요약 (인쇄/PDF용) ───
        with tab_upload:
            # 업로드용 전용 스타일 — 글자 크기 키움 + 표 행 통일
            st.markdown("""
            <style>
            .up-section { font-size:1.6rem; font-weight:700; margin-top:1rem; margin-bottom:0.6rem; }
            .up-subsection { font-size:1.25rem; font-weight:600; margin-top:1rem; margin-bottom:0.4rem; }
            .up-divider { border-top:2px solid #e0e0e0; margin:2rem 0; }
            </style>
            """, unsafe_allow_html=True)

            # 데이터 재로드 (탭 순서 무관)
            _up_memo = load_memo(selected_month)
            _up_goals = load_budget_goals()
            _up_assets = load_assets_detail()
            _up_events, _up_rate, _up_settings = load_roadmap_config()
            _up_monthly_targets = _up_settings.get("monthly_targets", {}) or {}
            _up_yearly_target = int(_up_settings.get("yearly_target", 0) or 0)

            # 표 헬퍼: HTML 직접 렌더 (글자 1.2rem 고정, 스크롤 없음)
            def _up_show_table(_d):
                st.markdown(_render_html_table(_d, font_rem=1.2), unsafe_allow_html=True)

            st.caption("👆 이 화면을 그대로 인쇄(Ctrl+P) → PDF로 저장하면 한 장 요약이 됩니다.")

            # ─── 🎯 목표 달성률 (월간 + 연간) ───
            _up_m_target = int(_up_monthly_targets.get(selected_month, 0) or 0)
            _up_m_balance = int(balance)

            # 연간 — 재산 내역 최신 월 합계
            _up_monthly_assets = _up_assets.get("monthly", {})
            _up_latest_asset_total = 0
            _up_latest_asset_month = None
            _up_cands = sorted([m for m, rows in _up_monthly_assets.items() if rows])
            if _up_cands:
                _up_latest_asset_month = _up_cands[-1]
                _up_latest_asset_total = sum(int(r.get("amount", 0) or 0) for r in _up_monthly_assets[_up_latest_asset_month])

            # 이번 년 이벤트
            _up_now = datetime.now()
            _up_year_now = _up_now.year
            _up_this_year_events = [e for e in _up_events if e.get("year") == _up_year_now]
            _up_ty_event_amt = sum(int(e.get("amount", 0) or 0) for e in _up_this_year_events)
            _up_ty_event_desc = ", ".join(e.get("desc", "") for e in _up_this_year_events) if _up_this_year_events else ""

            if _up_m_target > 0 or _up_yearly_target > 0:
                st.markdown('<div class="up-section">🎯 목표 달성률</div>', unsafe_allow_html=True)
                _gc1, _gc2 = st.columns(2, vertical_alignment="center")
                with _gc1:
                    st.markdown(f"**📅 {selected_month} 월간 목표**")
                    if _up_m_target > 0:
                        _mr = _up_m_balance / _up_m_target if _up_m_target else 0
                        _mrem = max(_up_m_target - _up_m_balance, 0)
                        _mc = _pct_color(_mr); _me = _pct_emoji(_mr)
                        st.markdown(
                            f"<div style='color:{_mc}; font-weight:700; font-size:1.2rem; margin:6px 0;'>"
                            f"{_me} {_mr:.1%} <span style='font-weight:500; font-size:1.05rem'>"
                            f"(잔액 {format_won_abs(_up_m_balance)} / 목표 {format_won_abs(_up_m_target)} · 잔여 {format_won_abs(_mrem)})"
                            f"</span></div>", unsafe_allow_html=True)
                        st.progress(max(min(_mr, 1.0), 0.0))
                    else:
                        st.caption(f"📅 {selected_month} 월간 목표 미설정")
                with _gc2:
                    _yl = f"{_up_year_now}년({_up_now.month}월 기준)"
                    st.markdown(f"**📆 {_yl} 연간 목표**")
                    if _up_yearly_target > 0:
                        _yr = _up_latest_asset_total / _up_yearly_target if _up_yearly_target else 0
                        _yrem = max(_up_yearly_target - _up_latest_asset_total, 0)
                        _yc = _pct_color(_yr); _ye = _pct_emoji(_yr)
                        st.markdown(
                            f"<div style='color:{_yc}; font-weight:700; font-size:1.2rem; margin:6px 0;'>"
                            f"{_ye} {_yr:.1%} <span style='font-weight:500; font-size:1.05rem'>"
                            f"(목표 {format_won_abs(_up_yearly_target)} · 잔여 {format_won_abs(_yrem)})"
                            f"</span></div>", unsafe_allow_html=True)
                        if _up_this_year_events:
                            _evc = "#d32f2f" if _up_ty_event_amt < 0 else "#2e7d32" if _up_ty_event_amt > 0 else "#666"
                            _evd = f" ({_up_ty_event_desc})" if _up_ty_event_desc else ""
                            st.markdown(
                                f"<div style='color:{_evc}; font-size:0.9rem; margin:2px 0 6px 0;'>"
                                f"이번 년 이벤트 {_up_ty_event_amt:+,.0f}원{_evd}</div>",
                                unsafe_allow_html=True)
                        st.progress(max(min(_yr, 1.0), 0.0))
                    else:
                        st.caption("📆 연간 목표 미설정")
                st.markdown('<div class="up-divider"></div>', unsafe_allow_html=True)

            # ─── ① 총 수입/총 지출/잔액 ───
            st.markdown(f'<div class="up-section">📊 {selected_month} 요약</div>', unsafe_allow_html=True)
            _uc1, _uc2, _uc3, _uc4 = st.columns(4)
            with _uc1:
                st.markdown(f'<div class="metric-card income"><div class="metric-label">총 수입</div>'
                            f'<div class="metric-value">{format_won_abs(total_income)}</div></div>', unsafe_allow_html=True)
            with _uc2:
                st.markdown(f'<div class="metric-card expense"><div class="metric-label">총 지출</div>'
                            f'<div class="metric-value">{format_won_abs(total_expense)}</div></div>', unsafe_allow_html=True)
            with _uc3:
                _bcls = "balance" if balance >= 0 else "expense"
                st.markdown(f'<div class="metric-card {_bcls}"><div class="metric-label">잔액</div>'
                            f'<div class="metric-value">{format_won(balance)}</div></div>', unsafe_allow_html=True)
            with _uc4:
                st.markdown(f'<div class="metric-card saving"><div class="metric-label">고정 / 변동</div>'
                            f'<div class="metric-value" style="font-size:1.4rem">'
                            f'{format_won_abs(total_fixed)} / {format_won_abs(total_variable)}</div></div>',
                            unsafe_allow_html=True)
            st.markdown('<div class="up-divider"></div>', unsafe_allow_html=True)

            # ─── 🎯 예산 vs 실제 ───
            _up_month_goals = _up_goals.get(selected_month, {}) or {}
            _up_overall_goal = int(_up_month_goals.get("__total__", 0) or 0)
            _up_cat_goals_dict = {k: int(v) for k, v in _up_month_goals.items()
                                  if not k.startswith("__") and isinstance(v, (int, float)) and int(v) > 0}
            _up_hidden = set(_up_goals.get("__hidden_cats__", []) or [])
            _up_cat_goals_dict = {k: v for k, v in _up_cat_goals_dict.items() if k not in _up_hidden}
            _up_total_spent = abs(expense_df["실 사용"].sum()) if not expense_df.empty else 0

            if _up_overall_goal > 0 or _up_cat_goals_dict:
                st.markdown('<div class="up-section">🎯 예산 vs 실제</div>', unsafe_allow_html=True)
                if _up_overall_goal > 0:
                    _diff = _up_overall_goal - _up_total_spent
                    _pct = (_up_total_spent / _up_overall_goal * 100) if _up_overall_goal > 0 else 0
                    _diff_cls = "income" if _diff >= 0 else "expense"
                    _diff_lbl = f"절약 {format_won_abs(_diff)}" if _diff >= 0 else f"초과 {format_won_abs(-_diff)}"
                    _emj = "🎉" if _pct <= 80 else ("✅" if _pct <= 100 else ("⚠️" if _pct <= 120 else "🚨"))
                    _b1, _b2, _b3, _b4 = st.columns(4)
                    with _b1:
                        st.markdown(f'<div class="metric-card balance"><div class="metric-label">전체 예산</div>'
                                    f'<div class="metric-value">{format_won_abs(_up_overall_goal)}</div></div>',
                                    unsafe_allow_html=True)
                    with _b2:
                        st.markdown(f'<div class="metric-card expense"><div class="metric-label">실제 사용</div>'
                                    f'<div class="metric-value">{format_won_abs(_up_total_spent)}</div></div>',
                                    unsafe_allow_html=True)
                    with _b3:
                        st.markdown(f'<div class="metric-card {_diff_cls}"><div class="metric-label">{_emj} 차이</div>'
                                    f'<div class="metric-value">{_diff_lbl}</div></div>', unsafe_allow_html=True)
                    with _b4:
                        st.markdown(f'<div class="metric-card saving"><div class="metric-label">집행률</div>'
                                    f'<div class="metric-value">{_pct:.0f}%</div></div>', unsafe_allow_html=True)
                    st.markdown("")

                if _up_cat_goals_dict:
                    _cord = _up_goals.get("__cat_order__", []) or []
                    _ordered = [c for c in _cord if c in _up_cat_goals_dict]
                    _ordered += [c for c in sorted(_up_cat_goals_dict.keys()) if c not in _ordered]
                    _rows = []; _crows = []
                    for cat in _ordered:
                        g = _up_cat_goals_dict[cat]
                        s = abs(expense_df[expense_df["대분류"] == cat]["실 사용"].sum()) if not expense_df.empty else 0
                        diff = g - s
                        pct = (s / g * 100) if g > 0 else 0
                        stat = "🎉 여유" if pct <= 80 else ("✅ 적정" if pct <= 100 else ("⚠️ 주의" if pct <= 120 else "🚨 초과"))
                        diff_label = f"-{abs(diff):,.0f}원 (절약)" if diff >= 0 else f"+{abs(diff):,.0f}원 (초과)"
                        _rows.append({"카테고리": cat, "예산": f"{g:,.0f}원", "실제 사용": f"{s:,.0f}원",
                                      "차이": diff_label, "집행률": f"{pct:.0f}%", "상태": stat})
                        _crows.append({"카테고리": cat, "예산": g, "실제": s,
                                       "색상": "#38ef7d" if pct <= 100 else "#f45c43"})
                    st.markdown('<div class="up-subsection">📂 카테고리별 예산 vs 실제</div>', unsafe_allow_html=True)
                    _up_show_table(pd.DataFrame(_rows))
                    _cdf = pd.DataFrame(_crows)
                    _fig_bv = go.Figure()
                    _fig_bv.add_trace(go.Bar(name="예산", x=_cdf["카테고리"], y=_cdf["예산"],
                                             marker_color="rgba(180,180,180,0.5)",
                                             text=[f"{v:,.0f}원" for v in _cdf["예산"]],
                                             textposition="outside", textfont_size=12, cliponaxis=False))
                    _fig_bv.add_trace(go.Bar(name="실제", x=_cdf["카테고리"], y=_cdf["실제"],
                                             marker_color=_cdf["색상"],
                                             text=[f"{v:,.0f}원" for v in _cdf["실제"]],
                                             textposition="outside", textfont_size=12, cliponaxis=False))
                    _fig_bv.update_layout(barmode="group", height=420, margin=dict(l=10, r=10, t=40, b=10),
                                          xaxis_title="", yaxis_title="원",
                                          xaxis=dict(tickfont=dict(size=13)),
                                          yaxis=dict(tickfont=dict(size=12), tickformat=",.0f"),
                                          legend=dict(font=dict(size=13)))
                    st.plotly_chart(_fig_bv, use_container_width=True, key="up_budget_vs_actual")
                st.markdown('<div class="up-divider"></div>', unsafe_allow_html=True)

            # ─── ② 재산 내역 (지금 기준 대분류) ───
            st.markdown('<div class="up-section">💎 재산 내역 (지금 기준 대분류)</div>', unsafe_allow_html=True)
            _today_key_up = _up_now.strftime("%Y-%m")
            _asset_month_up = None
            if _today_key_up in _up_monthly_assets and _up_monthly_assets[_today_key_up]:
                _asset_month_up = _today_key_up
            elif _up_cands:
                _asset_month_up = _up_cands[-1]
            if _asset_month_up is None:
                st.info("재산 내역이 입력되지 않았습니다. (아래 '💎 재산 내역'에서 입력)")
            else:
                _adf = pd.DataFrame(_up_monthly_assets[_asset_month_up])
                _adf["amount"] = pd.to_numeric(_adf["amount"], errors="coerce").fillna(0)
                _by = _adf.groupby("category")["amount"].sum().reset_index()
                _by.columns = ["대분류", "금액"]
                _by = _by.sort_values("금액", ascending=False)
                _ta = _by["금액"].sum()
                _by["비중"] = (_by["금액"] / _ta * 100).round(1) if _ta > 0 else 0
                st.caption(f"기준 월: **{_asset_month_up}** · 총 자산 **{format_won_abs(_ta)}**")
                _al, _ar = st.columns([1, 1])
                with _al:
                    _disp_a = _by.copy()
                    _disp_a["금액"] = _disp_a["금액"].apply(lambda v: f"{v:,.0f}원")
                    _disp_a["비중"] = _disp_a["비중"].apply(lambda v: f"{v}%")
                    _up_show_table(_disp_a)
                with _ar:
                    if _ta > 0:
                        _fig_a = px.pie(_by, values="금액", names="대분류",
                                        color_discrete_sequence=px.colors.qualitative.Pastel, hole=0.35)
                        _fig_a.update_traces(textposition="inside", textinfo="label+percent", textfont_size=13)
                        _fig_a.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                                             legend=dict(font=dict(size=12)))
                        st.plotly_chart(_fig_a, use_container_width=True, key="up_assets_pie")

                # 소분류 상세 — 토글로 숨김
                with st.expander(f"📋 소분류 상세 보기 ({len(_adf)}건)", expanded=False):
                    _disp_sub = _adf.copy()
                    _disp_sub = _disp_sub.rename(columns={
                        "category": "대분류", "subcategory": "소분류", "amount": "금액"
                    })
                    # 대분류 → 금액 내림차순으로 정렬
                    _disp_sub = _disp_sub.sort_values(["대분류", "금액"], ascending=[True, False])
                    _disp_sub["금액"] = _disp_sub["금액"].apply(lambda v: f"{v:,.0f}원")
                    _up_show_table(_disp_sub[["대분류", "소분류", "금액"]])
            st.markdown('<div class="up-divider"></div>', unsafe_allow_html=True)

            # ─── ③ 수입 ───
            st.markdown('<div class="up-section">💰 수입 내역</div>', unsafe_allow_html=True)
            if income_df.empty:
                st.caption("이번 달 수입 내역이 없습니다.")
            else:
                # 전월 소분류별 수입 사전
                _up_prev_mk_inc = _prev_month_key(selected_month)
                _up_prev_inc_by_sub = {}
                if _up_prev_mk_inc:
                    _up_prev_inc_df = df[(df["월"] == _up_prev_mk_inc) & (df["구분"] == "수입")]
                    if not _up_prev_inc_df.empty:
                        _up_prev_inc_by_sub = _up_prev_inc_df.groupby("소분류")["순수입(부호)"].sum().to_dict()

                _is = income_df.groupby("소분류")["순수입(부호)"].sum().reset_index()
                _is.columns = ["소분류", "금액"]
                _is = _is.sort_values("금액", ascending=False)
                for _, r in _is.iterrows():
                    sub = r["소분류"]; amt = r["금액"]
                    items = income_df[income_df["소분류"] == sub]
                    _prev_a = _up_prev_inc_by_sub.get(sub, 0)
                    _delta_html = _delta_label_html(amt, _prev_a, expense=False)
                    _delta_part = f" &nbsp; {_delta_html}" if _delta_html else ""
                    st.markdown(
                        f'<div class="up-subsection">💰 {sub} — {format_won_abs(amt)} ({len(items)}건){_delta_part}</div>',
                        unsafe_allow_html=True)
                    d = items[["날짜", "이름", "순수입(부호)", "사용처"]].copy()
                    d.columns = ["날짜", "내용", "금액", "사용처"]
                    d["금액"] = d["금액"].apply(lambda x: f"{x:,.0f}원")
                    _up_show_table(d)
            st.markdown('<div class="up-divider"></div>', unsafe_allow_html=True)

            # ─── ④ 고정지출 ───
            st.markdown(f'<div class="up-section">🧾 고정지출 내역 — {format_won_abs(total_fixed)}</div>', unsafe_allow_html=True)
            if fixed_df.empty:
                st.caption("이번 달 고정지출 내역이 없습니다.")
            else:
                # 전월 소분류별 고정지출 사전
                _up_prev_mk_fix = _prev_month_key(selected_month)
                _up_prev_fix_by_sub = {}
                if _up_prev_mk_fix:
                    _up_prev_fix_df = df[(df["월"] == _up_prev_mk_fix) &
                                         (df["구분"] == "지출") &
                                         (df["대분류"].str.contains("고정지출", na=False))]
                    if not _up_prev_fix_df.empty:
                        _up_prev_fix_by_sub = _up_prev_fix_df.groupby("소분류")["실 사용"].sum().to_dict()

                _fs = fixed_df.groupby("소분류")["실 사용"].sum().reset_index()
                _fs.columns = ["소분류", "금액"]
                _fs = _fs.sort_values("금액", ascending=False)
                for _, r in _fs.iterrows():
                    sub = r["소분류"]; amt = r["금액"]
                    items = fixed_df[fixed_df["소분류"] == sub]
                    _prev_a = _up_prev_fix_by_sub.get(sub, 0)
                    _delta_html = _delta_label_html(amt, _prev_a, expense=True)
                    _delta_part = f" &nbsp; {_delta_html}" if _delta_html else ""
                    st.markdown(
                        f'<div class="up-subsection">🧾 {sub} — {format_won_abs(amt)} ({len(items)}건){_delta_part}</div>',
                        unsafe_allow_html=True)
                    d = items[["날짜", "이름", "실 사용", "결제 방법", "결제 여부"]].copy()
                    d.columns = ["날짜", "내용", "금액", "결제 방법", "결제 여부"]
                    d["금액"] = d["금액"].apply(lambda x: f"{x:,.0f}원")
                    _up_show_table(d)
            st.markdown('<div class="up-divider"></div>', unsafe_allow_html=True)

            # ─── ⑤ 변동지출 ───
            st.markdown(f'<div class="up-section">🔄 변동지출 내역 — {format_won_abs(total_variable)}</div>', unsafe_allow_html=True)
            if variable_df.empty:
                st.caption("이번 달 변동지출 내역이 없습니다.")
            else:
                # 전월 대분류별 지출 사전 (증감율 비교용)
                _up_prev_mk = _prev_month_key(selected_month)
                _up_prev_by_cat = {}
                if _up_prev_mk:
                    _up_prev_df = df[(df["월"] == _up_prev_mk) &
                                     (df["구분"] == "지출") &
                                     (~df["대분류"].str.contains("고정지출", na=False))]
                    if not _up_prev_df.empty:
                        _up_prev_by_cat = _up_prev_df.groupby("대분류")["실 사용"].sum().to_dict()

                _vm = variable_df.groupby("대분류")["실 사용"].sum().reset_index()
                _vm.columns = ["대분류", "금액"]
                _vm = _vm.sort_values("금액", ascending=False)
                for _, mrow in _vm.iterrows():
                    major = mrow["대분류"]; mamt = mrow["금액"]
                    mitems = variable_df[variable_df["대분류"] == major]
                    _prev_a = _up_prev_by_cat.get(major, 0)
                    _delta_html = _delta_label_html(mamt, _prev_a, expense=True)
                    _delta_part = f" &nbsp; {_delta_html}" if _delta_html else ""
                    st.markdown(
                        f'<div class="up-subsection">{major} — {format_won_abs(mamt)} ({len(mitems)}건){_delta_part}</div>',
                        unsafe_allow_html=True)
                    d = mitems[["날짜", "이름", "실 사용", "소분류", "사용처", "결제 방법", "결제 여부"]].copy()
                    d.columns = ["날짜", "내용", "금액", "소분류", "사용처", "결제 방법", "결제 여부"]
                    d["금액"] = d["금액"].apply(lambda x: f"{x:,.0f}원")
                    _up_show_table(d)
            st.markdown('<div class="up-divider"></div>', unsafe_allow_html=True)

            # ─── ⑥ 그래프 ───
            st.markdown('<div class="up-section">📈 그래프 — 어디에 얼마 썼나</div>', unsafe_allow_html=True)
            _ebm = expense_df.groupby("대분류")["실 사용"].sum().reset_index()
            _ebm.columns = ["대분류", "금액"]
            _ebm = _ebm.sort_values("금액", ascending=False)
            if _ebm.empty:
                st.caption("이번 달 지출 내역이 없습니다.")
            else:
                _g1, _g2 = st.columns(2)
                with _g1:
                    _fb = px.bar(_ebm.sort_values("금액"), x="금액", y="대분류", orientation="h",
                                 text="금액", color="대분류",
                                 color_discrete_sequence=px.colors.qualitative.Set2)
                    _fb.update_traces(
                        texttemplate=[_to_korean_won(v) for v in _ebm.sort_values("금액")["금액"]],
                        textposition="outside", textfont_size=18, cliponaxis=False)
                    _fb.update_layout(showlegend=False, height=460,
                                      margin=dict(l=10, r=140, t=10, b=10),
                                      xaxis_title="", yaxis_title="",
                                      xaxis=dict(tickfont=dict(size=15)),
                                      yaxis=dict(tickfont=dict(size=17)))
                    st.plotly_chart(_fb, use_container_width=True, key="up_expense_bar")
                with _g2:
                    _fp = px.pie(_ebm, values="금액", names="대분류",
                                 color_discrete_sequence=px.colors.qualitative.Set2, hole=0.3)
                    _fp.update_traces(textposition="inside", textinfo="label+percent", textfont_size=18)
                    _fp.update_layout(height=460, margin=dict(l=10, r=10, t=10, b=10),
                                      legend=dict(font=dict(size=15)))
                    st.plotly_chart(_fp, use_container_width=True, key="up_expense_pie")
            st.markdown('<div class="up-divider"></div>', unsafe_allow_html=True)

            # ─── ⑦ 회고 (빈 칸 생략) ───
            st.markdown(f'<div class="up-section">🪞 {selected_month} 회고</div>', unsafe_allow_html=True)
            _overall_review = [
                ("💰 정산", _up_memo.get("정산", "")),
                ("💬 피드백", _up_memo.get("피드백", "")),
                ("🔧 개선점", _up_memo.get("개선점", "")),
                ("✅ 지난 달 반영 내역", _up_memo.get("지난 달 반영 내역", "")),
            ]
            _overall_filled = [(t, v) for t, v in _overall_review if str(v).strip()]
            _goal_memo_up = _up_memo.get("목표 회고", {}) or {}
            _cat_filled = []
            for k, v in _goal_memo_up.items():
                if not str(v).strip():
                    continue
                _lbl = "전체" if k == "__total__" else k
                _cat_filled.append((_lbl, v))
            if not _overall_filled and not _cat_filled:
                st.info("아직 작성된 회고가 없습니다.")
            else:
                # 회고 메모 글자 크게
                _memo_style = ("font-size:1.25rem; line-height:1.7; padding:10px 14px; "
                               "background:#fafafa; border-left:4px solid #b3e5fc; "
                               "border-radius:4px; margin-bottom:14px; white-space:pre-wrap;")
                _memo_title_style = "font-size:1.35rem; font-weight:700; margin-top:14px; margin-bottom:6px;"
                if _overall_filled:
                    st.markdown('<div class="up-subsection">📝 종합 회고</div>', unsafe_allow_html=True)
                    for title, txt in _overall_filled:
                        st.markdown(f"<div style='{_memo_title_style}'>{title}</div>", unsafe_allow_html=True)
                        st.markdown(f"<div style='{_memo_style}'>{txt}</div>", unsafe_allow_html=True)
                if _cat_filled:
                    st.markdown('<div class="up-subsection">📂 카테고리별 회고</div>', unsafe_allow_html=True)
                    for label, txt in _cat_filled:
                        st.markdown(f"<div style='{_memo_title_style}'>📂 {label}</div>", unsafe_allow_html=True)
                        st.markdown(f"<div style='{_memo_style}'>{txt}</div>", unsafe_allow_html=True)
            st.markdown('<div class="up-divider"></div>', unsafe_allow_html=True)

            # ─── ⑧ 30년 자산 로드맵 ───
            st.markdown('<div class="up-section">🛤️ 30년 자산 로드맵</div>', unsafe_allow_html=True)
            _by_yr = int(_up_settings.get("birth_year", 1992))
            _sa = int(_up_settings.get("roadmap_start_asset", 0))
            _ann = int(_up_settings.get("annual_savings", 0))
            _drate = float(_up_settings.get("return_rate", 5.0))
            _years = int(_up_settings.get("roadmap_years", 30))
            if _sa <= 0 and _ann <= 0:
                st.info("로드맵 설정이 비어있습니다. 사이드바에서 시작 자산/연 저축액을 입력해주세요.")
            else:
                _rm = calc_roadmap(_by_yr, _sa, _ann, _drate, _up_events, _up_rate, years=_years)
                _rmdf = pd.DataFrame(_rm)
                st.caption(
                    f"출생연도 **{_by_yr}** · 시작 자산 **{format_won_abs(_sa)}** · "
                    f"연 저축 **{format_won_abs(_ann)}** · 기본 수익률 **{_drate}%** · {_years}년"
                )

                # 마일스톤
                _ms_colors = {1:"#e8f5e9", 2:"#c8e6c9", 3:"#a5d6a7", 5:"#81c784",
                              10:"#bbdefb", 20:"#90caf9", 30:"#c5cae9", 50:"#ffccbc", 100:"#fff9c4"}
                def _ms_get(row_data, prev_total):
                    cur = row_data["합계"]
                    for tgt in sorted(_ms_colors.keys(), reverse=True):
                        thr = tgt * 100_000_000
                        if cur >= thr and prev_total < thr:
                            return tgt
                    return None

                # 라인 그래프
                _figln = go.Figure()
                _figln.add_trace(go.Scatter(
                    x=_rmdf["년도"], y=_rmdf["합계"], mode="lines+markers",
                    name="연말 자산", line=dict(color="#667eea", width=3), marker=dict(size=7),
                    hovertemplate="<b>%{x}년 (%{customdata}세)</b><br>자산: %{y:,.0f}원<extra></extra>",
                    customdata=_rmdf["나이"],
                ))
                _ms_y, _ms_t, _ms_x, _ms_clr = [], [], [], []
                _pt = 0
                for _, _r in _rmdf.iterrows():
                    _m = _ms_get(_r, _pt)
                    if _m:
                        _ms_y.append(_r["년도"]); _ms_t.append(_r["합계"])
                        _ms_x.append(f"🏆 {_m}억 돌파!")
                        _ms_clr.append(_ms_colors.get(_m, "#667eea"))
                    _pt = _r["합계"]
                if _ms_y:
                    _figln.add_trace(go.Scatter(
                        x=_ms_y, y=_ms_t, mode="markers+text", name="목표 달성",
                        marker=dict(size=22, color=_ms_clr, symbol="star",
                                    line=dict(width=2, color="#333")),
                        text=_ms_x, textposition="top center", textfont=dict(size=16, color="#333"),
                    ))
                _evdf_up = _rmdf[_rmdf["이벤트"] != ""]
                if not _evdf_up.empty:
                    _figln.add_trace(go.Scatter(
                        x=_evdf_up["년도"], y=_evdf_up["합계"], mode="markers+text",
                        name="이벤트", marker=dict(size=16, color="#f45c43", symbol="diamond"),
                        text=_evdf_up["이벤트"], textposition="bottom center", textfont=dict(size=15),
                    ))
                _mn = _rmdf["합계"].min(); _mx = _rmdf["합계"].max()
                for _tgt in sorted(_ms_colors.keys()):
                    _thr = _tgt * 100_000_000
                    if _mn * 0.8 <= _thr <= _mx * 1.2:
                        _figln.add_hline(y=_thr, line_dash="dash", line_color="rgba(0,0,0,0.15)",
                                         annotation_text=f"{_tgt}억", annotation_position="right",
                                         annotation_font_size=14)
                _figln.update_layout(
                    height=580, margin=dict(l=10, r=60, t=30, b=20),
                    xaxis_title="년도", yaxis_title="자산 (원)",
                    xaxis=dict(title_font_size=15, tickfont=dict(size=15)),
                    yaxis=dict(title_font_size=15, tickformat=",", tickfont=dict(size=14)),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=15)),
                )
                st.plotly_chart(_figln, use_container_width=True, key="up_roadmap_line")

                # 검증
                if len(_rmdf) != _years:
                    st.warning(f"⚠️ 예상 {_years}년치인데 {len(_rmdf)}행만 생성됨 — 데이터 확인 필요")
                else:
                    st.caption(f"✅ {_years}년치 모두 표시 (1년차 ~ {_years}년차)")

                # 표 — 마일스톤 행 강조 (HTML)
                _td = "padding:14px 16px; border-bottom:1px solid #eee; white-space:nowrap; text-align:center; font-size:1.2rem;"
                _th = "padding:16px 16px; border-bottom:2px solid #ddd; text-align:center; white-space:nowrap; font-size:1.2rem; font-weight:bold;"
                _thtml = '<div style="overflow-x:auto;"><table style="width:100%; border-collapse:collapse;">'
                _thtml += '<thead><tr style="background:#f0f2f6;">'
                for _col in ["회차", "년도", "나이", "보유 자산", "저축액", "수익률", "이벤트", "이벤트 금액", "합계"]:
                    _thtml += f'<th style="{_th}">{_col}</th>'
                _thtml += '</tr></thead><tbody>'
                _ptot = 0
                for _i, _row in _rmdf.iterrows():
                    _m = _ms_get(_row, _ptot)
                    _bg = _ms_colors.get(_m, "transparent") if _m else "transparent"
                    _fw = "font-weight:bold;" if _m else ""
                    _badge = f' 🏆 {_m}억 돌파!' if _m else ""
                    _et = _row["이벤트"] if _row["이벤트"] else "-"
                    _ea = f'{_row["이벤트 금액"]:+,.0f}원' if _row["이벤트 금액"] != 0 else "-"
                    _ec = "#d32f2f" if _row["이벤트 금액"] < 0 else "#2e7d32" if _row["이벤트 금액"] > 0 else ""
                    _thtml += f'<tr style="background-color:{_bg};{_fw}">'
                    _thtml += f'<td style="{_td}">{_i+1}년차</td>'
                    _thtml += f'<td style="{_td}">{_row["년도"]}</td>'
                    _thtml += f'<td style="{_td}">{_row["나이"]}세</td>'
                    _thtml += f'<td style="{_td}">{_row["보유 자산"]:,.0f}원</td>'
                    _thtml += f'<td style="{_td}">{_row["저축액"]:,.0f}원</td>'
                    _thtml += f'<td style="{_td}">{_row["수익률"]}%</td>'
                    _thtml += f'<td style="{_td}">{_et}</td>'
                    _thtml += f'<td style="{_td} color:{_ec};">{_ea}</td>'
                    _thtml += f'<td style="{_td}">{_row["합계"]:,.0f}원{_badge}</td>'
                    _thtml += '</tr>'
                    _ptot = _row["합계"]
                _thtml += '</tbody></table></div>'
                st.markdown(_thtml, unsafe_allow_html=True)

                # 30년 로드맵 회고 메모 (읽기 전용 — 메인 앱에서 입력)
                # 최신 파일 직접 다시 로드 (탭 렌더 시점과 저장 사이 동기화)
                _, _, _up_settings_now = load_roadmap_config()
                _up_rm_memo = str(_up_settings_now.get("roadmap_memo", "") or "").strip()
                st.markdown('<div class="up-subsection" style="margin-top:24px;">🪞 30년 로드맵 회고</div>',
                            unsafe_allow_html=True)
                if _up_rm_memo:
                    st.markdown(
                        f"<div style='font-size:1.25rem; line-height:1.7; padding:14px 18px; "
                        f"background:#fafafa; border-left:4px solid #c5cae9; border-radius:4px; "
                        f"white-space:pre-wrap;'>{_up_rm_memo}</div>",
                        unsafe_allow_html=True
                    )
                else:
                    st.caption("💡 메인 앱 30년 로드맵 차트 아래 '🪞 30년 로드맵 회고' 입력란에 작성·저장하면 여기에 표시됩니다.")
            st.markdown('<div class="up-divider"></div>', unsafe_allow_html=True)
            st.caption("👆 이 화면을 그대로 인쇄(Ctrl+P)하면 PDF로 한 장 요약 저장됩니다.")

        # ─── 하단: 미결제 내역 ───
        st.markdown("")
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown("")

        if not unpaid_df.empty:
            st.markdown(f"### ⚠️ 미결제 내역 — {unpaid_count}건, {format_won_abs(unpaid_amount)}")
            unpaid_by_cat = unpaid_df.groupby("대분류")["실 사용"].sum().reset_index()
            unpaid_by_cat.columns = ["대분류", "금액"]
            unpaid_by_cat = unpaid_by_cat.sort_values("금액", ascending=False)
            for _, urow in unpaid_by_cat.iterrows():
                cat_name = urow["대분류"]
                cat_amount = urow["금액"]
                cat_items = unpaid_df[unpaid_df["대분류"] == cat_name]
                with st.expander(f"🟡 {cat_name} — {format_won_abs(cat_amount)} ({len(cat_items)}건)", expanded=True):
                    for row_idx, (_, item_row) in enumerate(cat_items.iterrows()):
                        col_check, col_date, col_name, col_amt, col_method, col_sub = st.columns([0.5, 1.2, 2, 1.2, 1, 1])
                        item_key = f"pay_{cat_name}_{row_idx}_{item_row['이름']}"
                        with col_check:
                            if st.checkbox("✅", key=item_key, label_visibility="collapsed"):
                                # 결제완료 처리
                                new_paid = {
                                    "날짜": str(item_row["날짜"]),
                                    "이름": item_row["이름"],
                                    "금액": float(item_row["순수입(부호)"])
                                }
                                paid_items.append(new_paid)
                                save_payment_status({"paid_items": paid_items})
                                st.rerun()
                        with col_date:
                            st.markdown(f"<small>{item_row['날짜']}</small>", unsafe_allow_html=True)
                        with col_name:
                            st.markdown(f"**{item_row['이름']}**")
                        with col_amt:
                            st.markdown(f"{item_row['실 사용']:,.0f}원")
                        with col_method:
                            st.markdown(f"<small>{item_row.get('결제 방법', '')}</small>", unsafe_allow_html=True)
                        with col_sub:
                            st.markdown(f"<small>{item_row['소분류']}</small>", unsafe_allow_html=True)

# ─── 재산 내역 (항상 표시) ───
st.markdown("")
st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
st.markdown("")
st.markdown("### 💎 재산 내역")
st.caption("월별 자산 현황 (대분류 / 소분류 / 금액). 가장 최근 월의 총합이 '장기 로드맵 시작 보유 자산'에 자동 반영됩니다.")

# 데이터 로드
_assets_detail = load_assets_detail()
_monthly = _assets_detail.get("monthly", {})

# 사용 가능한 월 목록 (없으면 2026-04부터 시작)
_existing_months = sorted(_monthly.keys())
if not _existing_months:
    _existing_months = ["2026-04"]
    _monthly["2026-04"] = []

# 월 선택 + 새 월 추가 버튼
asset_col_sel, asset_col_add = st.columns([3, 1])
with asset_col_sel:
    # 오늘(한국 시간)의 'YYYY-MM' — 목록에 없으면 가장 최근 월
    try:
        from zoneinfo import ZoneInfo
        _today_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    except Exception:
        _today_kst = datetime.now()
    _today_key = f"{_today_kst.year:04d}-{_today_kst.month:02d}"
    if _today_key in _existing_months:
        _default_idx = _existing_months.index(_today_key)
    else:
        _default_idx = len(_existing_months) - 1
    selected_month = st.selectbox(
        "기준 월",
        options=_existing_months,
        index=_default_idx,
        key="assets_month_select",
    )
with asset_col_add:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("➕ 새 월 추가", use_container_width=True, help="가장 최근 월의 다음 달을 만들고 항목을 자동 복사"):
        latest = _existing_months[-1]
        new_key = next_month_key(latest)
        if new_key in _monthly:
            st.warning(f"{new_key}는 이미 존재합니다")
        else:
            # 직전 월 행을 deepcopy
            import copy
            _monthly[new_key] = copy.deepcopy(_monthly.get(latest, []))
            _assets_detail["monthly"] = _monthly
            save_assets_detail(_assets_detail)
            sync_start_asset_from_detail()
            st.rerun()

# 직전 월 복사 버튼 — 현재 선택 월이 첫 월이 아닐 때만 노출
_sel_idx = _existing_months.index(selected_month)
if _sel_idx > 0:
    _prev_month = _existing_months[_sel_idx - 1]
    _prev_count = len(_monthly.get(_prev_month, []))
    if st.button(
        f"📥 {_prev_month} 내역을 {selected_month}에 복사 (덮어쓰기)",
        use_container_width=True,
        help=f"{_prev_month}의 {_prev_count}개 항목을 그대로 가져옵니다. 현재 {selected_month}에 입력된 내용은 사라집니다.",
        key=f"copy_prev_{selected_month}",
    ):
        import copy
        _monthly[selected_month] = copy.deepcopy(_monthly.get(_prev_month, []))
        _assets_detail["monthly"] = _monthly
        save_assets_detail(_assets_detail)
        sync_start_asset_from_detail()
        st.success(f"📥 {_prev_month} → {selected_month} 복사 완료 ({_prev_count}개 항목)")
        st.rerun()

# 현재 선택 월의 데이터를 DataFrame으로
_rows = _monthly.get(selected_month, [])
if _rows:
    _df_assets = pd.DataFrame(_rows)
    # 컬럼 순서/이름 보정
    for col in ["category", "subcategory", "amount"]:
        if col not in _df_assets.columns:
            _df_assets[col] = "" if col != "amount" else 0
    _df_assets = _df_assets[["category", "subcategory", "amount"]]
else:
    _df_assets = pd.DataFrame(columns=["category", "subcategory", "amount"])

# 한국어 컬럼명으로 표시
_df_assets_display = _df_assets.rename(columns={
    "category": "대분류", "subcategory": "소분류", "amount": "금액"
})

# data_editor — 행 추가/수정/삭제 가능 (소분류 상세 편집은 토글로 숨김)
with st.expander(f"📋 소분류 상세 편집 / 추가 ({len(_df_assets_display)}건)", expanded=False):
    edited_df = st.data_editor(
        _df_assets_display,
        num_rows="dynamic",
        use_container_width=True,
        key=f"assets_editor_{selected_month}",
        column_config={
            "대분류": st.column_config.TextColumn("대분류", help="예: 투자금, 현금, 부동산", required=False),
            "소분류": st.column_config.TextColumn("소분류", help="예: A 펀드, 주거래 통장", required=False),
            "금액": st.column_config.NumberColumn(
                "금액 (원)",
                help="숫자만 입력 — 쉼표는 자동으로 표시됩니다",
                format="localized",
                min_value=0,
                step=1_000_000,
            ),
        },
    )

    # 저장 버튼
    asset_save_col, asset_del_col = st.columns([1, 1])
    with asset_save_col:
        if st.button("💾 저장", type="primary", use_container_width=True, key="assets_save_btn"):
            # 빈 행 제외, 정수 변환
            new_rows = []
            for _, r in edited_df.iterrows():
                cat = str(r.get("대분류", "") or "").strip()
                sub = str(r.get("소분류", "") or "").strip()
                amt_raw = r.get("금액", 0)
                try:
                    amt = int(amt_raw) if pd.notna(amt_raw) else 0
                except (TypeError, ValueError):
                    amt = 0
                # 모두 비어있는 행은 제외
                if not cat and not sub and amt == 0:
                    continue
                new_rows.append({"category": cat, "subcategory": sub, "amount": amt})
            _monthly[selected_month] = new_rows
            _assets_detail["monthly"] = _monthly
            save_assets_detail(_assets_detail)
            synced = sync_start_asset_from_detail()
            st.success(f"💾 저장 완료 — 시작 보유 자산: {synced:,}원" if synced is not None else "💾 저장 완료")
            st.rerun()

    with asset_del_col:
        if st.button("🗑️ 이 월 삭제", use_container_width=True, key="assets_del_btn",
                     help=f"{selected_month}의 모든 데이터 삭제"):
            if selected_month in _monthly:
                del _monthly[selected_month]
                _assets_detail["monthly"] = _monthly
                save_assets_detail(_assets_detail)
                sync_start_asset_from_detail()
                st.rerun()

# 합계 표시 (현재 선택 월 기준, 편집 중인 값 반영)
st.markdown("")
_summary_rows = []
_summary_total = 0
if not edited_df.empty:
    # 대분류별 합계
    _temp = edited_df.copy()
    _temp["금액"] = pd.to_numeric(_temp["금액"], errors="coerce").fillna(0).astype(int)
    _temp["대분류"] = _temp["대분류"].fillna("").astype(str).str.strip()
    _temp = _temp[_temp["대분류"] != ""]
    if not _temp.empty:
        _grouped = _temp.groupby("대분류")["금액"].sum().reset_index()
        for _, row in _grouped.iterrows():
            _summary_rows.append((row["대분류"], int(row["금액"])))
        _summary_total = int(_temp["금액"].sum())

if _summary_rows:
    _table_html = """
    <style>
      .assets-summary { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
      .assets-summary th, .assets-summary td { padding: 0.5rem 0.8rem; border-bottom: 1px solid #e0e0e0; }
      .assets-summary th { text-align: left; background: #f5f5f5; }
      .assets-summary td.num { text-align: right; font-variant-numeric: tabular-nums; }
      .assets-summary tr.total td { font-weight: 700; background: #fff8e1; border-top: 2px solid #f9a825; }
    </style>
    <table class="assets-summary">
      <thead><tr><th>대분류</th><th style="text-align:right">합계</th></tr></thead>
      <tbody>
    """
    for cat, amt in _summary_rows:
        _table_html += f'<tr><td>{cat}</td><td class="num">{amt:,}원</td></tr>'
    _table_html += f'<tr class="total"><td>총합계</td><td class="num">{_summary_total:,}원</td></tr>'
    _table_html += "</tbody></table>"
    st.markdown(_table_html, unsafe_allow_html=True)
    st.caption(f"※ 저장 시 위 총합계({_summary_total:,}원)가 시작 보유 자산에 반영됩니다")
else:
    st.info("아직 입력된 항목이 없습니다. 위 표에 행을 추가하고 💾 저장을 눌러 주세요.")

# ─── 재산 추이 전체 보기 ───
st.markdown("")
with st.expander("📈 전체 보기 (재산 추이 + 월별 상세)", expanded=False):
    _all_months = sorted([m for m, rows in _monthly.items() if rows])
    if not _all_months:
        st.info("저장된 월 데이터가 없습니다. 표에 행을 추가하고 💾 저장을 눌러 주세요.")
    else:
        # 월별 합계 시계열 + 대분류별 누적
        _trend_rows = []  # 총합계 시계열
        _stack_rows = []  # 대분류별 누적
        for mk in _all_months:
            rows = _monthly[mk]
            month_total = sum(int(r.get("amount", 0) or 0) for r in rows)
            _trend_rows.append({"월": mk, "총합계": month_total})
            # 대분류 합계
            cat_sum = {}
            for r in rows:
                cat = (r.get("category") or "").strip() or "(미분류)"
                cat_sum[cat] = cat_sum.get(cat, 0) + int(r.get("amount", 0) or 0)
            for cat, amt in cat_sum.items():
                _stack_rows.append({"월": mk, "대분류": cat, "금액": amt})

        _trend_df = pd.DataFrame(_trend_rows)
        _stack_df = pd.DataFrame(_stack_rows)

        # 'YYYY-MM' → 'YYYY년 M월' 한글 라벨
        def _month_label(mk):
            y, m = mk.split("-")
            return f"{y}년 {int(m)}월"
        _trend_df["월라벨"] = _trend_df["월"].apply(_month_label)

        # 큰 단위(억/만) 라벨 헬퍼
        def _won_short(v):
            v = int(v)
            if v == 0:
                return "0"
            sign = "-" if v < 0 else ""
            v = abs(v)
            eok = v // 100_000_000
            man = (v % 100_000_000) // 10_000
            if eok and man:
                return f"{sign}{eok}억 {man:,}만"
            if eok:
                return f"{sign}{eok}억"
            if man:
                return f"{sign}{man:,}만"
            return f"{sign}{v:,}"

        # Y축 틱: 5천만 단위 그리드 (최대값에 따라 자동)
        def _y_ticks(max_val):
            if max_val <= 0:
                return [0, 50_000_000], ["0", "5천만"]
            step = 50_000_000  # 5천만 기본
            if max_val > 1_000_000_000:
                step = 200_000_000  # 2억
            elif max_val > 500_000_000:
                step = 100_000_000  # 1억
            top = ((int(max_val) // step) + 1) * step
            vals = list(range(0, top + 1, step))
            labels = [_won_short(v) for v in vals]
            return vals, labels

        # 1) 총자산 추이 (라인)
        st.markdown("#### 💰 총자산 추이")
        _max_total = int(_trend_df["총합계"].max() or 0)
        _yt_vals, _yt_labels = _y_ticks(_max_total)
        fig_line = px.line(
            _trend_df, x="월라벨", y="총합계",
            markers=True, text=_trend_df["총합계"].apply(_won_short),
        )
        fig_line.update_traces(
            textposition="top center",
            line=dict(color="#4facfe", width=3),
            marker=dict(size=10, color="#00f2fe"),
            hovertemplate="%{x}<br>%{y:,}원<extra></extra>",
        )
        fig_line.update_layout(
            height=380, margin=dict(l=20, r=20, t=30, b=20),
            yaxis=dict(
                tickmode="array", tickvals=_yt_vals, ticktext=_yt_labels,
                title="", gridcolor="#eaeaea",
            ),
            xaxis=dict(title="", type="category"),
        )
        st.plotly_chart(fig_line, use_container_width=True)

        # 전월 대비 변동
        if len(_trend_df) >= 2:
            _trend_df["전월대비"] = _trend_df["총합계"].diff()
            _delta_df = _trend_df.dropna(subset=["전월대비"]).copy()
            _delta_df["변동"] = _delta_df["전월대비"].apply(
                lambda v: f"🟢 +{int(v):,}원" if v > 0 else (f"🔴 {int(v):,}원" if v < 0 else "—")
            )
            _delta_show = _delta_df[["월", "총합계", "변동"]].copy()
            _delta_show["총합계"] = _delta_show["총합계"].apply(lambda v: f"{int(v):,}원")
            st.markdown("#### 📊 월별 변동")
            st.dataframe(_delta_show, use_container_width=True, hide_index=True)

        # 2) 월별 상세 내역 (피벗 — 행=대분류·소분류, 열=월)
        st.markdown("#### 📋 월별 상세 내역")
        _detail_rows = []
        for mk in _all_months:
            for r in _monthly[mk]:
                _detail_rows.append({
                    "월": mk,
                    "대분류": (r.get("category") or "").strip() or "(미분류)",
                    "소분류": (r.get("subcategory") or "").strip() or "(미지정)",
                    "금액": int(r.get("amount", 0) or 0),
                })
        _detail_df_full = pd.DataFrame(_detail_rows)
        # 피벗
        _pivot = _detail_df_full.pivot_table(
            index=["대분류", "소분류"], columns="월", values="금액",
            aggfunc="sum", fill_value=0,
        )
        # NaN 방지 — fill_value=0이지만 dtype 충돌 가능
        _pivot = _pivot.fillna(0).astype(int)
        # 합계 행 — 컬럼별 sum을 명시적으로 계산해 새 DataFrame으로 concat
        _totals = {c: int(_pivot[c].sum()) for c in _pivot.columns}
        _total_row = pd.DataFrame(
            [_totals],
            index=pd.MultiIndex.from_tuples([("총합계", "")], names=_pivot.index.names),
        )
        _pivot_with_total = pd.concat([_pivot, _total_row])
        # 모든 셀 쉼표 포맷
        def _fmt_cell(v):
            try:
                iv = int(v) if pd.notna(v) else 0
            except (TypeError, ValueError):
                iv = 0
            return f"{iv:,}" if iv else "0"
        _pivot_fmt = _pivot_with_total.applymap(_fmt_cell)
        st.dataframe(_pivot_fmt, use_container_width=True)

# ─── 장기 로드맵 (항상 표시) ───
st.markdown("")
st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
st.markdown("")
st.markdown("### 🗺️ 장기 자산 로드맵")

current_year = datetime.now().year
current_age = current_year - birth_year + 1  # 한국 나이
st.caption(f"📌 {birth_year}년생 · 현재 {current_age}세 · {current_year}년 기준")

# 이벤트 & 수익률 변경 관리
events, rate_changes, roadmap_settings = load_roadmap_config()

with st.expander("📌 주요 이벤트 추가/관리 (자동차, 집, 결혼 등)", expanded=False):
    with st.form("event_form", clear_on_submit=True):
        ev_row1_col1, ev_row1_col2, ev_row1_col3 = st.columns([1.5, 1.5, 3])
        with ev_row1_col1:
            new_ev_year = st.number_input("년도", min_value=current_year, max_value=current_year + 50,
                                           value=current_year + 1, step=1)
        with ev_row1_col2:
            new_ev_type = st.radio("구분", ["🔴 지출", "🟢 수입"], horizontal=True)
        with ev_row1_col3:
            new_ev_desc = st.text_input("설명", placeholder="예: 집 매매, 자동차 구매, 결혼")

        ev_row2_col1, ev_row2_col2 = st.columns([3, 1])
        with ev_row2_col1:
            new_ev_amount_text = st.text_input(
                "금액 (원)", value="0", help="쉼표 입력 가능 (예: 50,000,000)"
            )
        with ev_row2_col2:
            st.markdown("<br>", unsafe_allow_html=True)
            submitted = st.form_submit_button("➕ 추가", use_container_width=True)

        if submitted:
            new_ev_amount = parse_won(new_ev_amount_text)
            if new_ev_amount is None or new_ev_amount < 0:
                st.warning("금액은 숫자(쉼표 OK)로 0 이상 입력해 주세요")
            elif new_ev_desc and new_ev_amount > 0:
                final_amount = -new_ev_amount if "지출" in new_ev_type else new_ev_amount
                events.append({"year": int(new_ev_year), "desc": new_ev_desc, "amount": int(final_amount)})
                save_roadmap_config(events, rate_changes)
                st.rerun()
            else:
                st.warning("설명과 금액을 모두 입력해주세요 (금액은 0보다 커야 합니다)")

    # 등록된 이벤트 목록
    if events:
        st.markdown("**등록된 이벤트:**")
        sorted_events = sorted(events, key=lambda e: e["year"])
        for idx, ev in enumerate(sorted_events):
            ev_age = ev["year"] - birth_year + 1
            sign = "🟢" if ev["amount"] > 0 else "🔴"
            ec1, ec2 = st.columns([5, 1])
            with ec1:
                st.markdown(f"{sign} **{ev['year']}년** ({ev_age}세) — {ev['desc']}: **{ev['amount']:+,.0f}원**")
            with ec2:
                if st.button("🗑️", key=f"del_ev_{idx}", help="삭제"):
                    original_idx = events.index(ev)
                    events.pop(original_idx)
                    save_roadmap_config(events, rate_changes)
                    st.rerun()
    else:
        st.info("등록된 이벤트가 없습니다. 위에서 추가해주세요.")

st.markdown("")
with st.expander("📊 수익률 변경 구간 관리", expanded=False):
    st.caption(f"기본 수익률: **{return_rate}%** (사이드바에서 설정) — 특정 기간만 다른 수익률을 적용할 수 있습니다")

    # 수익률 변경 추가 폼
    with st.form("rate_form", clear_on_submit=True):
        rc_col1, rc_col2, rc_col3, rc_col4 = st.columns([1.5, 1.5, 1.5, 1])
        with rc_col1:
            new_rc_start = st.number_input("시작 년도", min_value=current_year, max_value=current_year + 50,
                                            value=current_year + 5, step=1)
        with rc_col2:
            new_rc_end = st.number_input("종료 년도", min_value=current_year, max_value=current_year + 50,
                                          value=current_year + 10, step=1)
        with rc_col3:
            new_rc_rate = st.number_input("수익률 (%)", min_value=0.0, max_value=50.0, value=10.0, step=0.5)
        with rc_col4:
            st.markdown("<br>", unsafe_allow_html=True)
            rc_submitted = st.form_submit_button("➕ 추가", use_container_width=True)
        if rc_submitted:
            if new_rc_end < new_rc_start:
                st.warning("종료 년도가 시작 년도보다 빠릅니다")
            else:
                rate_changes.append({"year_start": int(new_rc_start), "year_end": int(new_rc_end), "rate": float(new_rc_rate)})
                save_roadmap_config(events, rate_changes)
                st.rerun()

    # 등록된 수익률 변경 목록
    if rate_changes:
        st.markdown("**수익률 변경 구간:**")
        sorted_rc = sorted(rate_changes, key=lambda r: r.get("year_start", r.get("year", 0)))
        for idx, rc in enumerate(sorted_rc):
            rc_start = rc.get("year_start", rc.get("year", 0))
            rc_end = rc.get("year_end", "~")
            rc_age_s = rc_start - birth_year + 1
            rc_age_e = rc_end - birth_year + 1 if isinstance(rc_end, int) else "~"
            rc1, rc2 = st.columns([5, 1])
            with rc1:
                st.markdown(f"📈 **{rc_start}년**({rc_age_s}세) → **{rc_end}년**({rc_age_e}세) : **{rc['rate']}%**")
            with rc2:
                if st.button("🗑️", key=f"del_rc_{idx}", help="삭제"):
                    original_idx = rate_changes.index(rc)
                    rate_changes.pop(original_idx)
                    save_roadmap_config(events, rate_changes)
                    st.rerun()
    else:
        st.info(f"변경 없음 — 전 구간 {return_rate}% 적용")

# 로드맵 계산
roadmap_rows = calc_roadmap(birth_year, roadmap_start_asset, annual_savings, return_rate, events, rate_changes, roadmap_years)

# 마일스톤 자동 감지
milestones = {}
for row in roadmap_rows:
    total_billions = row["합계"] / 100_000_000  # 1억 단위
    for target in [1, 2, 3, 5, 10, 20, 30, 50, 100]:
        if target not in milestones and total_billions >= target:
            milestones[target] = row

# 마일스톤 카드
if milestones:
    st.markdown("#### 🏆 목표 달성 예상")
    ms_display = min(len(milestones), 9)
    ms_cols = st.columns(ms_display)
    for i, (target, row) in enumerate(sorted(milestones.items())):
        if i < ms_display:
            with ms_cols[i]:
                st.markdown(f"""
                <div class="metric-card" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 1.5rem 1rem;">
                    <div class="metric-label" style="font-size:1.05rem;">{target}억 달성</div>
                    <div class="metric-value" style="font-size:2.2rem;">{row['년도']}년</div>
                    <div class="metric-label" style="font-size:1.05rem;">{row['나이']}세</div>
                </div>
                """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# 구간 선택
section_size = 10
section_options = []
section_ranges = []  # (start, end) 인덱스 저장
for sec_idx in range(0, roadmap_years, section_size):
    sec_end = min(sec_idx + section_size, roadmap_years)
    sec_rows_tmp = roadmap_rows[sec_idx:sec_end]
    s_year, e_year = sec_rows_tmp[0]["년도"], sec_rows_tmp[-1]["년도"]
    s_age, e_age = sec_rows_tmp[0]["나이"], sec_rows_tmp[-1]["나이"]
    section_names_map = {0: "단기", 1: "중기", 2: "장기", 3: "초장기", 4: "극장기"}
    label = section_names_map.get(sec_idx // section_size, f"{sec_idx+1}~{sec_end}년차")
    section_options.append(f"📅 {label} ({s_year}→{e_year}년 / {s_age}→{e_age}세)")
    section_ranges.append((sec_idx, sec_end))

# "전체" 옵션 추가
all_s_year, all_e_year = roadmap_rows[0]["년도"], roadmap_rows[-1]["년도"]
all_s_age, all_e_age = roadmap_rows[0]["나이"], roadmap_rows[-1]["나이"]
section_options.append(f"📅 전체 ({all_s_year}→{all_e_year}년 / {all_s_age}→{all_e_age}세)")
section_ranges.append((0, roadmap_years))

selected_section = st.radio("구간 선택", section_options, horizontal=True, key="roadmap_section")
sec_index = section_options.index(selected_section)

# 선택된 구간 데이터
sec_start, sec_end = section_ranges[sec_index]
sec_rows = roadmap_rows[sec_start:sec_end]

# 억 단위 돌파 행 색상 매핑
milestone_colors = {
    1: "#e8f5e9",   # 1억
    2: "#c8e6c9",   # 2억
    3: "#a5d6a7",   # 3억
    5: "#81c784",   # 5억
    10: "#bbdefb",  # 10억
    20: "#90caf9",  # 20억
    30: "#c5cae9",  # 30억
    50: "#ffccbc",  # 50억
    100: "#fff9c4", # 100억
}

# 각 행이 돌파한 억 단위 체크
def get_row_milestone(row_data, prev_total):
    """이전 합계 → 현재 합계 사이에 돌파한 억 단위 반환"""
    cur = row_data["합계"]
    for target in sorted(milestone_colors.keys(), reverse=True):
        threshold = target * 100_000_000  # 1억 = 100,000,000
        if cur >= threshold and prev_total < threshold:
            return target
    return None

# 테이블 HTML 직접 생성 (행별 색상 적용)
st.markdown("")
header_cols = ["년도", "나이", "보유 자산", "저축액", "수익률", "이벤트", "이벤트 금액", "합계"]
td_base = "padding:10px 14px; border-bottom:1px solid #eee; white-space:nowrap; text-align:center;"

table_html = '<div style="overflow-x:auto;">'
table_html += '<table style="width:100%; border-collapse:collapse; font-size:1rem; margin:0 auto;">'
table_html += '<thead><tr style="background:#f0f2f6; font-weight:bold;">'
for col in header_cols:
    table_html += f'<th style="padding:12px 14px; border-bottom:2px solid #ddd; text-align:center; white-space:nowrap; font-size:1rem;">{col}</th>'
table_html += '</tr></thead><tbody>'

for i, row in enumerate(sec_rows):
    global_idx = sec_start + i
    prev_total = roadmap_rows[global_idx - 1]["합계"] if global_idx > 0 else 0
    ms = get_row_milestone(row, prev_total)

    bg_color = milestone_colors.get(ms, "transparent") if ms else "transparent"
    row_style = f'background-color:{bg_color};'
    fw = "font-weight:bold;" if ms else ""
    ms_badge = f' 🏆 {ms}억 돌파!' if ms else ""

    ev_text = row["이벤트"] if row["이벤트"] else ""
    ev_amount = f'{row["이벤트 금액"]:+,.0f}' if row["이벤트 금액"] != 0 else ""
    ev_color = "#d32f2f" if row["이벤트 금액"] < 0 else "#2e7d32" if row["이벤트 금액"] > 0 else ""

    table_html += f'<tr style="{row_style}{fw}">'
    table_html += f'<td style="{td_base}">{row["년도"]}</td>'
    table_html += f'<td style="{td_base}">{row["나이"]}세</td>'
    table_html += f'<td style="{td_base}">{row["보유 자산"]:,.0f}</td>'
    table_html += f'<td style="{td_base}">{row["저축액"]:,.0f}</td>'
    table_html += f'<td style="{td_base}">{row["수익률"]}%</td>'
    table_html += f'<td style="{td_base}">{ev_text}</td>'
    table_html += f'<td style="{td_base} color:{ev_color};">{ev_amount}</td>'
    table_html += f'<td style="{td_base}">{row["합계"]:,.0f}{ms_badge}</td>'
    table_html += '</tr>'

table_html += '</tbody></table></div>'
st.markdown(table_html, unsafe_allow_html=True)

# 선택 구간 그래프
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("#### 📈 자산 성장 추이")
chart_df = pd.DataFrame(sec_rows)

fig_roadmap = go.Figure()

# 자산 라인
fig_roadmap.add_trace(go.Scatter(
    x=chart_df["년도"],
    y=chart_df["합계"],
    mode="lines+markers",
    name="총 자산",
    line=dict(color="#667eea", width=3),
    hovertemplate="<b>%{x}년 (%{customdata}세)</b><br>자산: %{y:,.0f}원<extra></extra>",
    customdata=chart_df["나이"],
))

# 마일스톤 마커
ms_years, ms_totals, ms_texts, ms_colors_list = [], [], [], []
prev_t = roadmap_rows[sec_start - 1]["합계"] if sec_start > 0 else 0
for row in sec_rows:
    ms = get_row_milestone(row, prev_t)
    if ms:
        ms_years.append(row["년도"])
        ms_totals.append(row["합계"])
        ms_texts.append(f"{ms}억 돌파!")
        ms_colors_list.append(milestone_colors.get(ms, "#667eea"))
    prev_t = row["합계"]

if ms_years:
    fig_roadmap.add_trace(go.Scatter(
        x=ms_years, y=ms_totals, mode="markers+text", name="목표 달성",
        marker=dict(size=18, color=ms_colors_list, symbol="star", line=dict(width=2, color="#333")),
        text=ms_texts, textposition="top center", textfont=dict(size=13, color="#333"),
    ))

# 이벤트 마커
event_rows = chart_df[chart_df["이벤트"] != ""]
if not event_rows.empty:
    fig_roadmap.add_trace(go.Scatter(
        x=event_rows["년도"], y=event_rows["합계"], mode="markers+text", name="이벤트",
        marker=dict(size=14, color="#f45c43", symbol="diamond"),
        text=event_rows["이벤트"], textposition="bottom center", textfont=dict(size=12),
    ))

# 억 단위 기준선 (선택 구간 범위 내)
min_asset = chart_df["합계"].min()
max_asset = chart_df["합계"].max()
for target in sorted(milestone_colors.keys()):
    threshold = target * 100_000_000  # 1억 = 100,000,000
    if min_asset * 0.8 <= threshold <= max_asset * 1.2:
        fig_roadmap.add_hline(
            y=threshold, line_dash="dash", line_color="rgba(0,0,0,0.15)",
            annotation_text=f"{target}억", annotation_position="right",
        )

fig_roadmap.update_layout(
    height=520, margin=dict(l=10, r=60, t=30, b=20),
    xaxis_title="년도", yaxis_title="자산 (원)",
    xaxis=dict(tickfont=dict(size=13)),
    yaxis=dict(tickformat=",", tickfont=dict(size=12)),
    showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=12)),
)
fig_roadmap.update_xaxes(
    ticktext=[f"{r['년도']}<br>({r['나이']}세)" for r in sec_rows[::2]],
    tickvals=[r["년도"] for r in sec_rows[::2]],
)
st.plotly_chart(fig_roadmap, use_container_width=True)

# ─── 30년 로드맵 회고 메모 ───
st.markdown("")
st.markdown("#### 🪞 30년 로드맵 회고")
st.caption("자산 계획 점검 · 향후 전략 · 떠오르는 생각 등 자유롭게 기록 (자동으로 영구 저장)")

_rm_events, _rm_rates, _rm_settings = load_roadmap_config()
_rm_memo_saved = str(_rm_settings.get("roadmap_memo", "") or "")
_rm_memo_input = st.text_area(
    "회고 메모",
    value=_rm_memo_saved,
    height=240,
    key="roadmap_memo_input",
    placeholder="예: 2031년 14% 수익 구간이 너무 낙관적인 가정 같다 / 결혼 비용 25M은 신혼여행 포함이라 합리적 / 50대 진입 전 100억 돌파 가능 여부 재검토 필요…",
    label_visibility="collapsed",
)
_rm_btn1, _rm_btn2 = st.columns([1, 4])
with _rm_btn1:
    if st.button("💾 메모 저장", type="primary", use_container_width=True, key="roadmap_memo_save"):
        _rm_settings["roadmap_memo"] = _rm_memo_input
        save_roadmap_config(_rm_events, _rm_rates, _rm_settings)
        st.success("✅ 30년 로드맵 회고가 저장되었습니다.")
        st.rerun()
with _rm_btn2:
    if _rm_memo_saved.strip():
        st.caption(f"📌 마지막 저장본 길이 {len(_rm_memo_saved):,}자")

# ─── 하단 정보 ───
st.markdown("---")
st.caption("효하 가계부 v1.1 | 데이터는 로컬에만 저장됩니다 💾")
