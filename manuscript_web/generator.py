"""단일 원고 생성 오케스트레이션 — GUI/웹/CLI 공통 진입점."""
from datetime import datetime, timezone, timedelta

from api_client import call_claude_api
from prompt_builder import build_system_prompt, build_user_prompt
from output_parser import parse
from config import DEFAULT_CATEGORY


def _kst_date():
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y-%m-%d")


def generate_one(api_key, keyword, product_name, product_link,
                 writer_name="", write_date="",
                 model_key="Opus", system_prompt=None):
    """단건 생성 — 동기 호출. 파싱 결과 dict 반환.

    system_prompt을 외부에서 주면 재사용(배치 시 빌드 1회만).
    """
    sys_p = system_prompt or build_system_prompt()
    user_p = build_user_prompt(keyword, product_name, product_link)

    result_holder = {"text": None, "meta": None, "error": None}

    def on_done(text, meta):
        result_holder["text"] = text
        result_holder["meta"] = meta

    def on_err(msg):
        result_holder["error"] = msg

    call_claude_api(api_key, sys_p, user_p, on_done, on_err,
                    model_key=model_key)

    if result_holder["error"]:
        raise RuntimeError(result_holder["error"])

    parsed = parse(result_holder["text"])
    parsed.update({
        "keyword": keyword,
        "product_name": product_name,
        "product_link": product_link,
        "writer_name": writer_name,
        "write_date": write_date or _kst_date(),
        "category": DEFAULT_CATEGORY,
        "model_key": model_key,
        "usage": result_holder["meta"],
    })
    return parsed


def to_sheet_row(result):
    """parse 결과 + 메타를 sheet_writer용 리스트로 변환 (A~K열, L열은 sheet_writer가 생성)."""
    return [
        result.get("write_date", ""),
        result.get("product_name", ""),
        result.get("category", DEFAULT_CATEGORY),
        result.get("keyword", ""),
        result.get("writer_name", ""),
        result.get("product_link", ""),
        result.get("title", ""),
        result.get("body", ""),
        result.get("char_count", 0),
        result.get("review", ""),
        result.get("model_key", ""),
    ]
