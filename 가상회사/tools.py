"""
직원들이 사용할 수 있는 도구 모음
- 웹 검색 (DuckDuckGo, 무료)
- 네이버 검색 (네이버 검색 API)
- 다음/브런치 검색 (카카오 검색 API)
"""
import json
import os
import urllib.request
import urllib.parse

# ── 네이버 API 키 로드 ──────────────────────────────
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_NAVER_API_FILE = os.path.join(_BASE_DIR, ".naver_api")

NAVER_CLIENT_ID = ""
NAVER_CLIENT_SECRET = ""

if os.path.exists(_NAVER_API_FILE):
    with open(_NAVER_API_FILE, "r", encoding="utf-8") as _f:
        _lines = _f.read().strip().splitlines()
        if len(_lines) >= 2:
            NAVER_CLIENT_ID = _lines[0].strip()
            NAVER_CLIENT_SECRET = _lines[1].strip()


# ── 카카오 API 키 로드 ──────────────────────────────
_KAKAO_API_FILE = os.path.join(_BASE_DIR, ".kakao_api")

KAKAO_REST_KEY = ""

if os.path.exists(_KAKAO_API_FILE):
    with open(_KAKAO_API_FILE, "r", encoding="utf-8") as _f:
        KAKAO_REST_KEY = _f.read().strip()


def web_search(query: str, max_results: int = 5, region: str = "kr-kr") -> str:
    """DuckDuckGo 웹 검색 (무료, API 키 불필요)"""
    try:
        from ddgs import DDGS
        results = DDGS().text(query, max_results=max_results, region=region)
        if not results:
            return "검색 결과가 없습니다."

        output = []
        for i, r in enumerate(results, 1):
            output.append(f"[{i}] {r['title']}\n    {r['href']}\n    {r['body']}")
        return "\n\n".join(output)
    except Exception as e:
        return f"검색 오류: {e}"


def _naver_api_search(query: str, search_type: str = "blog", display: int = 5) -> str:
    """네이버 검색 API 호출 (blog, news, webkr 등)"""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return "네이버 API 키가 설정되지 않았습니다. .naver_api 파일을 확인하세요."

    url = f"https://openapi.naver.com/v1/search/{search_type}.json"
    params = urllib.parse.urlencode({"query": query, "display": display, "sort": "sim"})
    req = urllib.request.Request(f"{url}?{params}")
    req.add_header("X-Naver-Client-Id", NAVER_CLIENT_ID)
    req.add_header("X-Naver-Client-Secret", NAVER_CLIENT_SECRET)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return f"네이버 API 오류: {e}"

    items = data.get("items", [])
    if not items:
        return "검색 결과가 없습니다."

    output = []
    for i, item in enumerate(items, 1):
        # HTML 태그 제거
        title = item.get("title", "").replace("<b>", "").replace("</b>", "")
        desc = item.get("description", "").replace("<b>", "").replace("</b>", "")
        link = item.get("link", "")
        # 블로그는 블로거 이름/날짜 추가
        blogger = item.get("bloggername", "")
        postdate = item.get("postdate", "")
        extra = ""
        if blogger:
            extra += f"\n    작성자: {blogger}"
        if postdate:
            extra += f" | 날짜: {postdate[:4]}-{postdate[4:6]}-{postdate[6:]}"
        output.append(f"[{i}] {title}\n    {link}\n    {desc}{extra}")
    return "\n\n".join(output)


def naver_search(query: str, max_results: int = 5) -> str:
    """네이버 블로그 검색 (네이버 검색 API 사용)"""
    return _naver_api_search(query, search_type="blog", display=max_results)


def naver_web_search(query: str, max_results: int = 5) -> str:
    """네이버 웹문서 검색 (네이버 검색 API 사용)"""
    return _naver_api_search(query, search_type="webkr", display=max_results)


def _kakao_api_search(query: str, search_type: str = "web", size: int = 5) -> str:
    """카카오 검색 API 호출 (web, blog, cafe 등)"""
    if not KAKAO_REST_KEY:
        return "카카오 API 키가 설정되지 않았습니다. .kakao_api 파일을 확인하세요."

    url = f"https://dapi.kakao.com/v2/search/{search_type}"
    params = urllib.parse.urlencode({"query": query, "size": size, "sort": "accuracy"})
    req = urllib.request.Request(f"{url}?{params}")
    req.add_header("Authorization", f"KakaoAK {KAKAO_REST_KEY}")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return f"카카오 API 오류: {e}"

    docs = data.get("documents", [])
    if not docs:
        return "검색 결과가 없습니다."

    output = []
    for i, doc in enumerate(docs, 1):
        # HTML 태그 제거
        title = doc.get("title", "").replace("<b>", "").replace("</b>", "")
        contents = doc.get("contents", "").replace("<b>", "").replace("</b>", "")
        url_link = doc.get("url", "")
        # 블로그는 블로그명/날짜 추가
        blogname = doc.get("blogname", "") or doc.get("cafename", "")
        datetime_str = doc.get("datetime", "")
        extra = ""
        if blogname:
            extra += f"\n    출처: {blogname}"
        if datetime_str:
            extra += f" | 날짜: {datetime_str[:10]}"
        output.append(f"[{i}] {title}\n    {url_link}\n    {contents[:300]}{extra}")
    return "\n\n".join(output)


