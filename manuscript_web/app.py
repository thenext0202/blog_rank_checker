"""블록 원고 생성기 — Flask 웹 API (Railway 배포)."""
import os
import re
import base64
import tempfile
import datetime
from urllib.parse import quote

from flask import Flask, request, jsonify, render_template, Response

# Google 서비스 계정 인증 (환경변수 base64 디코딩)
_cred_env = os.environ.get("GOOGLE_CREDENTIALS_B64", "")
if _cred_env:
    _tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="wb")
    _tmp.write(base64.b64decode(_cred_env))
    _tmp.close()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _tmp.name

import config
from api_client import call_claude_api, MODELS
from prompt_builder import build_system_prompt, build_user_prompt
from output_parser import parse
from docx_writer import build_docx_bytes
from html_formatter import build_html_preview
from docx_formatter import normalize_text
from sheet_writer import (
    write_row, _open_ws, DEFAULT_TAB_NAME,
    load_product_links, build_product_link,
    update_l_column_bulk,
    load_keyword_recommendations,
)

app = Flask(__name__)

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "") or config.load_api_key()
API_SECRET = os.environ.get("API_SECRET", "")

# 프로세스 수명 동안 시스템 프롬프트 1회만 빌드 (메모리 캐시)
_SYSTEM_PROMPT = None
# 제품 링크 마스터 캐시 (시트에서 1회 로드) — 수동 새로고침은 /reload_products
_PRODUCT_LINKS = None
# 추천 키워드 캐시 — 새로고침은 /recommend_keywords?refresh=1
_KEYWORD_RECS = None


def get_system_prompt():
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = build_system_prompt()
    return _SYSTEM_PROMPT


def get_product_links():
    global _PRODUCT_LINKS
    if _PRODUCT_LINKS is None:
        _PRODUCT_LINKS = load_product_links()
    return _PRODUCT_LINKS


def get_keyword_recommendations(force_reload=False):
    global _KEYWORD_RECS
    if _KEYWORD_RECS is None or force_reload:
        _KEYWORD_RECS = load_keyword_recommendations()
    return _KEYWORD_RECS


def _auth_check(req):
    if not API_SECRET:
        return True
    token = req.headers.get("X-API-Secret", "") or req.args.get("secret", "")
    return token == API_SECRET


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": config.VERSION})


@app.route("/debug", methods=["GET"])
def debug():
    return jsonify({
        "API_KEY_set": bool(API_KEY),
        "API_KEY_length": len(API_KEY),
        "SHEET_ID": config.load_sheet_id(),
        "TAB_NAME": DEFAULT_TAB_NAME,
        "products": config.PRODUCT_NAMES,
        "models": list(MODELS.keys()),
    })


@app.route("/", methods=["GET"])
def index():
    return render_template(
        "index.html",
        version=config.VERSION,
        products=config.PRODUCT_NAMES,
        models=list(MODELS.keys()),
        category=config.DEFAULT_CATEGORY,
        product_links=get_product_links(),
    )


@app.route("/test", methods=["GET"])
def test_page():
    # 편집창 서식 로직 자동 검증 페이지. 실제 index.html을 iframe으로 띄워
    # 샘플 원고·선택 범위·버튼 클릭을 자동으로 재현하고 결과를 비교한다.
    return render_template("test_format.html", version=config.VERSION)


@app.route("/test_preview", methods=["POST"])
def test_preview():
    """테스트 페이지 전용 미리보기 프록시 (인증 없음, localhost 개발용)."""
    from html_formatter import build_html_preview
    data = request.get_json(silent=True) or {}
    title = data.get("title", "") or ""
    body = data.get("body", "") or ""
    if not body.strip():
        return jsonify({"error": "body가 비어 있습니다."}), 400
    try:
        html = build_html_preview(title, body)
        return jsonify({"html": html})
    except Exception as e:
        return jsonify({"error": f"미리보기 생성 실패: {e}"}), 500


