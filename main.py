# -*- coding: utf-8 -*-
"""
동네별 인구 피라미드 (스트림릿 앱)
- 시도 → 시군구 → 동 순서로 고르면, 그 동네의 인구 피라미드를 보여줍니다.
- 데이터: 2015~2026년 전국 읍·면·동 성별·나이별 인구 (가장 최신 연도만 사용)
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ------------------------------------------------------------------
# 1. 기본 설정
# ------------------------------------------------------------------

# 데이터 주소 (깃허브 '원본(raw)' 주소예요. 화면용 blob 주소는 HTML이라 판다스가 못 읽어요)
DATA_URL = (
    "https://raw.githubusercontent.com/0123mstop-cmyk/population/main/"
    "population_ts_yearly_gender.zip"
)

# 나이 라벨: 0세, 1세, ... 99세, 100세 이상 (이 순서가 그래프 세로축 순서가 됩니다)
AGE_LABELS = [f"{n}세" for n in range(100)] + ["100세 이상"]

# 따뜻한 톤 색상
COLOR_MALE = "#6F9A8D"     # 차분한 세이지 그린 (남자)
COLOR_FEMALE = "#E07A5F"   # 부드러운 테라코타 (여자)
COLOR_BG = "#FFF8F0"       # 따뜻한 크림색 배경
COLOR_TEXT = "#5A4636"     # 따뜻한 갈색 글씨
COLOR_GRID = "#EADCCB"     # 연한 베이지 눈금선

st.set_page_config(page_title="동네별 인구 피라미드", page_icon="🏘️", layout="wide")


# ------------------------------------------------------------------
# 2. 데이터 불러오기
# ------------------------------------------------------------------

@st.cache_data(show_spinner="인구 데이터를 불러오는 중이에요...")
def load_latest_data() -> tuple[pd.DataFrame, int]:
    """CSV(zip)를 읽어서 '가장 최신 연도'의 행만 돌려줍니다."""
    # 한글 CSV는 인코딩이 제각각이라, 안 읽히면 다음 인코딩으로 다시 시도해요.
    df = None
    for enc in ("utf-8", "utf-8-sig", "cp949"):
        try:
            df = pd.read_csv(DATA_URL, encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if df is None:
        raise ValueError("CSV 인코딩을 알 수 없어요.")

    # 연도 열에서 숫자 4자리만 뽑아서 정수로 바꿔요 ('2026' 이든 '2026년' 이든 OK)
    df["연도"] = pd.to_numeric(df["연도"].astype(str).str.extract(r"(\d{4})")[0])

    # 가장 최신 연도만 남기기
    latest_year = int(df["연도"].max())
    df = df[df["연도"] == latest_year].copy()

    # 시도·시군구·동이 비어 있는 행(합계 행 등)은 빼요
    df = df.dropna(subset=["시도", "시군구", "동"])

    # 인구 열(남_0세 ... 여_100세 이상)을 숫자로 바꿔요 ('1,234' 같은 쉼표도 처리)
    pop_cols = [f"{g}_{a}" for g in ("남", "여") for a in AGE_LABELS]
    missing = [c for c in pop_cols if c not in df.columns]
    if missing:
        raise KeyError(f"데이터에 없는 열이 있어요: {missing[:5]} ...")
    for col in pop_cols:
        df[col] = pd.to_numeric(
            df[col].astype(str).str.replace(",", "", regex=False), errors="coerce"
        ).fillna(0)

    return df, latest_year


# ------------------------------------------------------------------
# 3. 지표 계산 (평균연령, 고령화율, 한 줄 설명)
# ------------------------------------------------------------------

# 나이 숫자 목록: 0, 1, ... 100 (AGE_LABELS와 같은 순서, 마지막 100은 '100세 이상'을 뜻해요)
AGES = list(range(101))

AGING_WARNING_LIMIT = 20  # 고령화율이 이 값(%)을 넘으면 주의 표시를 붙여요


def calc_stats(male: list, female: list):
    """총인구·평균연령·고령화율·어린이 비율을 계산해요. 인구가 0명이면 None을 돌려줘요."""
    # 나이별 인구 = 남자 + 여자
    people = [m + f for m, f in zip(male, female)]
    total = sum(people)
    if total <= 0:
        return None

    # 평균연령 = (나이 × 그 나이 인구)를 모두 더한 값 ÷ 총인구
    # ('100세 이상'은 100세로 계산하므로 실제보다 아주 조금 낮게 나올 수 있어요)
    avg_age = sum(a * p for a, p in zip(AGES, people)) / total

    # 고령화율 = 65세 이상 인구 ÷ 총인구 × 100
    aged_pct = sum(people[65:]) / total * 100
    # 어린이(0~14세) 비율도 구해둬요 (한 줄 설명에 써요)
    child_pct = sum(people[:15]) / total * 100

    return {"total": int(total), "avg_age": avg_age, "aged_pct": aged_pct, "child_pct": child_pct}


def make_description(child_pct: float, aged_pct: float) -> str:
    """어린이(0~14세) 비율과 어르신(65세 이상) 비율을 비교해서 한 줄 설명을 만들어요."""
    gap = child_pct - aged_pct  # 양수면 어린이가 더 많고, 음수면 어르신이 더 많아요
    numbers = f"(어린이 0~14세 {child_pct:.1f}% · 어르신 65세 이상 {aged_pct:.1f}%)"
    if gap >= 3:
        return f"👶 이 동네는 아이들이 어르신보다 많은 편이에요. {numbers}"
    if gap <= -3:
        return f"🌳 이 동네는 아이들보다 어르신이 많은 편이에요. {numbers}"
    return f"🏡 이 동네는 아이들과 어르신이 비슷하게 어우러져 있어요. {numbers}"


# ------------------------------------------------------------------
# 4. 인구 피라미드 그래프 만들기
# ------------------------------------------------------------------

def make_pyramid(male: list, female: list, title: str) -> go.Figure:
    """남자(왼쪽, 음수)·여자(오른쪽, 양수) 가로 막대그래프를 만들어요."""
    male_neg = [-v for v in male]  # 남자는 왼쪽에 그리려고 값을 음수로 바꿔요

    fig = go.Figure()
    fig.add_bar(
        y=AGE_LABELS, x=male_neg, orientation="h", name="남자",
        marker_color=COLOR_MALE,
        customdata=male,  # 마우스를 올렸을 때는 양수로 보여주려고 따로 저장
        hovertemplate="%{y} 남자: %{customdata:,.0f}명<extra></extra>",
    )
    fig.add_bar(
        y=AGE_LABELS, x=female, orientation="h", name="여자",
        marker_color=COLOR_FEMALE,
        hovertemplate="%{y} 여자: %{x:,.0f}명<extra></extra>",
    )

    # 가로축 눈금: 가장 큰 값을 기준으로 좌우 대칭이 되게 하고, 눈금 글씨는 양수로 표시해요
    biggest = max(max(male), max(female), 1)
    # 눈금 간격(step)은 반드시 정수여야 해서 int()로 감싸요 (range()에는 정수만 들어가요)
    step = int(max(1, round(biggest / 3, -len(str(int(biggest / 3))) + 1)))  # 보기 좋은 간격
    limit = step * 4
    ticks = list(range(-limit, limit + 1, step))

    fig.update_layout(
        title=dict(text=title, x=0.5, font=dict(size=20, color=COLOR_TEXT)),
        barmode="overlay",   # 남녀 막대를 같은 줄에 겹쳐서(좌/우로 갈라서) 그려요
        bargap=0.1,
        height=800,
        paper_bgcolor=COLOR_BG,
        plot_bgcolor=COLOR_BG,
        font=dict(color=COLOR_TEXT),
        legend=dict(orientation="h", y=1.04, x=0.5, xanchor="center"),
        margin=dict(l=70, r=30, t=90, b=60),
        xaxis=dict(
            title="인구 (명)",
            range=[-limit, limit],
            tickvals=ticks,
            ticktext=[f"{abs(t):,}" for t in ticks],  # 음수 기호 없이 표시
            gridcolor=COLOR_GRID,
            zeroline=True, zerolinecolor=COLOR_TEXT,
        ),
        yaxis=dict(
            title="나이",
            # ★ 세로축 순서 고정: 나이 라벨을 0세 → 100세 이상 순서 그대로 지정해요.
            #   (축 뒤집기 옵션이나 값 크기순 정렬은 쓰지 않아요)
            #   막대그래프의 첫 번째 라벨(0세)이 맨 아래, 마지막(100세 이상)이 맨 위에 와요.
            type="category",
            categoryorder="array",
            categoryarray=AGE_LABELS,
            # 눈금은 10살 단위 + 마지막 라벨만 보여줘서 글씨가 겹치지 않게 해요
            tickmode="array",
            tickvals=[a for i, a in enumerate(AGE_LABELS) if i % 10 == 0 or i == 100],
            gridcolor=COLOR_GRID,
        ),
    )
    return fig


# ------------------------------------------------------------------
# 5. 화면 구성
# ------------------------------------------------------------------

st.title("🏘️ 동네별 인구 피라미드")

try:
    data, latest_year = load_latest_data()
except Exception as e:  # 데이터를 못 읽었을 때 친절하게 알려줘요
    st.error(f"데이터를 불러오지 못했어요: {e}")
    st.stop()

st.caption(f"{latest_year}년 기준 · 시도 → 시군구 → 동 순서로 골라보세요.")

# 드롭다운 3개를 한 줄에 나란히 놓아요
col1, col2, col3 = st.columns(3)

with col1:
    sido_list = sorted(data["시도"].unique())
    sido = st.selectbox("시도", sido_list)

with col2:
    # 고른 시도에 속한 시군구만 보여줘요
    sigungu_list = sorted(data.loc[data["시도"] == sido, "시군구"].unique())
    sigungu = st.selectbox("시군구", sigungu_list)

with col3:
    # 고른 시도·시군구에 속한 동만 보여줘요
    dong_list = sorted(
        data.loc[(data["시도"] == sido) & (data["시군구"] == sigungu), "동"].unique()
    )
    dong = st.selectbox("동", dong_list)

# 고른 동네의 행을 찾아요 (같은 이름의 행이 여러 개면 합쳐요)
picked = data[(data["시도"] == sido) & (data["시군구"] == sigungu) & (data["동"] == dong)]
male_values = [float(picked[f"남_{a}"].sum()) for a in AGE_LABELS]
female_values = [float(picked[f"여_{a}"].sum()) for a in AGE_LABELS]

# 지표 계산 (인구가 0명인 동네는 stats가 None이에요)
stats = calc_stats(male_values, female_values)

# 지표 카드 3개를 나란히 놓아요. 네 번째 칸은 '주의 표시'가 들어갈 자리예요.
card1, card2, card3, notice = st.columns([3, 3, 3, 2])

if stats is None:
    card1.metric("총인구", "0명")
    card2.metric("평균연령", "-")
    card3.metric("고령화율 (65세 이상)", "-")
else:
    card1.metric("총인구", f"{stats['total']:,}명")
    card2.metric("평균연령", f"{stats['avg_age']:.1f}세")
    card3.metric("고령화율 (65세 이상)", f"{stats['aged_pct']:.1f}%")

    # 고령화율이 20%를 넘으면 고령화율 카드 옆에 주의 표시를 붙여요
    if stats["aged_pct"] > AGING_WARNING_LIMIT:
        notice.warning(f"⚠️ 주의\n\n고령화율 {AGING_WARNING_LIMIT}% 초과")

# 그래프 그리기
fig = make_pyramid(male_values, female_values, f"{sido} {sigungu} {dong} 인구 피라미드 ({latest_year}년)")
st.plotly_chart(fig, use_container_width=True)

# 피라미드 아래 한 줄 설명
if stats is None:
    st.info("이 동네는 인구 정보가 없어서 설명을 드리기 어려워요.")
else:
    st.info(make_description(stats["child_pct"], stats["aged_pct"]))
