"""
심의안전 원고제작기 — Claude API 호출
"""


MODEL_MAP = {
    "Sonnet 4 (빠름)": "claude-sonnet-4-20250514",
    "Opus 4 (고품질)": "claude-opus-4-20250514",
}


def call_claude_api(api_key, prompt, on_complete, on_error, max_tokens=8192,
                    system_prompt=None, model="claude-sonnet-4-20250514"):
    """별도 스레드에서 호출할 Claude API 함수
    system_prompt: 별도 system 파라미터로 전달할 프롬프트 (없으면 기존 방식)
    model: 사용할 Claude 모델 ID
    """
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        message = client.messages.create(**kwargs)
        on_complete(message.content[0].text)
    except Exception as e:
        on_error(str(e))
