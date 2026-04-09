#!/usr/bin/env python3
"""
Railway 시작 스크립트 v4
GOOGLE_CREDENTIALS_BASE64 → credentials.json 파일로 변환 후 rank.py 실행
"""
import os, base64, json, sys
print("=== STARTUP v6 (Playwright) ===", flush=True)
import subprocess
# Playwright chromium 설치
print("[startup] playwright install chromium...", flush=True)
r = subprocess.run(
    ["playwright", "install", "chromium", "--with-deps"],
    capture_output=True, text=True
)
if r.returncode == 0:
    print("[startup] playwright chromium 설치 완료", flush=True)
else:
    print(f"[startup] playwright install 오류: {r.stderr[:200]}", flush=True)

creds_b64 = os.environ.get('GOOGLE_CREDENTIALS_BASE64', '')

if creds_b64:
    try:
        # 공백/줄바꿈 제거 및 패딩 보정
        creds_b64 = ''.join(creds_b64.split())
        creds_b64 += '=' * (-len(creds_b64) % 4)

        # raw bytes 그대로 파일에 쓰기 (json 파싱/재직렬화 없음)
        decoded = base64.b64decode(creds_b64)
        with open('/app/credentials.json', 'wb') as f:
            f.write(decoded)

        # 디버그용 검증
        info = json.loads(decoded.decode('utf-8'))
        print(f"[startup] client_email: {info.get('client_email')}")
        pk = info.get('private_key', '')
        print(f"[startup] private_key length: {len(pk)}")
        print(f"[startup] has BEGIN: {'-----BEGIN PRIVATE KEY-----' in pk}")
        print(f"[startup] has END: {'-----END PRIVATE KEY-----' in pk}")
        print(f"[startup] key tail: {repr(pk[-60:])}")
        print("[startup] credentials.json 저장 완료")

        # env var 제거 → rank.py가 파일로 읽도록
        del os.environ['GOOGLE_CREDENTIALS_BASE64']

    except Exception as e:
        print(f"[startup] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
else:
    print("[startup] GOOGLE_CREDENTIALS_BASE64 없음 → credentials.json 직접 사용")

# rank.py watch 실행
os.execv(sys.executable, [sys.executable, '/app/rank.py', 'watch'])