@app.route("/test_format_apply", methods=["POST"])
def test_format_apply():
    """테스트 페이지 전용 — 짧은 원고에 LLM이 서식 지침 적용 (Phase A~D 생략, E만).

    /generate 는 전체 원고를 새로 쓰느라 수분 걸림. 이 엔드포인트는 사용자가
    이미 작성한 짧은 원고(5줄 내외)에 `ㄴ 주석`·`**볼드**`만 덧붙여 돌려준다.
    """
    if not API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY 미설정"}), 500
    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()
    product = data.get("product") or ""
    model_key = data.get("model") or "Sonnet"  # 속도 기본 Sonnet, 품질 원하면 Opus
    if not body:
        return jsonify({"error": "body가 비었습니다"}), 400

    # 서식 지침(모듈7) 로드
    inst_dir = config.load_instructions_dir() or config.DEFAULT_INSTRUCTIONS_DIR
    formatting_path = os.path.join(inst_dir, config.MODULE_FILES["formatting"])
    try:
        with open(formatting_path, "r", encoding="utf-8") as f:
            formatting_guide = f.read()
    except FileNotFoundError:
        formatting_guide = "(서식 지침 파일 없음 — 기본 규칙으로 처리)"

    system_prompt = (
        "너는 블록 원고 서식 전문가다. 사용자가 준 짧은 원고에, 아래 서식 지침에 따라 "
        "`ㄴ 주석`과 `**볼드**` 표식만 덧붙여서 돌려준다.\n\n"
        "[중요 출력 규칙]\n"
        "- 원본 문장 내용·순서 그대로 유지\n"
        "- 원본의 빈 줄(문단 분리)은 **반드시 그대로 유지**\n"
        "- 본문 라인 아래 `ㄴ 주석`으로 색상·형광펜·밑줄·볼드·인용구 지시\n"
        "- **같은 문단(연속 본문 라인) 안에는 `ㄴ 주석` 한 개만**. 줄마다 ㄴ + 빈 줄 반복 금지\n"
        "- 문단이 바뀌면 빈 줄 1줄로 분리 (원본의 문단 구조 존중)\n"
        "- 배합명/성분명 등 특정 단어만 강조는 `ㄴ '단어' 색상 형광펜, 볼드` 형태\n"
        "- 결과는 주석 섞인 원고 텍스트만 반환 — 설명·코드블록·서두·Phase 헤더 금지\n\n"
        "[블록 묶음 예시]\n"
        "잘못된 출력 (문단 안 줄마다 ㄴ + 빈 줄):\n"
        "  의사선생님도 모르겠다고 하신다.\n"
        "  ㄴ 빨간색\n"
        "\n"
        "  정말 답답함 그 자체다.\n"
        "  ㄴ 빨간색\n"
        "\n"
        "올바른 출력 (한 문단 안엔 ㄴ 한 개, 문단 경계 빈 줄 유지):\n"
        "  의사선생님도 모르겠다고 하신다.\n"
        "  정말 답답함 그 자체다.\n"
        "  뭐가 문제일까?\n"
        "  ㄴ 빨간색\n"
        "\n"
        "  (다음 문단은 여기서 시작)\n\n"
        "=== 서식 지침 (모듈7) ===\n"
        + formatting_guide
    )
    user_prompt = (
        f"제품: {product or '(지정 없음)'}\n\n"
        f"[원고]\n{body}\n\n"
        "위 원고에 서식 지침을 적용해 `ㄴ 주석`·`**볼드**`만 덧붙인 결과를 반환해줘."
    )

    holder = {"text": "", "error": None}
    call_claude_api(
        API_KEY, system_prompt, user_prompt,
        lambda text, meta: holder.update({"text": text}),
        lambda err: holder.update({"error": err}),
        model_key=model_key, max_tokens=4000,
    )
    if holder["error"]:
        return jsonify({"error": holder["error"]}), 500

    raw = (holder["text"] or "").strip()
    # LLM이 각 줄마다 ㄴ + 빈 줄 넣는 경향 방어 — 연속 본문-ㄴ-빈줄 패턴 압축
    raw = _collapse_llm_over_spacing(raw)
    # 파서 체인 + 줄 길이 정규화 (실제 /generate 흐름과 동일)
    import output_parser
    result = output_parser._em_dash_to_quote(raw)
    result = output_parser._normalize_quotes_in_annotations(result)
    result = output_parser._split_sentences_after_period(result)
    result = output_parser._enforce_product_ingredient_format(result, product or None)
    result = normalize_text(result)
    return jsonify({"result": result, "raw_llm": raw, "model": model_key})


