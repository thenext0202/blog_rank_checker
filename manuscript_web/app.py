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
from drive_uploader import upload_docx_bytes
from sheet_writer import (
    write_row, _open_ws, DEFAULT_TAB_NAME,
    load_product_links, build_product_link,
)

app = Flask(__name__)

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "") or config.load_api_key()
API_SECRET = os.environ.get("API_SECRET", "")

# 프로세스 수명 동안 시스템 프롬프트 1회만 빌드 (메모리 캐시)
_SYSTEM_PROMPT = None
# 제품 링크 마스터 캐시 (시트에서 1회 로드) — 수동 새로고침은 /reload_products
_PRODUCT_LINKS = None


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

    parsed = parse(holder["text"])

    return jsonify({
        "title": parsed["title"],
        "body": parsed["body"],
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

    if not body.strip():
        return jsonify({"error": "원고 본문이 비어 있습니다."}), 400
    if not keyword or not product or not link:
        return jsonify({"error": "keyword, product, link는 필수입니다."}), 400

    # 편집본 기준으로 글자수 재계산
    char_count = len(body)

    # Drive 업로드 (편집본으로 docx 생성)
    drive_link = None
    try:
        docx_bytes = build_docx_bytes(title, body)
        fname_base = f"{keyword}_{product}".strip("_") or "원고"
        fname_base = re.sub(r'[\\/:*?"<>|]', "_", fname_base)[:80]
        _fid, drive_link = upload_docx_bytes(docx_bytes, f"{fname_base}.docx")
    except Exception as e:
        print(f"[write_sheet] Drive 업로드 실패: {e}")

    try:
        sheet_row = write_row(
            date_str, product, config.DEFAULT_CATEGORY, keyword,
            writer, link,
            title, body, char_count,
            review, model_key,
            drive_url=drive_link,
        )
    except Exception as e:
        return jsonify({"error": f"시트 기입 실패: {e}"}), 500

    return jsonify({
        "sheet_row": sheet_row,
        "drive_link": drive_link,
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