def daum_search(query: str, max_results: int = 5) -> str:
    """다음 웹문서 검색 (브런치, 티스토리 등 카카오 계열 콘텐츠 포함)"""
    return _kakao_api_search(query, search_type="web", size=max_results)


def brunch_search(query: str, max_results: int = 5) -> str:
    """브런치 글 검색 (카카오 블로그 API + brunch.co.kr 필터)"""
    result = _kakao_api_search(f"site:brunch.co.kr {query}", search_type="web", size=max_results)
    if result == "검색 결과가 없습니다.":
        # site 필터로 안 나오면 일반 블로그 검색에서 브런치 포함 결과 반환
        return _kakao_api_search(f"브런치 {query}", search_type="blog", size=max_results)
    return result


def news_search(query: str, max_results: int = 5) -> str:
    """뉴스 검색 (네이버 검색 API 우선, 실패 시 DuckDuckGo)"""
    result = _naver_api_search(query, search_type="news", display=max_results)
    if "API 키가 설정되지 않았습니다" in result or "API 오류" in result:
        # 네이버 API 실패 시 DuckDuckGo 뉴스로 대체
        try:
            from ddgs import DDGS
            results = DDGS().news(query, max_results=max_results, region="kr-kr")
            if not results:
                return "뉴스 검색 결과가 없습니다."
            output = []
            for i, r in enumerate(results, 1):
                output.append(f"[{i}] {r['title']}\n    {r['url']}\n    {r['body']}\n    날짜: {r.get('date', '날짜 없음')}")
            return "\n\n".join(output)
        except Exception as e:
            return f"뉴스 검색 오류: {e}"
    return result


# Anthropic API 도구 정의 (직원들이 호출할 수 있는 도구)
TOOL_DEFINITIONS = [
    {
        "name": "web_search",
        "description": "웹 검색. 최신 정보, 트렌드, 경쟁사 분석, 시장 조사 등에 사용. 한국어 검색 기본.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색할 키워드 또는 문장"
                },
                "max_results": {
                    "type": "integer",
                    "description": "최대 결과 수 (기본 5)",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "news_search",
        "description": "최신 뉴스 검색. 업계 동향, 규제 변경, 경쟁사 소식 등에 사용.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색할 키워드 또는 문장"
                },
                "max_results": {
                    "type": "integer",
                    "description": "최대 결과 수 (기본 5)",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "naver_search",
        "description": "네이버 블로그 검색. 네이버 블로그 레퍼런스 원고, 후기, 체험기 등 국내 블로그 콘텐츠 검색에 사용.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색할 키워드 또는 문장"
                },
                "max_results": {
                    "type": "integer",
                    "description": "최대 결과 수 (기본 5)",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "naver_web_search",
        "description": "네이버 웹문서 검색. 네이버 블로그 외 카페, 지식인, 일반 웹페이지 등 폭넓은 검색에 사용.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색할 키워드 또는 문장"
                },
                "max_results": {
                    "type": "integer",
                    "description": "최대 결과 수 (기본 5)",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "daum_search",
        "description": "다음 웹문서 검색. 브런치, 티스토리, 다음 카페 등 카카오 계열 콘텐츠 검색에 사용.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색할 키워드 또는 문장"
                },
                "max_results": {
                    "type": "integer",
                    "description": "최대 결과 수 (기본 5)",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "brunch_search",
        "description": "브런치(brunch.co.kr) 글 검색. 에세이, 칼럼, 전문가 글 등 고퀄리티 레퍼런스 원고 검색에 특화.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색할 키워드 또는 문장"
                },
                "max_results": {
                    "type": "integer",
                    "description": "최대 결과 수 (기본 5)",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    }
]

# 도구 이름 → 함수 매핑
TOOL_FUNCTIONS = {
    "web_search": web_search,
    "news_search": news_search,
    "naver_search": naver_search,
    "naver_web_search": naver_web_search,
    "daum_search": daum_search,
    "brunch_search": brunch_search,
}