def _collapse_llm_over_spacing(text):
    """LLM이 과하게 `본문\\nㄴ 주석\\n(빈 줄)\\n본문\\nㄴ 주석` 식으로 출력한 경우
    연속 ㄴ 주석 블록을 모아 마지막 한 줄로 압축.

    같은 색상·볼드 조합(공통 서식)만 남기고 나머지는 드롭 — 보수적 병합.
    다른 서식(예: 인용구)은 건드리지 않음.
    """
    import re as _re
    if not text:
        return text
    lines = text.split("\n")
    out = []
    i = 0
    # 패턴: (본문)(빈 줄*)(ㄴ 색/볼드)(빈 줄*) 반복 2회 이상
    SIMPLE_ANN = _re.compile(
        r"^ㄴ\s+(?:[\w가-힣\s,]+)?(빨간색|파란색|청록색|초록색|보라색|주황색|회색|하늘색|노란색)"
        r"(?:\s*형광펜)?(?:\s*,\s*볼드)?(?:\s*,\s*밑줄)?\s*$"
    )
    while i < len(lines):
        # 본문 라인 감지
        s = lines[i].strip()
        if not s or s.startswith("ㄴ") or s.startswith("★") or _re.match(r"^[─—–\-=_]{3,}$", s):
            out.append(lines[i])
            i += 1
            continue
        # 본문 시작 → 같은 "문단" (빈 줄 없이 이어지는) 안에서만 ㄴ 수집
        # 빈 줄 만나면 즉시 블록 종료 (문단 경계 존중)
        bodies = []
        anns = []
        j = i
        while j < len(lines):
            t = lines[j].strip()
            if not t:
                break  # 문단 경계 (빈 줄) 도달 → 압축 중단, 빈 줄은 out에 그대로 나감
            if t.startswith("ㄴ"):
                if SIMPLE_ANN.match(t):
                    anns.append(t)
                    j += 1
                    continue
                break  # 복잡한 ㄴ (타겟 있는, 인용구 등) → 블록 종료
            # 본문 라인
            bodies.append(lines[j])
            j += 1
        # 압축 조건: 본문 2줄 이상 + 단일 서식 ㄴ 2개 이상
        if len(bodies) >= 2 and len(anns) >= 2:
            # 공통 핵심 색상(첫 ㄴ 기준)만 추출
            first_ann = anns[0]
            color_m = _re.search(r"(빨간색|파란색|청록색|초록색|보라색|주황색|회색|하늘색|노란색)", first_ann)
            is_hl = "형광펜" in first_ann
            if color_m:
                merged = f"ㄴ {color_m.group(1)}" + (" 형광펜" if is_hl else "")
                out.extend(bodies)
                out.append(merged)
                i = j
                continue
        # 압축 안 함 — 원본 그대로
        out.append(lines[i])
        i += 1
    return "\n".join(out)


