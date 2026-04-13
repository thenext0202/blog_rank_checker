#!/usr/bin/env python3
"""
Railway 시작 스크립트 v7
GOOGLE_CREDENTIALS_BASE64 → credentials.json 파일로 변환 후 rank_checker.py watch 실행
"""
import os, base64, json, sys
from datetime import datetime
print("=== STARTUP v8 (rank_checker.py watch) ===", flush=True)
print(f"[startup] 시작 시각: {datetime.now()}", flush=True)
print(f"[startup] TZ: {os.environ.get('TZ', 'not set')}", flush=True)

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
        print("[startup] credentials.json 저장 완료")
        # 환경변수는 유지 → rank_checker.py가 우선 사용

    except Exception as e:
        print(f"[startup] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
else:
    print("[startup] GOOGLE_CREDENTIALS_BASE64 없음 → credentials.json 직접 사용")

# rank_checker.py watch 실행
os.execv(sys.executable, [sys.executable, '/app/rank_checker.py', 'watch'])
