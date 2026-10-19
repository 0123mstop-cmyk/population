# -*- coding: utf-8 -*-
"""
전국 고령화 단계구분도 (스트림릿 앱)
- 2026년 읍·면·동 인구를 시군구 단위로 묶어서 '65세 이상 비율(%)'을 계산하고,
  시군구 경계 지도 위에 진하기로 보여줍니다. (높을수록 진하게)
- 지역은 이름이 아니라 '코드(5자리)'로 짝지어요. 이름은 같은 곳이 많아서(중구, 동구 ...) 위험하거든요.
"""

import json

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# ------------------------------------------------------------------
# 1. 기본 설정
# ------------------------------------------------------------------

# 깃허브 '원본(raw)' 주소예요. (화면용 blob 주소는 HTML 페이지라 읽을 수 없어요)
POP_URL = (
    "https://raw.githubusercontent.com/0123mstop-cmyk/population/main/"
    "population_ts_yearly_gender.zip"
)
GEO_URL = (
    "https://raw.githubusercontent.com/0123mstop-cmyk/population/main/"
    "sigungu_kr.geojson.txt"
)

TARGET_YEAR = 2026  # 이 해(6월 기준) 데이터만 사용해요

# 나이 이름: 0세, 1세, ... 99세, 100세 이상
AGE_NAMES = [f"{n}세" for n in range(100)] + ["100세 이상"]
# 65세 이상 열: 계_65세 ~ 계_99세, 계_100세 이상 (AGE_NAMES[65:]가 65세부터 끝까지예요)
AGED_COLS = [f"계_{a}" for a in AGE_NAMES[65:]]

st.set_page_config(page_title="전국 고령화 단계구분도", page_icon="🗺️", layout="wide")


# ------------------------------------------------------------------
# 2. 인구 데이터 → 시군구별 65세 이상 비율
# ------------------------------------------------------------------

def _is_needed_column(col: str) -> bool:
    """CSV에서 꼭 필요한 열만 읽어서 메모리를 아껴요. (남_·여_ 열은 아예 읽지 않아요)"""
    return col in ("연도", "시도", "시군구", "동", "코드") or col.startswith("계_")


@st.cache_data(show_spinner="인구 데이터를 불러오는 중이에요...")
def load_aging_rate() -> tuple[pd.DataFrame, int, float]:
    """시군구 코드(5자리)별 고령화율(%)과 '계_' 열 개수, 전국 고령화율을 돌려줘요."""
    # 한글 CSV는 인코딩이 제각각이라, 안 읽히면 다음 인코딩으로 다시 시도해요.
    df = None
    for enc in ("utf-8", "utf-8-sig", "cp949"):
        try:
            # dtype={"코드": str} : 코드를 숫자가 아닌 '문자열'로 읽어요 (앞자리 0이 사라지지 않게)
            df = pd.read_csv(POP_URL, encoding=enc, usecols=_is_needed_column, dtype={"코드": str})
            break
        except UnicodeDecodeError:
            continue
    if df is None:
        raise ValueError("CSV 인코딩을 알 수 없어요.")

    # '연도' 열에서 숫자 4자리만 뽑아서(2026, '2026년', '2026-06' 모두 OK) 2026년만 남겨요
    year = pd.to_numeric(df["연도"].astype(str).str.extract(r"(\d{4})")[0], errors="coerce")
    df = df[year == TARGET_YEAR].dropna(subset=["코드"])
    if df.empty:
        raise ValueError(f"{TARGET_YEAR}년 데이터가 없어요.")

    # '계_'로 시작하는 모든 열 = 전체 인구 계산에 쓸 열
    total_cols = [c for c in df.columns if c.startswith("계_")]
    missing = [c for c in AGED_COLS if c not in df.columns]
    if missing:
        raise KeyError(f"데이터에 없는 열이 있어요: {missing[:3]} ...")

    # 인구 열을 숫자로 바꿔요 ('1,234' 같은 쉼표도 처리, 빈칸은 0)
    people = df[total_cols].apply(
        lambda s: pd.to_numeric(s.astype(str).str.replace(",", "", regex=False), errors="coerce")
    ).fillna(0)

    # 동 코드의 앞 5자리 = 시군구 코드. 같은 시군구끼리 묶어서 더해요.
    table = pd.DataFrame({
        "코드": df["코드"].astype(str).str.strip().str[:5],
        "고령": people[AGED_COLS].sum(axis=1),   # 65세 이상 인구
        "전체": people.sum(axis=1),               # 전체 인구 ('계_' 열 전부의 합)
    })
    grouped = table.groupby("코드", as_index=False).sum()

    national = grouped["고령"].sum() / grouped["전체"].sum() * 100  # 전국 고령화율
    grouped = grouped[grouped["전체"] > 0].copy()                   # 인구 0명 지역은 비율을 못 구해서 제외
    grouped["고령화율"] = grouped["고령"] / grouped["전체"] * 100   # 65세 이상 비율(%)

    return grouped[["코드", "고령화율"]], len(total_cols), float(national)