@app.route("/test_hook", methods=["POST"])
def test_hook():
    """output_parser 후처리 함수를 단건 호출해 결과를 반환 — 테스트 페이지 전용."""
    import output_parser
    data = request.get_json(silent=True) or {}
    func = data.get("func", "")
    body = data.get("body", "") or ""
    product = data.get("product")
    keyword = data.get("keyword")
    try:
        if func == "enforce":
            result = output_parser._enforce_product_ingredient_format(body, product)
        elif func == "inject_keyword":
            result = output_parser._inject_keyword_target(body, keyword)
        elif func == "split_sentences":
            result = output_parser._split_sentences_after_period(body)
        elif func == "parse_body":
            # Phase E body 후처리 체인과 동일 순서 (parse() L549~ 와 일치)
            result = output_parser._em_dash_to_quote(body)
            result = output_parser._normalize_quotes_in_annotations(result)
            result = output_parser._split_sentences_after_period(result)
            result = output_parser._enforce_product_ingredient_format(result, product)
            result = output_parser._merge_same_target_annotations(result)
            result = output_parser._inject_keyword_target(result, keyword)
        elif func == "full_pipeline":
            # 실제 /generate 흐름 재현: parse 체인 + normalize_text(줄 길이 28자 정리)
            from docx_formatter import normalize_text
            result = output_parser._em_dash_to_quote(body)
            result = output_parser._normalize_quotes_in_annotations(result)
            result = output_parser._split_sentences_after_period(result)
            result = output_parser._enforce_product_ingredient_format(result, product)
            result = output_parser._merge_same_target_annotations(result)
            result = output_parser._inject_keyword_target(result, keyword)
            result = normalize_text(result)
        elif func == "parse_annotation":
            # docx_formatter.parse_annotation 단건 검증 (v2.1.6~ 슬래시 분할 등)
            from docx_formatter import parse_annotation as _pa
            fmt = _pa(body)
            result = {
                "colored_words": fmt.get("colored_words", []),
                "highlighted_words": [(w, str(c)) for w, c in fmt.get("highlighted_words", [])],
                "bolded_words": fmt.get("bolded_words", []),
                "underlined_words": fmt.get("underlined_words", []),
                "target_words": fmt.get("target_words", []),
                "full_text_color": fmt.get("full_text_color"),
                "highlight": str(fmt.get("highlight")) if fmt.get("highlight") else None,
                "bold": fmt.get("bold"),
            }
        else:
            return jsonify({"error": f"unknown func: {func}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"result": result})


@app.route("/products", methods=["GET"])
def products():
    return jsonify({"products": config.PRODUCT_NAMES})


@app.route("/product_links", methods=["GET"])
def product_links():
    """프론트엔드에서 최신 링크 마스터 조회."""
    return jsonify(get_product_links())


@app.route("/reload_products", methods=["POST"])
def reload_products():
    """제품 링크 시트를 다시 로드 (캐시 갱신)."""
    global _PRODUCT_LINKS
    _PRODUCT_LINKS = load_product_links()
    return jsonify({"ok": True, "count": len(_PRODUCT_LINKS)})


@app.route("/recommend_keywords", methods=["GET"])
def recommend_keywords():
    """'키워드 전광판' 탭의 추천 키워드 조회.

    - 페이지 로드 시 1회 캐시 사용
    - ?refresh=1 → 시트 다시 읽어 캐시 갱신
    """
    refresh = request.args.get("refresh", "") == "1"
    data = get_keyword_recommendations(force_reload=refresh)
    return jsonify({"recommendations": data})


@app.route("/generate", methods=["POST"])
def generate():
    """단건 생성만 수행. 시트 기입·Drive 업로드는 편집 후 /write_sheet에서 처리."""
    if not _auth_check(request):
        return jsonify({"error": "인증 실패"}), 403

    data = request.get_json(force=True) or {}
    keyword = (data.get("keyword") or "").strip()
    product = (data.get("product") or "").strip()
    link = (data.get("link") or "").strip()
    writer = (data.get("writer") or "").strip()
    nt_medium = (data.get("nt_medium") or "").strip()
    date_str = (data.get("date") or "").strip()
    model_key = (data.get("model") or "Opus").strip()

    # link 미제공 시 백엔드 자동 조립 (제품 링크 탭 기반)
    if not link:
        info = get_product_links().get(product)
        if info and info.get("base_link"):
            link = build_product_link(
                info["base_link"], nt_medium, date_str, keyword, info.get("code", "")
            )

    if not keyword or not product or not link:
        return jsonify({"error": "keyword, product, link는 필수입니다."}), 400
    if not API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY 미설정"}), 500

    holder = {"text": None, "meta": None, "err": None}

    def on_done(text, meta):
        holder["text"] = text
        holder["meta"] = meta

    def on_err(msg):
        holder["err"] = msg

    try:
        call_claude_api(
            API_KEY, get_system_prompt(),
            build_user_prompt(keyword, product, link),
            on_done, on_err, model_key=model_key,
        )
    except Exception as e:
        return jsonify({"error": f"API 호출 실패: {e}"}), 500

    if holder["err"]:
        return jsonify({"error": holder["err"]}), 500

    # 진단용: LLM raw 출력을 output 폴더에 저장 (ㄴ 지시 라벨 등 원본 확인)
    try:
        _ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        _safe_kw = re.sub(r'[\\/:*?"<>|]', "_", keyword or "raw")[:40]
        _raw_path = os.path.join(config.OUTPUT_DIR, f"{_ts}_{_safe_kw}_raw.txt")
        with open(_raw_path, "w", encoding="utf-8") as _f:
            _f.write(holder["text"] or "")
    except Exception:
        pass

    parsed = parse(holder["text"], product=product, keyword=keyword)

    # 편집창 = 미리보기/워드 출력 결과 일치 보장 — 본문 줄바꿈 정규화 후 반환
    normalized_body = normalize_text(parsed["body"])

    return jsonify({
        "title": parsed["title"],
        "body": normalized_body,
        "char_count": parsed["char_count"],
        "style": parsed["style"],
        "blocks_summary": parsed["blocks_summary"],
        "review": parsed["review"],
        "phases": parsed["phases"],
        "usage": holder["meta"],
        # 프론트가 그대로 되돌려 보낼 메타 (시트 기입 단계에서 사용)
        "meta": {
            "keyword": keyword,
            "product": product,
            "link": link,
            "writer": writer,
            "date": date_str,
            "model": model_key,
        },
    })


@app.route("/raw_files", methods=["GET"])
def raw_files():
    """output 폴더의 *_raw.txt 파일 목록 (최신순) — 재처리 UI 용."""
    out_dir = config.OUTPUT_DIR
    files = []
    try:
        for fn in os.listdir(out_dir):
            if not fn.endswith("_raw.txt"):
                continue
            path = os.path.join(out_dir, fn)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            # 파일명 형식: {YYYYMMDD_HHMMSS}_{keyword}_raw.txt
            m = re.match(r"^(\d{8}_\d{6})_(.+)_raw\.txt$", fn)
            ts_disp = m.group(1) if m else ""
            kw_guess = m.group(2) if m else ""
            files.append({
                "filename": fn,
                "ts": ts_disp,
                "keyword_guess": kw_guess,
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            })
    except OSError as e:
        return jsonify({"error": str(e)}), 500
    files.sort(key=lambda f: f["mtime"], reverse=True)
    return jsonify({"files": files[:50]})  # 최신 50개만


@app.route("/reprocess", methods=["POST"])
def reprocess():
    """기존 raw 파일을 LLM 호출 없이 다시 parse → 편집창에 표시.

    /generate 와 같은 응답 형식. raw 파일은 새로 저장하지 않음.
    """
    if not _auth_check(request):
        return jsonify({"error": "인증 실패"}), 403

    data = request.get_json(force=True) or {}
    filename = (data.get("filename") or "").strip()
    keyword = (data.get("keyword") or "").strip()
    product = (data.get("product") or "").strip()
    link = (data.get("link") or "").strip()
    writer = (data.get("writer") or "").strip()
    nt_medium = (data.get("nt_medium") or "").strip()
    date_str = (data.get("date") or "").strip()
    model_key = (data.get("model") or "Opus").strip()

    if not filename:
        return jsonify({"error": "filename 필수"}), 400
    # 보안: 경로 분리자/상위 이동 금지
    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "잘못된 파일명"}), 400
    if not filename.endswith("_raw.txt"):
        return jsonify({"error": "raw 파일이 아님"}), 400

    raw_path = os.path.join(config.OUTPUT_DIR, filename)
    if not os.path.isfile(raw_path):
        return jsonify({"error": f"파일 없음: {filename}"}), 404

    try:
        with open(raw_path, "r", encoding="utf-8") as f:
            raw_text = f.read()
    except OSError as e:
        return jsonify({"error": f"파일 읽기 실패: {e}"}), 500

    # 파일명에서 keyword 추출 (요청에 없으면)
    if not keyword:
        m = re.match(r"^\d{8}_\d{6}_(.+)_raw\.txt$", filename)
        if m:
            keyword = m.group(1)

    parsed = parse(raw_text, product=product or None, keyword=keyword or None)
    normalized_body = normalize_text(parsed["body"])

    return jsonify({
        "title": parsed["title"],
        "body": normalized_body,
        "char_count": parsed["char_count"],
        "style": parsed["style"],
        "blocks_summary": parsed["blocks_summary"],
        "review": parsed["review"],
        "phases": parsed["phases"],
        "usage": {"actual_model": "(재처리 — LLM 호출 없음)"},
        "meta": {
            "keyword": keyword,
            "product": product,
            "link": link,
            "writer": writer,
            "date": date_str,
            "model": model_key,
            "reprocessed_from": filename,
        },
    })


