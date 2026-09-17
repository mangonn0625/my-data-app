"""
KOBIS(영화진흥위원회) 일별 박스오피스 조회 앱
-------------------------------------------------
스트림릿 클라우드 배포를 전제로 작성했습니다.

배포 전 준비물:
  1) 스트림릿 클라우드 앱 설정 > Secrets 에 아래처럼 등록해 주세요.
       KOBIS_KEY = "여기에_발급받은_인증키"
  2) requirements.txt 를 함께 올려 주세요.
"""

import datetime as dt   # 날짜/시간 계산용
import requests         # KOBIS API 호출용
import pandas as pd     # 표 정리용
import streamlit as st  # 화면 구성용

try:
    from zoneinfo import ZoneInfo  # 파이썬 3.9+ 기본 내장, 시간대 계산용
except ImportError:
    ZoneInfo = None


# -----------------------------------------------------------------
# 1) 화면 기본 설정
# -----------------------------------------------------------------
st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")
st.title("🎬 어제의 일별 박스오피스")


# -----------------------------------------------------------------
# 2) 인증키 가져오기 (절대 코드에 직접 쓰지 않음)
# -----------------------------------------------------------------
def get_api_key() -> str | None:
    """secrets 금고에서 KOBIS_KEY 값을 꺼내 옵니다. 없으면 None을 돌려줍니다."""
    try:
        return st.secrets["KOBIS_KEY"]
    except Exception:
        return None


# -----------------------------------------------------------------
# 3) '어제' 날짜를 한국 시간(KST) 기준으로 계산
#    - 배포 서버의 시계는 한국 시간이 아닐 수 있으므로,
#      반드시 시간대를 명시해서 계산해야 합니다.
# -----------------------------------------------------------------
def get_yesterday_kst() -> str:
    """한국 시간 기준 '어제' 날짜를 yyyymmdd 형식 문자열로 돌려줍니다."""
    if ZoneInfo is not None:
        now_kst = dt.datetime.now(ZoneInfo("Asia/Seoul"))
    else:
        # 혹시 zoneinfo를 못 쓰는 아주 예전 환경이면, UTC+9로 직접 보정합니다.
        now_kst = dt.datetime.utcnow() + dt.timedelta(hours=9)

    yesterday = now_kst.date() - dt.timedelta(days=1)
    return yesterday.strftime("%Y%m%d")


