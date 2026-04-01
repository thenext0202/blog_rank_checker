"""
심의안전 원고제작기 — Claude API 호출
"""


def call_claude_api(api_key, prompt, on_complete, on_error, max_tokens=8192):
    """별도 스레드에서 호출할 Claude API 함수"""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        on_complete(message.content[0].text)
    except Exception as e:
        on_error(str(e))