@app.route("/write_sheet", methods=["POST"])
def write_sheet_route():
    """편집본(제목/본문) + 메타를 받아 Drive 업로드 → 시트 기입."""
    if not _auth_check(request):
        return jsonify({"error": "인증 실패"}), 403

    data = request.get_json(force=True) or {}
    keyword = (data.get("keyword") or "").strip()
    product = (data.get("product") or "").strip()
    link = (data.get("link") or "").strip()
    writer = (data.get("writer") or "").strip()
    date_str = (data.get("date") or "").strip()
    model_key = (data.get("model") or "Opus").strip()
    title = data.get("title") or ""
    body = data.get("body") or ""
    review = data.get("review") or ""
    filename = (data.get("filename") or "").strip()

    if not body.strip():
        return jsonify({"error": "원고 본문이 비어 있습니다."}), 400
    if not keyword or not product or not link:
        return jsonify({"error": "keyword, product, link는 필수입니다."}), 400

    # 편집본 기준으로 글자수 재계산
    char_count = len(body)

    # 시트 L열 '원고 다운로드' 링크 — 현 요청의 호스트를 기본값으로 사용
    # (APP_BASE_URL 환경변수가 있으면 그게 우선)
    base_url = (os.environ.get("APP_BASE_URL", "").strip()
                or request.host_url.rstrip("/"))

    try:
        sheet_row = write_row(
            date_str, product, config.DEFAULT_CATEGORY, keyword,
            writer, link,
            title, body, char_count,
            review, model_key,
            download_base_url=base_url,
            filename=filename,
        )
    except Exception as e:
        return jsonify({"error": f"시트 기입 실패: {e}"}), 500

    return jsonify({
        "sheet_row": sheet_row,
        "char_count": char_count,
    })


