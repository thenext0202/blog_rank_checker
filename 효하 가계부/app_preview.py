"""
효하 가계부 — 업로드용 탭 미리보기 (단독 실행)
- 기존 app.py는 건드리지 않고, 새 '업로드용' 탭만 따로 보여주는 화면
- 데이터 파일(memos.json / assets_detail.json / roadmap_config.json)은 그대로 공유
- 실행: streamlit run app_preview.py --server.port 8502
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import json
import re
from pathlib import Path
from datetime import datetime

# ─── 설정 ───
st.set_page_config(
    page_title="효하 가계부 — 업로드용 미리보기",
    page_icon="📤",
    layout="wide",
)

DATA_DIR = Path(__file__).parent / "data"
MEMO_FILE = DATA_DIR / "memos.json"
ASSETS_DETAIL_FILE = DATA_DIR / "assets_detail.json"
ROADMAP_FILE = DATA_DIR / "roadmap_config.json"
BUDGET_GOALS_FILE = DATA_DIR / "budget_goals.json"
SAVED_DATA_DIR = DATA_DIR / "saved_files"

# ─── 스타일 (기존 앱과 통일 + 글자 크기 키움) ───
st.markdown("""
<style>
/* 본문 전반 글자 크기 키움 */
html, body, [class*="st-"], .stMarkdown, .stMarkdown p, .stMarkdown li {
    font-size: 1.1rem !important;
    line-height: 1.65 !important;
}
.stMarkdown h1 { font-size: 2.2rem !important; }
.stMarkdown h2 { font-size: 1.8rem !important; }
.stMarkdown h3 { font-size: 1.5rem !important; }
.stMarkdown strong { font-size: 1.1rem; }
/* 캡션 */
.stCaption, [data-testid="stCaptionContainer"] { font-size: 1rem !important; }
/* 요약 카드 */
.metric-card {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 16px; padding: 1.4rem; color: white;
    text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    margin-bottom: 0.5rem;
}
.metric-card.income   { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
.metric-card.expense  { background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%); }
.metric-card.balance  { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }
.metric-card.asset    { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
.metric-card.under    { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
.metric-card.over     { background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%); }
.metric-label { font-size: 1.15rem; opacity: 0.95; }
.metric-value { font-size: 2rem; font-weight: 700; margin-top: 0.3rem; }
.divider { border-top: 2px solid #e0e0e0; margin: 2rem 0; }
.section-title { font-size: 1.6rem; font-weight: 700; margin-top: 1rem; margin-bottom: 0.6rem; }
.subsection { font-size: 1.25rem; font-weight: 600; margin-top: 1rem; margin-bottom: 0.4rem; }
/* 표: 글자 키움 + 줄 높이 통일 */
[data-testid="stDataFrame"] { font-size: 1.05rem !important; }
[data-testid="stDataFrame"] div[role="gridcell"],
[data-testid="stDataFrame"] div[role="columnheader"] {
    font-size: 1.05rem !important;
}
/* 표 셀 padding 통일로 행 높이 고정 */
[data-testid="stDataFrame"] [role="gridcell"] { padding: 6px 10px !important; }
</style>
""", unsafe_allow_html=True)


# ─── 표 헬퍼: 스크롤 없이 모든 행이 다 보이도록 height 자동 계산 ───
ROW_PX = 48      # 한 행 높이 (글자 키운 후 기준 — 여유있게)
HEADER_PX = 50   # 헤더 높이
PAD_PX = 16      # 여유 (테두리/스크롤바 영역)

def _table_height(n_rows):
    n = max(int(n_rows), 1)
    return HEADER_PX + ROW_PX * n + PAD_PX

def show_table(df_disp):
    """모든 표 공통 — 행 다 보이게, 글자 동일, 컨테이너 폭 사용"""
    st.dataframe(
        df_disp,
        use_container_width=True,
        hide_index=True,
        height=_table_height(len(df_disp)),
    )


# ─── 유틸 (app.py에서 필요한 것만 복사) ───
def format_won(amount):
    if amount >= 0:
        return f"+{amount:,.0f}원"
    return f"{amount:,.0f}원"


def format_won_abs(amount):
    return f"{abs(amount):,.0f}원"


_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U00002BFF"
    "\U0001F000-\U0001F251"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "\U00002B50"
    "]+", flags=re.UNICODE
)


def strip_emoji(text):
    return _EMOJI_PATTERN.sub("", str(text)).strip()


def normalize_categories(df, col="대분류"):
    stripped = df[col].apply(strip_emoji)
    repr_map = {}
    for original, text_only in zip(df[col], stripped):
        if text_only not in repr_map:
            repr_map[text_only] = original
    df[col] = stripped.map(repr_map)
    return df


def extract_month(date_str):
    try:
        date_str = str(date_str)
        if "년" in date_str and "월" in date_str:
            year = date_str.split("년")[0].strip()
            month = date_str.split("년")[1].split("월")[0].strip()
            return f"{year}-{int(month):02d}"
    except Exception:
        pass
    return "알 수 없음"


def parse_data(df):
    df.columns = [c.strip().replace("﻿", "") for c in df.columns]
    required = ["이름", "날짜", "대분류", "소분류", "순수입(부호)"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.error(f"필수 컬럼이 없습니다: {missing}")
        st.info(f"현재 컬럼: {list(df.columns)}")
        return None
    df["순수입(부호)"] = pd.to_numeric(df["순수입(부호)"], errors="coerce").fillna(0)
    if "실 사용" in df.columns:
        df["실 사용"] = pd.to_numeric(df["실 사용"], errors="coerce").fillna(0)
    else:
        df["실 사용"] = df["순수입(부호)"].abs()
    if "월" in df.columns and df["월"].notna().any():
        df["월"] = df["월"].astype(str).str.strip()
    else:
        df["월"] = df["날짜"].apply(extract_month)
    df["구분"] = df["순수입(부호)"].apply(lambda x: "수입" if x > 0 else "지출")
    for col in ["사용처", "결제 여부", "결제 방법", "필수 여부"]:
        if col not in df.columns:
            df[col] = ""
    df = normalize_categories(df, "대분류")
    return df


def load_memo(month_key):
    if MEMO_FILE.exists():
        with open(MEMO_FILE, "r", encoding="utf-8") as f:
            memos = json.load(f)
        m = memos.get(month_key, {})
    else:
        m = {}
    m.setdefault("정산", "")
    m.setdefault("피드백", "")
    m.setdefault("개선점", "")
    m.setdefault("지난 달 반영 내역", "")
    if not isinstance(m.get("목표 회고"), dict):
        m["목표 회고"] = {}
    return m


def load_assets_detail():
    if ASSETS_DETAIL_FILE.exists():
        with open(ASSETS_DETAIL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "monthly" not in data:
            data["monthly"] = {}
        return data
    return {"monthly": {}}


def load_budget_goals():
    if BUDGET_GOALS_FILE.exists():
        with open(BUDGET_GOALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_roadmap_config():
    if ROADMAP_FILE.exists():
        with open(ROADMAP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("events", []), data.get("rate_changes", []), data.get("settings", {})
    return [], [], {}


def calc_roadmap(birth_year, start_asset, annual_savings, default_rate, events, rate_changes, years=30):
    """복리 자산 로드맵 (app.py와 동일 로직)"""
    current_year = datetime.now().year
    rows = []
    asset = start_asset
    sorted_rates = sorted(rate_changes, key=lambda r: r.get("year_start", r.get("year", 0)))
    for i in range(years):
        year = current_year + i
        age = year - birth_year + 1
        year_rate = default_rate
        for rc in sorted_rates:
            rc_start = rc.get("year_start", rc.get("year", 0))
            rc_end = rc.get("year_end", 9999)
            if rc_start <= year <= rc_end:
                year_rate = rc["rate"]
        year_events = [e for e in events if e["year"] == year]
        event_amount = sum(e["amount"] for e in year_events)
        event_desc = ", ".join(e["desc"] for e in year_events) if year_events else ""
        total = asset * (1 + year_rate / 100) + annual_savings + event_amount
        rows.append({
            "년도": year, "나이": age, "보유 자산": asset, "저축액": annual_savings,
            "수익률": year_rate, "이벤트": event_desc, "이벤트 금액": event_amount,
            "합계": total,
        })
        asset = total
    return rows


# ─── 사이드바: 파일 업로드 + 월 선택 ───
st.sidebar.markdown("## 📤 업로드용 미리보기")
st.sidebar.caption("기존 app.py와 데이터 공유 — 메모/재산/로드맵 모두 그대로 표시")
st.sidebar.markdown("---")

uploaded = st.sidebar.file_uploader("가계부 CSV/엑셀", type=["csv", "xlsx", "xls"])

# 저장된 파일 선택도 지원
saved_files = []
if SAVED_DATA_DIR.exists():
    saved_files = sorted([p.name for p in SAVED_DATA_DIR.glob("*.csv")])
saved_choice = None
if saved_files:
    saved_choice = st.sidebar.selectbox(
        "또는 저장된 파일",
        options=["(선택 안 함)"] + saved_files,
        index=0,
    )
    if saved_choice == "(선택 안 함)":
        saved_choice = None

df = None
if uploaded is not None:
    try:
        if uploaded.name.lower().endswith(".csv"):
            df = pd.read_csv(uploaded, encoding="utf-8-sig")
        else:
            df = pd.read_excel(uploaded)
        df = parse_data(df)
    except Exception as e:
        st.sidebar.error(f"파일 읽기 실패: {e}")
elif saved_choice:
    try:
        df = pd.read_csv(SAVED_DATA_DIR / saved_choice, encoding="utf-8-sig")
        df = parse_data(df)
    except Exception as e:
        st.sidebar.error(f"파일 읽기 실패: {e}")

st.title("📤 업로드용 — 한 장 요약 미리보기")
st.caption("브라우저 인쇄(Ctrl+P) → PDF 저장으로 한 장으로 뽑을 수 있어요")

if df is None:
    st.info("👈 사이드바에서 가계부 파일을 업로드하거나 저장된 파일을 선택해주세요.")
    st.stop()

months = sorted([m for m in df["월"].unique() if m != "알 수 없음"], reverse=True)
if not months:
    st.warning("날짜 데이터를 파싱할 수 없습니다.")
    st.stop()

selected_month = st.selectbox("📅 월 선택", months, index=0)

# ─── 월별 데이터 분리 (app.py와 동일) ───
month_df = df[df["월"] == selected_month].copy()
income_df = month_df[month_df["구분"] == "수입"].copy()
expense_df = month_df[month_df["구분"] == "지출"].copy()
total_income = income_df["순수입(부호)"].sum()
total_expense = expense_df["순수입(부호)"].sum()
balance = total_income + total_expense
fixed_df = expense_df[expense_df["대분류"].str.contains("고정지출", na=False)].copy()
variable_df = expense_df[~expense_df["대분류"].str.contains("고정지출", na=False)].copy()
total_fixed = fixed_df["순수입(부호)"].sum()
total_variable = variable_df["순수입(부호)"].sum()

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)


# ─── ⓪ 목표 달성률 (월간 + 연간) — 원본 app.py 상단과 동일 ───
_events_top, _rate_top, _settings_top = load_roadmap_config()
_monthly_targets_top = _settings_top.get("monthly_targets", {}) or {}
_yearly_target_top = int(_settings_top.get("yearly_target", 0) or 0)

# 연간 — 최신 월 재산 합계 사용
_assets_top = load_assets_detail()
_monthly_top = _assets_top.get("monthly", {})
_latest_asset_total = 0
_latest_asset_month = None
_candidates = sorted([m for m, rows in _monthly_top.items() if rows])
if _candidates:
    _latest_asset_month = _candidates[-1]
    _latest_asset_total = sum(int(r.get("amount", 0) or 0) for r in _monthly_top[_latest_asset_month])

# 월간 — 선택 월의 잔액 / 그 월의 목표
_m_target = int(_monthly_targets_top.get(selected_month, 0) or 0)
_m_balance = int(balance)

def _pct_emoji_top(ratio):
    if ratio >= 1.5: return "🎊"
    if ratio >= 1.0: return "🎉"
    if ratio >= 0.8: return "😊"
    if ratio >= 0.5: return "🙂"
    if ratio >= 0.3: return "😐"
    if ratio > 0:    return "😢"
    return "😭"

if _m_target > 0 or _yearly_target_top > 0:
    st.markdown('<div class="section-title">🎯 목표 달성률</div>', unsafe_allow_html=True)
    g_col1, g_col2 = st.columns(2, vertical_alignment="center")

    with g_col1:
        st.markdown(f"**📅 {selected_month} 월간 목표**")
        if _m_target > 0:
            _m_ratio = _m_balance / _m_target if _m_target else 0
            _m_remain = max(_m_target - _m_balance, 0)
            _m_color = "#2563eb" if _m_ratio >= 1.0 else "#ef4444"
            _m_emoji = _pct_emoji_top(_m_ratio)
            st.markdown(
                f"<div style='color:{_m_color}; font-weight:700; font-size:1.2rem; margin:6px 0;'>"
                f"{_m_emoji} {_m_ratio:.1%} "
                f"<span style='font-weight:500; font-size:1.05rem'>"
                f"(잔액 {format_won_abs(_m_balance)} / 목표 {format_won_abs(_m_target)} · 잔여 {format_won_abs(_m_remain)})"
                f"</span></div>",
                unsafe_allow_html=True
            )
            st.progress(max(min(_m_ratio, 1.0), 0.0))
        else:
            st.caption(f"📅 {selected_month} 월간 목표 미설정")

    with g_col2:
        _now_local = datetime.now()
        _year_label = f"{_now_local.year}년({_now_local.month}월 기준)"
        st.markdown(f"**📆 {_year_label} 연간 목표**")

        # 이번 년 이벤트 합계 (지출은 음수)
        _now_year = _now_local.year
        _this_year_events = [e for e in _events_top if e.get("year") == _now_year]
        _ty_event_amt = sum(int(e.get("amount", 0) or 0) for e in _this_year_events)
        _ty_event_desc = ", ".join(e.get("desc", "") for e in _this_year_events) if _this_year_events else ""

        if _yearly_target_top > 0:
            _y_ratio = _latest_asset_total / _yearly_target_top if _yearly_target_top else 0
            _y_remain = max(_yearly_target_top - _latest_asset_total, 0)
            _y_color = "#2563eb" if _y_ratio >= 1.0 else "#ef4444"
            _y_emoji = _pct_emoji_top(_y_ratio)

            st.markdown(
                f"<div style='color:{_y_color}; font-weight:700; font-size:1.2rem; margin:6px 0;'>"
                f"{_y_emoji} {_y_ratio:.1%} "
                f"<span style='font-weight:500; font-size:1.05rem'>"
                f"(목표 {format_won_abs(_yearly_target_top)} · 잔여 {format_won_abs(_y_remain)})"
                f"</span></div>",
                unsafe_allow_html=True
            )

            # 이번 년 이벤트 — 작은 글씨, 새 줄
            if _this_year_events:
                _ev_color = "#d32f2f" if _ty_event_amt < 0 else "#2e7d32" if _ty_event_amt > 0 else "#666"
                _ev_desc_part = f" ({_ty_event_desc})" if _ty_event_desc else ""
                st.markdown(
                    f"<div style='color:{_ev_color}; font-size:0.9rem; margin:2px 0 6px 0;'>"
                    f"이번 년 이벤트 {_ty_event_amt:+,.0f}원{_ev_desc_part}"
                    f"</div>",
                    unsafe_allow_html=True
                )

            st.progress(max(min(_y_ratio, 1.0), 0.0))
        else:
            st.caption("📆 연간 목표 미설정")
            if _this_year_events:
                _ev_color = "#d32f2f" if _ty_event_amt < 0 else "#2e7d32"
                st.markdown(
                    f"<div style='color:{_ev_color}; font-size:0.9rem;'>"
                    f"이번 년 이벤트 {_ty_event_amt:+,.0f}원"
                    f"{f' ({_ty_event_desc})' if _ty_event_desc else ''}</div>",
                    unsafe_allow_html=True
                )

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)


# ─── ① 총 수입/총 지출/잔액 ───
st.markdown(f'<div class="section-title">📊 {selected_month} 요약</div>', unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f"""<div class="metric-card income">
        <div class="metric-label">총 수입</div>
        <div class="metric-value">{format_won_abs(total_income)}</div></div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""<div class="metric-card expense">
        <div class="metric-label">총 지출</div>
        <div class="metric-value">{format_won_abs(total_expense)}</div></div>""", unsafe_allow_html=True)
with c3:
    bcls = "balance" if balance >= 0 else "expense"
    st.markdown(f"""<div class="metric-card {bcls}">
        <div class="metric-label">잔액</div>
        <div class="metric-value">{format_won(balance)}</div></div>""", unsafe_allow_html=True)
with c4:
    st.markdown(f"""<div class="metric-card asset">
        <div class="metric-label">고정 / 변동</div>
        <div class="metric-value" style="font-size:1.4rem">
        {format_won_abs(total_fixed)} / {format_won_abs(total_variable)}</div></div>""", unsafe_allow_html=True)

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)


# ─── ①-2 예산 vs 실제 (전체 + 카테고리별) ───
_all_goals = load_budget_goals()
_month_goals = _all_goals.get(selected_month, {}) or {}
_overall_goal = int(_month_goals.get("__total__", 0) or 0)
_cat_goals = {k: int(v) for k, v in _month_goals.items()
              if not k.startswith("__") and isinstance(v, (int, float)) and int(v) > 0}
# 숨김 카테고리 제외
_hidden = _all_goals.get("__hidden_cats__", []) or []
_cat_goals = {k: v for k, v in _cat_goals.items() if k not in set(_hidden)}

_total_spent = abs(expense_df["실 사용"].sum()) if not expense_df.empty else 0

if _overall_goal > 0 or _cat_goals:
    st.markdown('<div class="section-title">🎯 예산 vs 실제</div>', unsafe_allow_html=True)

    # 전체 — 예산 카드 / 사용 카드 / 차이 카드
    if _overall_goal > 0:
        _diff = _overall_goal - _total_spent  # 양수=절약, 음수=초과
        _pct = (_total_spent / _overall_goal * 100) if _overall_goal > 0 else 0
        _diff_cls = "under" if _diff >= 0 else "over"
        _diff_label = f"절약 {format_won_abs(_diff)}" if _diff >= 0 else f"초과 {format_won_abs(-_diff)}"
        _emoji = "🎉" if _pct <= 80 else ("✅" if _pct <= 100 else ("⚠️" if _pct <= 120 else "🚨"))
        b1, b2, b3, b4 = st.columns(4)
        with b1:
            st.markdown(f"""<div class="metric-card balance">
                <div class="metric-label">전체 예산</div>
                <div class="metric-value">{format_won_abs(_overall_goal)}</div></div>""", unsafe_allow_html=True)
        with b2:
            st.markdown(f"""<div class="metric-card expense">
                <div class="metric-label">실제 사용</div>
                <div class="metric-value">{format_won_abs(_total_spent)}</div></div>""", unsafe_allow_html=True)
        with b3:
            st.markdown(f"""<div class="metric-card {_diff_cls}">
                <div class="metric-label">{_emoji} 차이</div>
                <div class="metric-value">{_diff_label}</div></div>""", unsafe_allow_html=True)
        with b4:
            st.markdown(f"""<div class="metric-card asset">
                <div class="metric-label">집행률</div>
                <div class="metric-value">{_pct:.0f}%</div></div>""", unsafe_allow_html=True)
        st.markdown("")

    # 카테고리별 — 표 + 막대그래프
    if _cat_goals:
        _cat_order = _all_goals.get("__cat_order__", []) or []
        _ordered = [c for c in _cat_order if c in _cat_goals]
        _ordered += [c for c in sorted(_cat_goals.keys()) if c not in _ordered]

        rows = []
        chart_rows = []
        for cat in _ordered:
            g = _cat_goals[cat]
            s = abs(expense_df[expense_df["대분류"] == cat]["실 사용"].sum()) if not expense_df.empty else 0
            diff = g - s
            pct = (s / g * 100) if g > 0 else 0
            stat = "🎉 여유" if pct <= 80 else ("✅ 적정" if pct <= 100 else ("⚠️ 주의" if pct <= 120 else "🚨 초과"))
            diff_label = f"-{abs(diff):,.0f}원 (절약)" if diff >= 0 else f"+{abs(diff):,.0f}원 (초과)"
            rows.append({
                "카테고리": cat,
                "예산": f"{g:,.0f}원",
                "실제 사용": f"{s:,.0f}원",
                "차이": diff_label,
                "집행률": f"{pct:.0f}%",
                "상태": stat,
            })
            chart_rows.append({
                "카테고리": cat,
                "예산": g,
                "실제": s,
                "색상": "#38ef7d" if pct <= 100 else "#f45c43",
            })

        st.markdown('<div class="subsection">📂 카테고리별 예산 vs 실제</div>', unsafe_allow_html=True)
        show_table(pd.DataFrame(rows))

        # 막대그래프 — 예산(회색 외곽) vs 실제(색상 채움)
        cdf = pd.DataFrame(chart_rows)
        fig_bv = go.Figure()
        fig_bv.add_trace(go.Bar(
            name="예산", x=cdf["카테고리"], y=cdf["예산"],
            marker_color="rgba(180,180,180,0.5)",
            text=[f"{v:,.0f}원" for v in cdf["예산"]],
            textposition="outside", textfont_size=12, cliponaxis=False,
        ))
        fig_bv.add_trace(go.Bar(
            name="실제", x=cdf["카테고리"], y=cdf["실제"],
            marker_color=cdf["색상"],
            text=[f"{v:,.0f}원" for v in cdf["실제"]],
            textposition="outside", textfont_size=12, cliponaxis=False,
        ))
        fig_bv.update_layout(
            barmode="group", height=420,
            margin=dict(l=10, r=10, t=40, b=10),
            xaxis_title="", yaxis_title="원",
            xaxis=dict(tickfont=dict(size=13)),
            yaxis=dict(tickfont=dict(size=12), tickformat=",.0f"),
            legend=dict(font=dict(size=13)),
        )
        st.plotly_chart(fig_bv, use_container_width=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)


# ─── ② 재산 내역 (지금 기준 대분류) ───
st.markdown('<div class="section-title">💎 재산 내역 (지금 기준 대분류)</div>', unsafe_allow_html=True)
_assets = load_assets_detail()
_monthly = _assets.get("monthly", {})
_today_key = datetime.now().strftime("%Y-%m")
_asset_month = None
if _today_key in _monthly and _monthly[_today_key]:
    _asset_month = _today_key
else:
    candidates = sorted([m for m, rows in _monthly.items() if rows])
    if candidates:
        _asset_month = candidates[-1]

if _asset_month is None:
    st.info("재산 내역이 아직 입력되지 않았습니다. (기존 앱의 💎 재산 내역에서 입력)")
else:
    rows = _monthly[_asset_month]
    a_df = pd.DataFrame(rows)
    a_df["amount"] = pd.to_numeric(a_df["amount"], errors="coerce").fillna(0)
    by_cat = a_df.groupby("category")["amount"].sum().reset_index()
    by_cat.columns = ["대분류", "금액"]
    by_cat = by_cat.sort_values("금액", ascending=False)
    total_asset = by_cat["금액"].sum()
    by_cat["비중"] = (by_cat["금액"] / total_asset * 100).round(1) if total_asset > 0 else 0

    st.caption(f"기준 월: **{_asset_month}** · 총 자산 **{format_won_abs(total_asset)}**")

    a_left, a_right = st.columns([1, 1])
    with a_left:
        disp = by_cat.copy()
        disp["금액"] = disp["금액"].apply(lambda v: f"{v:,.0f}원")
        disp["비중"] = disp["비중"].apply(lambda v: f"{v}%")
        show_table(disp)
    with a_right:
        if total_asset > 0:
            fig_a = px.pie(by_cat, values="금액", names="대분류",
                           color_discrete_sequence=px.colors.qualitative.Pastel, hole=0.35)
            fig_a.update_traces(textposition="inside", textinfo="label+percent", textfont_size=13)
            fig_a.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                                legend=dict(font=dict(size=12)))
            st.plotly_chart(fig_a, use_container_width=True)

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)


# ─── ③ 수입 내역 ───
st.markdown('<div class="section-title">💰 수입 내역</div>', unsafe_allow_html=True)
if income_df.empty:
    st.caption("이번 달 수입 내역이 없습니다.")
else:
    inc_summary = income_df.groupby("소분류")["순수입(부호)"].sum().reset_index()
    inc_summary.columns = ["소분류", "금액"]
    inc_summary = inc_summary.sort_values("금액", ascending=False)
    for _, r in inc_summary.iterrows():
        sub = r["소분류"]
        amt = r["금액"]
        items = income_df[income_df["소분류"] == sub]
        st.markdown(f'<div class="subsection">💰 {sub} — {format_won_abs(amt)} ({len(items)}건)</div>', unsafe_allow_html=True)
        d = items[["날짜", "이름", "순수입(부호)", "사용처"]].copy()
        d.columns = ["날짜", "내용", "금액", "사용처"]
        d["금액"] = d["금액"].apply(lambda x: f"{x:,.0f}원")
        show_table(d)

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)


# ─── ④ 고정지출 내역 ───
st.markdown(f'<div class="section-title">🧾 고정지출 내역 — {format_won_abs(total_fixed)}</div>', unsafe_allow_html=True)
if fixed_df.empty:
    st.caption("이번 달 고정지출 내역이 없습니다.")
else:
    fx_summary = fixed_df.groupby("소분류")["실 사용"].sum().reset_index()
    fx_summary.columns = ["소분류", "금액"]
    fx_summary = fx_summary.sort_values("금액", ascending=False)
    for _, r in fx_summary.iterrows():
        sub = r["소분류"]; amt = r["금액"]
        items = fixed_df[fixed_df["소분류"] == sub]
        st.markdown(f'<div class="subsection">🧾 {sub} — {format_won_abs(amt)} ({len(items)}건)</div>', unsafe_allow_html=True)
        d = items[["날짜", "이름", "실 사용", "결제 방법", "결제 여부"]].copy()
        d.columns = ["날짜", "내용", "금액", "결제 방법", "결제 여부"]
        d["금액"] = d["금액"].apply(lambda x: f"{x:,.0f}원")
        show_table(d)

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)


# ─── ⑤ 변동지출 내역 ───
st.markdown(f'<div class="section-title">🔄 변동지출 내역 — {format_won_abs(total_variable)}</div>', unsafe_allow_html=True)
if variable_df.empty:
    st.caption("이번 달 변동지출 내역이 없습니다.")
else:
    var_major = variable_df.groupby("대분류")["실 사용"].sum().reset_index()
    var_major.columns = ["대분류", "금액"]
    var_major = var_major.sort_values("금액", ascending=False)
    for _, mrow in var_major.iterrows():
        major = mrow["대분류"]; mamt = mrow["금액"]
        mitems = variable_df[variable_df["대분류"] == major]
        st.markdown(f'<div class="subsection">{major} — {format_won_abs(mamt)} ({len(mitems)}건)</div>', unsafe_allow_html=True)
        d = mitems[["날짜", "이름", "실 사용", "소분류", "사용처", "결제 방법", "결제 여부"]].copy()
        d.columns = ["날짜", "내용", "금액", "소분류", "사용처", "결제 방법", "결제 여부"]
        d["금액"] = d["금액"].apply(lambda x: f"{x:,.0f}원")
        show_table(d)

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)


# ─── ⑥ 그래프 (대분류별 지출) ───
st.markdown('<div class="section-title">📈 그래프 — 어디에 얼마 썼나</div>', unsafe_allow_html=True)
exp_by_major = expense_df.groupby("대분류")["실 사용"].sum().reset_index()
exp_by_major.columns = ["대분류", "금액"]
exp_by_major = exp_by_major.sort_values("금액", ascending=False)

if exp_by_major.empty:
    st.caption("이번 달 지출 내역이 없습니다.")
else:
    g1, g2 = st.columns(2)
    with g1:
        fig_bar = px.bar(exp_by_major.sort_values("금액"), x="금액", y="대분류", orientation="h",
                         text="금액", color="대분류",
                         color_discrete_sequence=px.colors.qualitative.Set2)
        fig_bar.update_traces(texttemplate="%{text:,.0f}원", textposition="outside",
                              textfont_size=13, cliponaxis=False)
        fig_bar.update_layout(showlegend=False, height=400,
                              margin=dict(l=10, r=120, t=10, b=10),
                              xaxis_title="", yaxis_title="",
                              yaxis=dict(tickfont=dict(size=13)))
        st.plotly_chart(fig_bar, use_container_width=True)
    with g2:
        fig_pie = px.pie(exp_by_major, values="금액", names="대분류",
                         color_discrete_sequence=px.colors.qualitative.Set2, hole=0.3)
        fig_pie.update_traces(textposition="inside", textinfo="label+percent", textfont_size=13)
        fig_pie.update_layout(height=400, margin=dict(l=10, r=10, t=10, b=10),
                              legend=dict(font=dict(size=12)))
        st.plotly_chart(fig_pie, use_container_width=True)

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)


# ─── ⑦ 회고 (빈 칸 생략) ───
st.markdown(f'<div class="section-title">🪞 {selected_month} 회고</div>', unsafe_allow_html=True)
memo = load_memo(selected_month)

# 종합 회고 4종 — 빈 값 생략
overall = [
    ("💰 정산", memo.get("정산", "")),
    ("💬 피드백", memo.get("피드백", "")),
    ("🔧 개선점", memo.get("개선점", "")),
    ("✅ 지난 달 반영 내역", memo.get("지난 달 반영 내역", "")),
]
overall_filled = [(t, v) for t, v in overall if str(v).strip()]

# 카테고리별 회고 — 빈 값 생략
goal_memo = memo.get("목표 회고", {}) or {}
cat_filled = []
for k, v in goal_memo.items():
    if not str(v).strip():
        continue
    label = "전체" if k == "__total__" else k
    cat_filled.append((label, v))

if not overall_filled and not cat_filled:
    st.info("아직 작성된 회고가 없습니다.")
else:
    if overall_filled:
        st.markdown("**📝 종합 회고**")
        for title, txt in overall_filled:
            st.markdown(f"**{title}**")
            st.write(txt)
            st.markdown("")
    if cat_filled:
        st.markdown("**📂 카테고리별 회고**")
        for label, txt in cat_filled:
            st.markdown(f"**📂 {label}**")
            st.write(txt)
            st.markdown("")

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)


# ─── ⑧ 30년 로드맵 ───
st.markdown('<div class="section-title">🛤️ 30년 자산 로드맵</div>', unsafe_allow_html=True)
events, rate_changes, settings = load_roadmap_config()
birth_year = int(settings.get("birth_year", 1992))
start_asset = int(settings.get("roadmap_start_asset", 0))
annual_savings = int(settings.get("annual_savings", 0))
default_rate = float(settings.get("return_rate", 5.0))
years = int(settings.get("roadmap_years", 30))

if start_asset <= 0 and annual_savings <= 0:
    st.info("로드맵 설정이 비어있습니다. 기존 앱 사이드바에서 시작 자산/연 저축액을 입력해주세요.")
else:
    rm_rows = calc_roadmap(birth_year, start_asset, annual_savings, default_rate, events, rate_changes, years=years)
    rm_df = pd.DataFrame(rm_rows)

    st.caption(
        f"출생연도 **{birth_year}** · 시작 자산 **{format_won_abs(start_asset)}** · "
        f"연 저축 **{format_won_abs(annual_savings)}** · 기본 수익률 **{default_rate}%** · {years}년"
    )

    # ─── 마일스톤 (억 단위 돌파) — 원본 app.py와 동일 ───
    milestone_colors = {
        1: "#e8f5e9",   2: "#c8e6c9",   3: "#a5d6a7",
        5: "#81c784",   10: "#bbdefb",  20: "#90caf9",
        30: "#c5cae9",  50: "#ffccbc",  100: "#fff9c4",
    }

    def get_row_milestone(row_data, prev_total):
        cur = row_data["합계"]
        for target in sorted(milestone_colors.keys(), reverse=True):
            threshold = target * 100_000_000
            if cur >= threshold and prev_total < threshold:
                return target
        return None

    # 라인 그래프 — 마일스톤 별 + 이벤트 + 억 단위 기준선
    fig_line = go.Figure()
    fig_line.add_trace(go.Scatter(
        x=rm_df["년도"], y=rm_df["합계"], mode="lines+markers",
        name="연말 자산", line=dict(color="#667eea", width=3),
        marker=dict(size=7),
        hovertemplate="<b>%{x}년 (%{customdata}세)</b><br>자산: %{y:,.0f}원<extra></extra>",
        customdata=rm_df["나이"],
    ))

    # 마일스톤 마커 (별)
    ms_years, ms_totals, ms_texts, ms_marker_colors = [], [], [], []
    prev_t = 0
    for _, _row in rm_df.iterrows():
        ms = get_row_milestone(_row, prev_t)
        if ms:
            ms_years.append(_row["년도"])
            ms_totals.append(_row["합계"])
            ms_texts.append(f"🏆 {ms}억 돌파!")
            ms_marker_colors.append(milestone_colors.get(ms, "#667eea"))
        prev_t = _row["합계"]
    if ms_years:
        fig_line.add_trace(go.Scatter(
            x=ms_years, y=ms_totals, mode="markers+text", name="목표 달성",
            marker=dict(size=18, color=ms_marker_colors, symbol="star",
                        line=dict(width=2, color="#333")),
            text=ms_texts, textposition="top center", textfont=dict(size=13, color="#333"),
        ))

    # 이벤트 마커 (다이아몬드)
    ev_df = rm_df[rm_df["이벤트"] != ""]
    if not ev_df.empty:
        fig_line.add_trace(go.Scatter(
            x=ev_df["년도"], y=ev_df["합계"], mode="markers+text",
            name="이벤트", marker=dict(size=14, color="#f45c43", symbol="diamond"),
            text=ev_df["이벤트"], textposition="bottom center", textfont=dict(size=12),
        ))

    # 억 단위 기준선
    min_a = rm_df["합계"].min()
    max_a = rm_df["합계"].max()
    for target in sorted(milestone_colors.keys()):
        threshold = target * 100_000_000
        if min_a * 0.8 <= threshold <= max_a * 1.2:
            fig_line.add_hline(
                y=threshold, line_dash="dash", line_color="rgba(0,0,0,0.15)",
                annotation_text=f"{target}억", annotation_position="right",
            )

    fig_line.update_layout(
        height=520, margin=dict(l=10, r=60, t=30, b=20),
        xaxis_title="년도", yaxis_title="자산 (원)",
        xaxis=dict(tickfont=dict(size=13)),
        yaxis=dict(tickformat=",", tickfont=dict(size=12)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=12)),
    )
    st.plotly_chart(fig_line, use_container_width=True)

    # 행 수 검증 — 30년이 다 안 나오면 경고 표시
    _expected = years
    _actual = len(rm_df)
    if _actual != _expected:
        st.warning(f"⚠️ 예상 {_expected}년치인데 {_actual}행만 생성됨 — 데이터 확인 필요")
    else:
        st.caption(f"✅ {_actual}년치 모두 표시 (1년차 ~ {_actual}년차)")

    # ─── 표 — 마일스톤 행 색상 + 1억 돌파 뱃지 (HTML 직접 생성, 원본 app.py와 동일) ───
    td_base = "padding:12px 14px; border-bottom:1px solid #eee; white-space:nowrap; text-align:center; font-size:1.05rem;"
    th_base = "padding:14px 14px; border-bottom:2px solid #ddd; text-align:center; white-space:nowrap; font-size:1.05rem; font-weight:bold;"

    table_html = '<div style="overflow-x:auto;">'
    table_html += '<table style="width:100%; border-collapse:collapse; margin:0 auto;">'
    table_html += '<thead><tr style="background:#f0f2f6;">'
    for col in ["회차", "년도", "나이", "보유 자산", "저축액", "수익률", "이벤트", "이벤트 금액", "합계"]:
        table_html += f'<th style="{th_base}">{col}</th>'
    table_html += '</tr></thead><tbody>'

    prev_total = 0
    for i, row in rm_df.iterrows():
        ms = get_row_milestone(row, prev_total)
        bg = milestone_colors.get(ms, "transparent") if ms else "transparent"
        fw = "font-weight:bold;" if ms else ""
        ms_badge = f' 🏆 {ms}억 돌파!' if ms else ""

        ev_text = row["이벤트"] if row["이벤트"] else "-"
        ev_amount = f'{row["이벤트 금액"]:+,.0f}원' if row["이벤트 금액"] != 0 else "-"
        ev_color = "#d32f2f" if row["이벤트 금액"] < 0 else "#2e7d32" if row["이벤트 금액"] > 0 else ""

        table_html += f'<tr style="background-color:{bg};{fw}">'
        table_html += f'<td style="{td_base}">{i+1}년차</td>'
        table_html += f'<td style="{td_base}">{row["년도"]}</td>'
        table_html += f'<td style="{td_base}">{row["나이"]}세</td>'
        table_html += f'<td style="{td_base}">{row["보유 자산"]:,.0f}원</td>'
        table_html += f'<td style="{td_base}">{row["저축액"]:,.0f}원</td>'
        table_html += f'<td style="{td_base}">{row["수익률"]}%</td>'
        table_html += f'<td style="{td_base}">{ev_text}</td>'
        table_html += f'<td style="{td_base} color:{ev_color};">{ev_amount}</td>'
        table_html += f'<td style="{td_base}">{row["합계"]:,.0f}원{ms_badge}</td>'
        table_html += '</tr>'
        prev_total = row["합계"]

    table_html += '</tbody></table></div>'
    st.markdown(table_html, unsafe_allow_html=True)

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
st.caption("👆 이 페이지를 그대로 인쇄(Ctrl+P)하면 PDF로 한 장 요약 저장됩니다.")
