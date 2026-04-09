"""원고 작성기 — Claude API 호출"""
import threading

# 선택 가능한 모델 목록
MODELS = {
    "Sonnet": "claude-sonnet-4-20250514",
    "Opus": "claude-opus-4-20250514",
}


def call_claude_api(api_key, prompt, on_complete, on_error,
                    model_key="Sonnet", max_tokens=8192):
    """Claude API 호출 (동기)"""
    try:
        import anthropic
        model_id = MODELS.get(model_key, MODELS["Sonnet"])
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        on_complete(message.content[0].text)
    except Exception as e:
        on_error(str(e))


def generate_manuscript_async(api_key, prompt, on_complete, on_error,
                              model_key="Sonnet"):
    """Claude API 호출 (스레드 기반 비동기 — GUI 블로킹 방지)"""
    thread = threading.Thread(
        target=call_claude_api,
        args=(api_key, prompt, on_complete, on_error, model_key),
        daemon=True
    )
    thread.start()
    return thread