def _docx_response(docx_bytes, filename):
    if not filename.lower().endswith(".docx"):
        filename += ".docx"
    encoded = quote(filename, safe="")
    return Response(
        docx_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
            "Content-Length": str(len(docx_bytes)),
        },
    )


@app.route("/migrate_l_column", methods=["POST"])
def migrate_l_column():
    """기존 행들의 L열 HYPERLINK를 일괄로 /download_row/N 링크로 갱신."""
    if not _auth_check(request):
        return jsonify({"error": "인증 실패"}), 403
    data = request.get_json(silent=True) or {}
    dry = bool(data.get("dry_run", False))
    base_url = (os.environ.get("APP_BASE_URL", "").strip()
                or request.host_url.rstrip("/"))
    try:
        result = update_l_column_bulk(base_url, dry_run=dry)
        result["base_url"] = base_url
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"L열 일괄 갱신 실패: {e}"}), 500


@app.route("/preview_html", methods=["POST"])
def preview_html():
    """편집본(제목/본문)을 받아 서식 적용된 HTML 미리보기 반환."""
    if not _auth_check(request):
        return jsonify({"error": "인증 실패"}), 403
    data = request.get_json(force=True) or {}
    title = data.get("title", "") or ""
    body = data.get("body", "") or ""
    if not body.strip():
        return jsonify({"error": "body가 비어 있습니다."}), 400
    try:
        html = build_html_preview(title, body)
        return jsonify({"html": html})
    except Exception as e:
        return jsonify({"error": f"미리보기 생성 실패: {e}"}), 500


@app.route("/download_docx", methods=["POST"])
def download_docx():
    """브라우저에서 본문 받아 .docx 반환."""
    if not _auth_check(request):
        return jsonify({"error": "인증 실패"}), 403
    data = request.get_json(force=True) or {}
    title = data.get("title", "")
    body = data.get("body", "")
    filename = (data.get("filename") or title or "manuscript").strip()
    if not body.strip():
        return jsonify({"error": "body가 비어 있습니다."}), 400
    return _docx_response(build_docx_bytes(title, body), filename)


@app.route("/download_row/<int:row>", methods=["GET"])
def download_row(row):
    """시트 L열 HYPERLINK에서 호출 — 행의 G(제목)+H(본문)으로 DOCX."""
    if not _auth_check(request):
        return jsonify({"error": "인증 실패"}), 403
    if row < 2:
        return jsonify({"error": "row는 2 이상이어야 합니다."}), 400
    try:
        ws = _open_ws()
        rng = ws.get(f"A{row}:L{row}")
        if not rng or not rng[0]:
            return jsonify({"error": f"행 {row} 비어 있음"}), 404
        r = rng[0] + [""] * max(0, 12 - len(rng[0]))
        keyword = r[3]  # D
        title = r[6]    # G
        body = r[7]     # H
    except Exception as e:
        return jsonify({"error": f"시트 읽기 실패: {e}"}), 500
    if not body.strip():
        return jsonify({"error": f"행 {row}의 본문(H열) 비어 있음"}), 404
    fname = title or keyword or f"row{row}"
    return _docx_response(build_docx_bytes(title, body), fname)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # use_reloader=False: 파일 수정 시 자동 재시작 방지 (긴 요청 중 연결 끊김 예방)
    # threaded=True: 동시에 여러 요청 처리 (긴 생성 중에도 헬스체크 등 가능)
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False, threaded=True)