# -----------------------------------------------------------------
# 4) KOBIS API 호출 (같은 날짜는 1시간 동안 캐시해서 재호출 방지)
#    - st.cache_data의 ttl=3600 옵션이 "1시간 동안 결과를 기억"하는 역할입니다.
#    - target_dt 값이 같으면 캐시된 결과를 그대로 재사용합니다.
# -----------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner="박스오피스 정보를 불러오는 중...")
def fetch_box_office(target_dt: str, api_key: str) -> dict:
    """
    KOBIS 일별 박스오피스 API를 호출합니다.
    반환값은 항상 아래 형태의 딕셔너리입니다.
      {"ok": True,  "movies": [...]}                 -> 정상
      {"ok": False, "message": "사람이 읽을 안내문구"}  -> 실패
    """
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
    params = {"key": api_key, "targetDt": target_dt}

    # 4-1) 네트워크 요청 자체가 실패하는 경우 (타임아웃, 접속 불가 등)
    try:
        response = requests.get(url, params=params, timeout=10)
    except requests.exceptions.RequestException:
        return {
            "ok": False,
            "message": (
                "KOBIS 서버에 접속하지 못했습니다. "
                "인터넷 연결 상태와 방화벽/네트워크 설정을 확인해 주세요."
            ),
        }

    # 4-2) HTTP 상태코드가 200이 아닌 경우
    if response.status_code != 200:
        return {
            "ok": False,
            "message": (
                f"KOBIS 서버가 오류를 돌려주었습니다 (상태코드 {response.status_code}). "
                "잠시 후 다시 시도해 주세요."
            ),
        }

    # 4-3) 응답이 JSON 형식이 아닌 경우
    try:
        data = response.json()
    except ValueError:
        return {
            "ok": False,
            "message": "KOBIS 서버 응답을 해석할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        }

    # 4-4) 인증키가 틀린 경우: 상태코드는 200이지만 faultInfo 상자가 옴
    if "faultInfo" in data:
        fault = data["faultInfo"]
        reason = fault.get("message", "알 수 없는 오류")
        return {
            "ok": False,
            "message": (
                f"KOBIS API가 오류를 반환했습니다: {reason}\n"
                "→ secrets에 등록한 KOBIS_KEY 값이 정확한지, "
                "발급받은 인증키가 맞는지 확인해 주세요."
            ),
        }

    # 4-5) 정상 응답이라면 boxOfficeResult > dailyBoxOfficeList 를 꺼냄
    try:
        movies = data["boxOfficeResult"]["dailyBoxOfficeList"]
    except (KeyError, TypeError):
        return {
            "ok": False,
            "message": (
                "응답 안에서 박스오피스 목록(boxOfficeResult)을 찾지 못했습니다. "
                "KOBIS API 응답 형식이 바뀌었을 수 있으니 문서를 다시 확인해 주세요."
            ),
        }

    # 4-6) 영화 목록이 비어 있는 경우 (예: 해당 날짜 데이터가 아직 없음)
    if not movies:
        return {
            "ok": False,
            "message": (
                "해당 날짜의 박스오피스 데이터가 비어 있습니다. "
                "아직 집계가 완료되지 않았을 수 있으니 잠시 후 다시 시도해 주세요."
            ),
        }

    return {"ok": True, "movies": movies}


# -----------------------------------------------------------------
# 5) API가 돌려준 문자열 숫자들을 진짜 숫자(int)로 바꾸고,
#    화면에 쓰기 좋은 표(DataFrame)로 정리
# -----------------------------------------------------------------
def to_dataframe(movies: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(movies)

    # 정렬/그래프에 쓸 숫자 컬럼들은 문자열 -> 정수로 변환
    numeric_cols = ["rank", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # 순위 기준으로 정렬 (혹시 API 응답 순서가 흐트러져 있을 경우 대비)
    df = df.sort_values("rank").reset_index(drop=True)
    return df


# -----------------------------------------------------------------
# 6) 실제 화면 그리기
# -----------------------------------------------------------------
def main():
    api_key = get_api_key()

    if not api_key:
        st.error(
            "KOBIS_KEY가 설정되어 있지 않습니다.\n\n"
            "스트림릿 클라우드 앱 설정(Settings) > Secrets 메뉴에서 아래처럼 등록해 주세요.\n\n"
            'KOBIS_KEY = "발급받은_인증키"'
        )
        st.stop()

    target_dt = get_yesterday_kst()
    st.caption(f"조회 기준일 (한국 시간 기준 어제): {target_dt}")

    result = fetch_box_office(target_dt, api_key)

    # 실패 케이스: 빈 화면 대신 안내 문구를 보여 줌
    if not result["ok"]:
        st.error(result["message"])
        st.stop()

    df = to_dataframe(result["movies"])

    # --- 6-1) 1위 영화 지표 카드 3장 ---
    top_movie = df.iloc[0]
    st.subheader(f"🏆 1위: {top_movie['movieNm']}")

    col1, col2, col3 = st.columns(3)
    col1.metric("오늘 관객수", f"{top_movie['audiCnt']:,} 명")
    col2.metric("누적 관객수", f"{top_movie['audiAcc']:,} 명")
    col3.metric("스크린수", f"{top_movie['scrnCnt']:,} 개")

    st.divider()

    # --- 6-2) 관객수 상위 5편 막대그래프 ---
    st.subheader("📊 관객수 상위 5편")
    top5 = df.sort_values("audiCnt", ascending=False).head(5)
    chart_data = top5.set_index("movieNm")["audiCnt"]
    st.bar_chart(chart_data)

    st.divider()

    # --- 6-3) 전체 목록 표 ---
    st.subheader("📋 전체 박스오피스 순위")
    table_df = df[["rank", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].copy()
    table_df.columns = ["순위", "영화명", "개봉일", "관객수", "누적관객", "스크린수"]
    st.dataframe(table_df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