# ------------------------------------------------------------------
# 3. 시군구 경계(GeoJSON) 불러오기
# ------------------------------------------------------------------

@st.cache_data(show_spinner="지도 경계를 불러오는 중이에요...")
def load_geojson() -> tuple[dict, pd.DataFrame]:
    """requests로 내려받아 JSON으로 읽고, 지역 목록(코드·시군구·시도)도 함께 돌려줘요."""
    resp = requests.get(GEO_URL, timeout=60)
    resp.raise_for_status()  # 주소가 틀렸거나 막혔으면 여기서 오류를 내요
    # .txt 파일이라 글자 깨짐을 막으려고 utf-8로 직접 해석해요 (맨 앞 BOM 표시도 제거)
    geojson = json.loads(resp.content.decode("utf-8-sig"))

    rows = []
    for feature in geojson["features"]:
        props = feature["properties"]
        # 경계의 '코드'도 문자열로 통일해요 (숫자로 들어있어도 문자열로 맞춰서 정확히 짝짓기 위해)
        props["코드"] = str(props["코드"]).strip()
        rows.append({"코드": props["코드"], "시군구": props["시군구"], "시도": props["시도"]})

    return geojson, pd.DataFrame(rows)


# ------------------------------------------------------------------
# 4. 단계구분도 그리기
# ------------------------------------------------------------------

def make_map(geojson: dict, merged: pd.DataFrame) -> go.Figure:
    """고령화율이 높을수록 진하게 칠한 지도를 만들어요. (배경 지도 타일 없음)"""
    fig = go.Figure(
        go.Choropleth(
            geojson=geojson,
            locations=merged["코드"],          # 색칠할 지역의 코드 (문자열)
            featureidkey="properties.코드",    # 경계 파일의 '코드' 속성과 짝짓기
            z=merged["고령화율"],               # 이 값이 클수록 진하게 칠해져요
            customdata=merged[["시군구"]],      # 마우스를 올렸을 때 보여줄 이름
            colorscale="Oranges",              # 연한 주황 → 진한 주황 (높을수록 진함)
            marker_line_color="white",         # 경계선은 흰색 얇은 선
            marker_line_width=0.4,
            colorbar=dict(title="65세 이상<br>비율", ticksuffix="%"),
            hovertemplate="<b>%{customdata[0]}</b><br>고령화율 %{z:.1f}%<extra></extra>",
        )
    )
    # fitbounds: 지도를 경계에 딱 맞게 확대 / visible=False: 위경도 격자·바다색 같은 배경을 숨겨요
    fig.update_geos(fitbounds="locations", visible=False)
    fig.update_layout(
        height=800,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ------------------------------------------------------------------
# 5. 화면 구성
# ------------------------------------------------------------------

st.title("🗺️ 전국 고령화 단계구분도")

try:
    aging, n_total_cols, national_rate = load_aging_rate()
    geojson, regions = load_geojson()
except Exception as e:  # 데이터를 못 읽었을 때 친절하게 알려줘요
    st.error(f"데이터를 불러오지 못했어요: {e}")
    st.stop()

# 경계 지역(코드·시군구)에 고령화율을 코드로 붙여요 (둘 다 문자열 코드라 정확히 맞아요)
merged = regions.merge(aging, on="코드", how="inner")
if merged.empty:
    st.error("경계 파일과 인구 데이터의 코드가 하나도 맞지 않아요. 코드 형식을 확인해 주세요.")
    st.stop()

st.caption(
    f"{TARGET_YEAR}년 6월 기준 · 시군구별 65세 이상 인구 비율(%) · "
    f"전국 {national_rate:.1f}% · 색이 진할수록 고령화율이 높아요."
)

# '계_' 열이 101개(0세~100세 이상)가 아니면 합계 열이 섞였을 수 있어서 알려드려요
if n_total_cols != len(AGE_NAMES):
    st.warning(
        f"'계_'로 시작하는 열이 {n_total_cols}개예요 (나이별 열은 {len(AGE_NAMES)}개). "
        "합계 같은 다른 열이 섞여 있으면 비율이 틀릴 수 있어요."
    )

# 코드가 서로 안 맞은 지역이 있으면 몇 곳인지 알려줘요
only_geo = len(regions) - len(merged)
only_pop = len(aging) - len(merged)
if only_geo or only_pop:
    st.caption(
        f"참고: 경계에는 있지만 인구 데이터에 없는 지역 {only_geo}곳, "
        f"인구 데이터에는 있지만 경계에 없는 지역 {only_pop}곳은 지도에서 빠져요."
    )

st.plotly_chart(make_map(geojson, merged), use_container_width=True)
