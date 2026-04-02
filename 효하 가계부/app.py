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
    /* expander 내부 테이블 */
    .dataframe { font-size: 0.85rem !important; }
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


def load_memo(month_key):
    """월별 메모 로드"""
    if MEMO_FILE.exists():
        with open(MEMO_FILE, "r", encoding="utf-8") as f:
            memos = json.load(f)
        return memos.get(month_key, {
            "정산": "", "피드백": "", "개선점": "", "지난 달 반영 내역": ""
        })
    return {"정산": "", "피드백": "", "개선점": "", "지난 달 반영 내역": ""}


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


def open_file(file_path):
    """파일을 기본 프로그램으로 열기"""
    try:
        if sys.platform == "win32":
            os.startfile(file_path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", file_path])
        else:
            subprocess.Popen(["xdg-open", file_path])
        return True
    except Exception as e:
        st.error(f"파일 열기 실패: {e}")
        return False


# ─── 메인 앱 ───
st.markdown('<div class="main-header">💰 효하 가계부</div>', unsafe_allow_html=True)

# ─── 사이드바: 파일 업로드 & 설정 ───
with st.sidebar:
    st.header("📂 데이터 업로드")
    uploaded_file = st.file_uploader(
        "가계부 CSV 또는 엑셀 파일",
        type=["csv", "xlsx", "xls"],
        help="노션에서 내보낸 CSV 또는 엑셀 파일을 올려주세요"
    )

    # 업로드한 파일 저장
    if uploaded_file is not None:
        save_path = SAVED_DATA_DIR / uploaded_file.name
        with open(save_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.success(f"✅ '{uploaded_file.name}' 저장됨")

    # 저장된 파일 목록
    saved_files = sorted(SAVED_DATA_DIR.glob("*.csv")) + sorted(SAVED_DATA_DIR.glob("*.xlsx")) + sorted(SAVED_DATA_DIR.glob("*.xls"))
    selected_saved = None
    if saved_files:
        st.markdown("**📁 저장된 파일**")
        saved_names = [f.name for f in saved_files]
        selected_saved = st.selectbox("파일 선택", saved_names, label_visibility="collapsed")
        # 삭제 버튼
        if st.button("🗑️ 선택 파일 삭제", use_container_width=True):
            (SAVED_DATA_DIR / selected_saved).unlink()
            st.rerun()

    st.markdown("---")

    # DB 파일 열기
    st.header("📁 DB 파일 열기")
    db_path = st.text_input(
        "파일 경로",
        value=r"C:\Users\iamhy\Downloads\가계부",
        help="가계부 DB 파일이 있는 경로"
    )
    if st.button("📂 DB 폴더 열기", use_container_width=True):
        open_file(db_path)

    st.markdown("---")

    # 저장된 설정 불러오기
    _, _, _saved = load_roadmap_config()

    # 목표 자산 설정
    st.header("🎯 목표 자산")
    target_asset = st.number_input(
        "목표 금액 (원)",
        min_value=0,
        value=_saved.get("target_asset", 100_000_000),
        step=1_000_000,
        format="%d"
    )
    if target_asset:
        st.caption(f"= {target_asset:,}원")
    current_asset = st.number_input(
        "현재 자산 (원)",
        min_value=0,
        value=_saved.get("current_asset", 0),
        step=100_000,
        format="%d"
    )
    if current_asset:
        st.caption(f"= {current_asset:,}원")

    st.markdown("---")

    # 장기 로드맵 설정
    st.header("🗺️ 장기 로드맵")
    birth_year = st.number_input(
        "출생 년도",
        min_value=1950, max_value=2010, value=_saved.get("birth_year", 1992), step=1
    )
    roadmap_start_asset = st.number_input(
        "시작 보유 자산 (원)",
        min_value=0, value=_saved.get("roadmap_start_asset", 170_000_000), step=1_000_000, format="%d"
    )
    if roadmap_start_asset:
        st.caption(f"= {roadmap_start_asset:,}원")
    annual_savings = st.number_input(
        "연 저축액 (원)",
        min_value=0, value=_saved.get("annual_savings", 20_000_000), step=1_000_000, format="%d"
    )
    if annual_savings:
        st.caption(f"= {annual_savings:,}원")
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
        "target_asset": target_asset,
        "current_asset": current_asset,
        "birth_year": birth_year,
        "roadmap_start_asset": roadmap_start_asset,
        "annual_savings": annual_savings,
        "return_rate": return_rate,
        "roadmap_years": roadmap_years,
    }
    if _new_settings != _saved:
        _ev, _rc, _ = load_roadmap_config()
        save_roadmap_config(_ev, _rc, _new_settings)

# ─── 데이터 로드 ───
df = None
# 새 업로드 우선, 없으면 저장된 파일에서 로드
_load_path = None
if uploaded_file is not None:
    _load_path = SAVED_DATA_DIR / uploaded_file.name
elif saved_files:
    _load_path = SAVED_DATA_DIR / selected_saved

if _load_path and _load_path.exists():
    try:
        if _load_path.suffix == ".csv":
            df = pd.read_csv(_load_path, encoding="utf-8-sig")
        else:
            df = pd.read_excel(_load_path)
        df = parse_data(df)
        # 미결제→결제 토글 상태 적용
        if df is not None:
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
            if target_asset > 0:
                progress = min((current_asset / target_asset) * 100, 100)
                remaining = target_asset - current_asset
                st.markdown(f"""
                <div class="metric-card saving">
                    <div class="metric-label">목표까지 남은 금액</div>
                    <div class="metric-value">{format_won_abs(remaining)}</div>
                </div>
                """, unsafe_allow_html=True)

        if unpaid_count > 0:
            st.warning(f"⚠️ 미결제 {unpaid_count}건 ({format_won_abs(unpaid_amount)}) — 결제 확인이 필요합니다")

        if target_asset > 0 and current_asset > 0:
            progress_pct = min(current_asset / target_asset, 1.0)
            st.progress(progress_pct, text=f"🎯 목표 달성률: {progress_pct:.1%} ({format_won_abs(current_asset)} / {format_won_abs(target_asset)})")

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

        st.markdown("")
        col_fixed, col_var = st.columns(2)
        with col_fixed:
            st.markdown(f"### 🧾 고정지출 — {format_won_abs(total_fixed)}")
        with col_var:
            st.markdown(f"### 🔄 변동지출 — {format_won_abs(total_variable)}")
        st.markdown("")

        # ─── 탭 ───
        tab_income, tab_fixed, tab_variable, tab_chart, tab_goal, tab_memo = st.tabs([
            "💰 수입", "🧾 고정지출", "🔄 변동지출", "📈 그래프", "🎯 목표", "📝 메모"
        ])

        with tab_income:
            if income_df.empty:
                st.info("이번 달 수입 내역이 없습니다.")
            else:
                income_summary = income_df.groupby("소분류")["순수입(부호)"].sum().reset_index()
                income_summary.columns = ["소분류", "금액"]
                income_summary = income_summary.sort_values("금액", ascending=False)
                for _, row in income_summary.iterrows():
                    sub_cat = row["소분류"]
                    amount = row["금액"]
                    sub_items = income_df[income_df["소분류"] == sub_cat]
                    with st.expander(f"💰 {sub_cat} — {format_won_abs(amount)} ({len(sub_items)}건)"):
                        display_cols = ["날짜", "이름", "순수입(부호)", "사용처"]
                        display_df = sub_items[display_cols].copy()
                        display_df.columns = ["날짜", "내용", "금액", "사용처"]
                        display_df["금액"] = display_df["금액"].apply(lambda x: f"{x:,.0f}원")
                        st.dataframe(display_df, use_container_width=True, hide_index=True)

        with tab_fixed:
            if fixed_df.empty:
                st.info("이번 달 고정지출 내역이 없습니다.")
            else:
                fixed_summary = fixed_df.groupby("소분류")["실 사용"].sum().reset_index()
                fixed_summary.columns = ["소분류", "금액"]
                fixed_summary = fixed_summary.sort_values("금액", ascending=False)
                for _, row in fixed_summary.iterrows():
                    sub_cat = row["소분류"]
                    amount = row["금액"]
                    sub_items = fixed_df[fixed_df["소분류"] == sub_cat]
                    with st.expander(f"🧾 {sub_cat} — {format_won_abs(amount)} ({len(sub_items)}건)"):
                        display_cols = ["날짜", "이름", "실 사용", "결제 방법", "결제 여부"]
                        display_df = sub_items[display_cols].copy()
                        display_df.columns = ["날짜", "내용", "금액", "결제 방법", "결제 여부"]
                        display_df["금액"] = display_df["금액"].apply(lambda x: f"{x:,.0f}원")
                        st.dataframe(display_df, use_container_width=True, hide_index=True)

        with tab_variable:
            if variable_df.empty:
                st.info("이번 달 변동지출 내역이 없습니다.")
            else:
                # 사용처 필터
                all_usage = variable_df["사용처"].fillna("").astype(str).str.strip()
                all_usage = all_usage.replace("", "미분류")
                variable_df = variable_df.copy()
                variable_df["사용처_표시"] = all_usage
                usage_options = sorted(variable_df["사용처_표시"].unique().tolist())

                if len(usage_options) > 1:
                    selected_usage = st.multiselect(
                        "👥 사용처 필터",
                        options=usage_options,
                        default=usage_options,
                        key="var_usage_filter"
                    )
                    filtered_var = variable_df[variable_df["사용처_표시"].isin(selected_usage)]
                else:
                    filtered_var = variable_df

                # 사용처별 지출 요약 그래프
                if len(usage_options) > 1 and not filtered_var.empty:
                    usage_summary = variable_df.groupby("사용처_표시")["실 사용"].sum().reset_index()
                    usage_summary.columns = ["사용처", "금액"]
                    usage_summary = usage_summary.sort_values("금액", ascending=False)

                    ug_col1, ug_col2 = st.columns(2)
                    with ug_col1:
                        fig_usage_bar = px.bar(usage_summary, x="사용처", y="금액",
                                               text="금액", color="사용처",
                                               color_discrete_sequence=px.colors.qualitative.Set2)
                        fig_usage_bar.update_traces(texttemplate="%{text:,.0f}원", textposition="outside",
                                                    textfont_size=13, cliponaxis=False)
                        fig_usage_bar.update_layout(showlegend=False, height=320,
                                                     margin=dict(l=10, r=10, t=50, b=10),
                                                     xaxis_title="", yaxis_title="",
                                                     xaxis=dict(tickfont=dict(size=12)))
                        st.plotly_chart(fig_usage_bar, use_container_width=True)
                    with ug_col2:
                        fig_usage_pie = px.pie(usage_summary, values="금액", names="사용처",
                                               color_discrete_sequence=px.colors.qualitative.Set2, hole=0.3)
                        fig_usage_pie.update_traces(textposition="inside", textinfo="label+percent", textfont_size=13)
                        fig_usage_pie.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                                                     legend=dict(font=dict(size=12)))
                        st.plotly_chart(fig_usage_pie, use_container_width=True)
                    st.markdown("---")
                    st.markdown("")

                # 대분류→소분류 드릴다운 (필터 적용)
                var_major = filtered_var.groupby("대분류")["실 사용"].sum().reset_index()
                var_major.columns = ["대분류", "금액"]
                var_major = var_major.sort_values("금액", ascending=False)
                for _, major_row in var_major.iterrows():
                    major_cat = major_row["대분류"]
                    major_amount = major_row["금액"]
                    major_items = filtered_var[filtered_var["대분류"] == major_cat]
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
                            st.dataframe(display_df, use_container_width=True, hide_index=True)
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
            st.markdown(f"### 🎯 {selected_month} 예산 목표")

            # 목표 데이터 로드
            all_goals = load_budget_goals()
            month_goals = all_goals.get(selected_month, {})

            # 현재 월의 대분류 목록 (지출만)
            expense_categories = sorted(expense_df["대분류"].unique().tolist()) if not expense_df.empty else []

            # ─── 목표 설정 ───
            with st.expander("⚙️ 월간 목표 설정", expanded=not bool(month_goals)):
                with st.form("budget_goal_form", clear_on_submit=False):
                    # 전체 월간 목표
                    st.markdown("**💰 전체 월간 목표**")
                    total_goal_input = st.number_input(
                        "전체 월간 지출 목표 (원)",
                        min_value=0,
                        value=month_goals.get("__total__", 0),
                        step=100000,
                        format="%d",
                        key=f"goal_{selected_month}___total__",
                        help="카테고리 합산과 별도로 전체 지출 목표를 설정합니다"
                    )

                    st.markdown("---")
                    st.markdown("**📂 카테고리별 목표**")
                    st.caption("대분류별 월간 목표 금액을 설정하세요. 0원 = 목표 없음")
                    goal_inputs = {}

                    # 전체 월 카테고리 통합 (한번 추가하면 다른 달에도 표시)
                    all_month_cats = set()
                    for m_goals in all_goals.values():
                        for k in m_goals.keys():
                            if not k.startswith("__"):
                                all_month_cats.add(k)
                    all_cats = sorted(all_month_cats | set(expense_categories))
                    if not all_cats:
                        st.info("지출 데이터가 없습니다. 파일 업로드 후 설정해주세요.")

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
                                        key=f"goal_{selected_month}_{cat}"
                                    )

                    # 새 카테고리 추가
                    new_cat_col1, new_cat_col2 = st.columns([2, 1])
                    with new_cat_col1:
                        new_cat_name = st.text_input("새 카테고리 추가", placeholder="예: 여행, 교육비", key="new_goal_cat")
                    with new_cat_col2:
                        new_cat_amount = st.number_input("목표 금액", min_value=0, value=0, step=10000, format="%d", key="new_goal_amount")

                    if st.form_submit_button("💾 월간 목표 저장", use_container_width=True, type="primary"):
                        # 0원이 아닌 것만 저장
                        saved_goals = {k: v for k, v in goal_inputs.items() if v > 0}
                        if total_goal_input > 0:
                            saved_goals["__total__"] = total_goal_input
                        if new_cat_name.strip() and new_cat_amount > 0:
                            saved_goals[new_cat_name.strip()] = new_cat_amount
                        # 기존 주간 목표 설정 유지
                        for k, v in month_goals.items():
                            if k.startswith("__weekly_"):
                                saved_goals[k] = v
                        all_goals[selected_month] = saved_goals
                        save_budget_goals(all_goals)
                        st.success("✅ 월간 목표가 저장되었습니다!")
                        st.rerun()

                # 주간 목표 설정 (폼 밖 — 라디오 즉시 반영)
                st.markdown("---")
                st.markdown("**📆 주간 목표 설정**")
                weekly_mode = st.radio(
                    "주간 목표 방식",
                    ["자동 (월간 목표 ÷ 주차수)", "직접 설정"],
                    index=0 if month_goals.get("__weekly_mode__", "auto") == "auto" else 1,
                    key=f"weekly_mode_{selected_month}",
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
                        auto_rows.append({"카테고리": "**전체**", "월간 목표": f"{total_preview:,.0f}원", "주간 목표": f"{total_preview / 4:,.0f}원"})
                        st.dataframe(pd.DataFrame(auto_rows), use_container_width=True, hide_index=True)
                    else:
                        st.info("월간 목표를 먼저 설정하면 자동 계산 결과가 표시됩니다.")

                    # 자동 모드 저장
                    if month_goals.get("__weekly_mode__") != "auto":
                        month_goals["__weekly_mode__"] = "auto"
                        all_goals[selected_month] = month_goals
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
                            key=f"weekly_total_{selected_month}"
                        )
                        # 카테고리별 주간 목표 (전체 월 카테고리 + 현재 데이터 카테고리 통합)
                        all_known_cats = set()
                        for m_goals in all_goals.values():
                            for k in m_goals.keys():
                                if not k.startswith("__"):
                                    all_known_cats.add(k)
                                elif k.startswith("__weekly_cat_"):
                                    all_known_cats.add(k.replace("__weekly_cat_", ""))
                        all_known_cats.update(expense_categories)
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
                                                key=f"wgoal_{selected_month}_{w_cat}"
                                            )

                        if st.form_submit_button("💾 주간 목표 저장", use_container_width=True, type="primary"):
                            # 기존 월간 목표 유지 + 주간 목표 업데이트
                            saved_goals = {k: v for k, v in month_goals.items() if not k.startswith("__weekly_")}
                            saved_goals["__weekly_mode__"] = "manual"
                            if weekly_goal_input > 0:
                                saved_goals["__weekly_total__"] = weekly_goal_input
                            for w_cat, w_amt in weekly_cat_inputs.items():
                                if w_amt > 0:
                                    saved_goals[f"__weekly_cat_{w_cat}"] = w_amt
                            all_goals[selected_month] = saved_goals
                            save_budget_goals(all_goals)
                            st.success("✅ 주간 목표가 저장되었습니다!")
                            st.rerun()

            # 목표 새로 로드 (저장 후 반영)
            all_goals = load_budget_goals()
            month_goals = all_goals.get(selected_month, {})

            # 카테고리별 목표만 분리 (내부 키 제외)
            cat_goals = {k: v for k, v in month_goals.items() if not k.startswith("__")}
            overall_goal = month_goals.get("__total__", 0)
            weekly_mode_saved = month_goals.get("__weekly_mode__", "auto")

            if not cat_goals and not overall_goal:
                st.info("👆 먼저 목표 금액을 설정해주세요.")
            else:
                # ─── 월간 달성률 ───
                st.markdown("#### 📅 월간 달성률")
                total_spent = abs(expense_df["실 사용"].sum()) if not expense_df.empty else 0

                # 전체 목표 (설정되어 있으면 전체 목표 사용, 아니면 카테고리 합산)
                display_total_goal = overall_goal if overall_goal > 0 else sum(cat_goals.values())
                total_pct = (total_spent / display_total_goal * 100) if display_total_goal > 0 else 0

                # 전체 요약
                summary_color = "🟢" if total_pct <= 100 else "🔴"
                goal_label = "전체 목표" if overall_goal > 0 else "카테고리 합산"
                st.markdown(f"**{summary_color} {goal_label}: {format_won_abs(total_spent)} / {format_won_abs(display_total_goal)} ({total_pct:.0f}%)**")
                st.progress(min(total_pct / 100, 1.0))

                if cat_goals:
                    # 카테고리별 테이블
                    goal_rows = []
                    for cat, goal_amount in sorted(cat_goals.items()):
                        if not expense_df.empty:
                            cat_spent = expense_df[expense_df["대분류"] == cat]["실 사용"].sum()
                        else:
                            cat_spent = 0
                        pct = (cat_spent / goal_amount * 100) if goal_amount > 0 else 0
                        remain = goal_amount - cat_spent
                        status = "✅ 여유" if pct <= 80 else ("⚠️ 주의" if pct <= 100 else "🚨 초과")
                        goal_rows.append({
                            "카테고리": cat,
                            "목표": f"{goal_amount:,.0f}원",
                            "사용": f"{cat_spent:,.0f}원",
                            "잔여": f"{remain:,.0f}원",
                            "달성률": f"{pct:.0f}%",
                            "상태": status
                        })

                    goal_df = pd.DataFrame(goal_rows)
                    st.dataframe(goal_df, use_container_width=True, hide_index=True)

                    # 달성률 막대그래프
                    chart_data = []
                    for cat, goal_amount in sorted(cat_goals.items()):
                        if not expense_df.empty:
                            cat_spent = expense_df[expense_df["대분류"] == cat]["실 사용"].sum()
                        else:
                            cat_spent = 0
                        pct = (cat_spent / goal_amount * 100) if goal_amount > 0 else 0
                        chart_data.append({"카테고리": cat, "달성률": min(pct, 150), "색상": "#38ef7d" if pct <= 100 else "#f45c43"})

                    chart_df = pd.DataFrame(chart_data)
                    fig_goal = go.Figure()
                    fig_goal.add_trace(go.Bar(
                        x=chart_df["카테고리"], y=chart_df["달성률"],
                        marker_color=chart_df["색상"],
                        text=[f"{v:.0f}%" for v in chart_df["달성률"]],
                        textposition="outside", textfont_size=13, cliponaxis=False
                    ))
                    # 100% 기준선
                    fig_goal.add_hline(y=100, line_dash="dash", line_color="gray", annotation_text="목표 100%")
                    fig_goal.update_layout(height=380, margin=dict(l=10, r=10, t=40, b=10),
                                            yaxis_title="달성률 (%)", xaxis_title="",
                                            xaxis=dict(tickfont=dict(size=13)),
                                            yaxis=dict(tickfont=dict(size=12)))
                    st.plotly_chart(fig_goal, use_container_width=True)

                st.markdown("")
                st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
                st.markdown("")

                # ─── 주간 달성률 ───
                st.markdown("#### 📆 주간 달성률")

                # 날짜 파싱 — 주차 계산
                if not expense_df.empty and "날짜" in expense_df.columns:
                    week_df = expense_df.copy()
                    week_df["날짜_parsed"] = pd.to_datetime(week_df["날짜"], errors="coerce")
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
            st.markdown(f"### 📝 {selected_month} 지출 회고")

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

            # ─── 메모 입력 ───
            memo = load_memo(selected_month)
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
            if st.button("💾 메모 저장", use_container_width=True, type="primary"):
                save_memo(selected_month, memo)
                st.success(f"✅ {selected_month} 메모가 저장되었습니다!")

        # ─── 하단: 미결제 내역 ───
        st.markdown("")
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown("")

        # 결제완료 처리된 항목 표시 (되돌리기 가능)
        ps = load_payment_status()
        paid_items = ps.get("paid_items", [])
        if paid_items:
            with st.expander(f"✅ 결제완료 처리된 항목 ({len(paid_items)}건) — 되돌리기 가능", expanded=False):
                for idx, item in enumerate(paid_items):
                    col_info, col_btn = st.columns([4, 1])
                    with col_info:
                        st.markdown(f"📌 {item['날짜']} | {item['이름']} | {abs(item['금액']):,.0f}원")
                    with col_btn:
                        if st.button("↩️ 되돌리기", key=f"undo_paid_{idx}"):
                            paid_items.pop(idx)
                            save_payment_status({"paid_items": paid_items})
                            st.rerun()

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
            new_ev_amount = st.number_input("금액 (원)", min_value=0, value=0, step=1_000_000, format="%d")
        with ev_row2_col2:
            st.markdown("<br>", unsafe_allow_html=True)
            submitted = st.form_submit_button("➕ 추가", use_container_width=True)

        if submitted:
            if new_ev_desc and new_ev_amount > 0:
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

# ─── 하단 정보 ───
st.markdown("---")
st.caption("효하 가계부 v1.1 | 데이터는 로컬에만 저장됩니다 💾")
