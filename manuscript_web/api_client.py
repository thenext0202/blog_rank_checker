"""Claude API 호출 — 프롬프트 캐싱 적용.

지침 6개(약 40K 토큰)는 system 블록에 cache_control 설정 →
첫 호출 후 5분간 재사용 시 90% 비용 절감.
"""
import threading

# 선택 가능한 모델 (최신 4.6 세대) — Opus가 기본 (dict 순서 = UI 순서)
MODELS = {
    "Opus":   "claude-opus-4-6",
    "Sonnet": "claude-sonnet-4-6",
}


def call_claude_api(api_key, system_prompt, user_prompt, on_complete, on_error,
                    model_key="Opus", max_tokens=32000):
    """Claude API 호출 — 스트리밍 방식. system에 cache_control 적용.

    max_tokens가 크면 SDK가 스트리밍을 요구하므로 stream() 사용.
    결과 텍스트와 usage는 final message에서 한 번에 수거.
    """
    try:
        import anthropic
        model_id = MODELS.get(model_key, MODELS["Opus"])
        client = anthropic.Anthropic(api_key=api_key)
        with client.messages.stream(
            model=model_id,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            message = stream.get_final_message()
        text = message.content[0].text
        # 캐시 히트 여부 + 실제 실행된 모델 ID
        usage = getattr(message, "usage", None)
        meta = {"actual_model": getattr(message, "model", model_id)}
        if usage:
            meta.update({
                "input_tokens": getattr(usage, "input_tokens", 0),
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
            })
        on_complete(text, meta)
    except Exception as e:
        on_error(str(e))


def generate_async(api_key, system_prompt, user_prompt, on_complete, on_error,
                   model_key="Opus", max_tokens=32000):
    """스레드 비동기 호출 (GUI 블로킹 방지)."""
    thread = threading.Thread(
        target=call_claude_api,
        args=(api_key, system_prompt, user_prompt, on_complete, on_error,
              model_key, max_tokens),
        daemon=True,
    )
    thread.start()
    return thread
