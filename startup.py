#!/usr/bin/env python3
"""
Railway 시작 스크립트
GOOGLE_CREDENTIALS_BASE64 → credentials.json 파일로 변환 후 rank.py 실행
"""
import os, base64, json, sys

creds_b64 = os.environ.get('GOOGLE_CREDENTIALS_BASE64', '')

if creds_b64:
    try:
        # 공백/줄바꿈 제거
        creds_b64 = ''.join(creds_b64.split())
        # 패딩 보정
        creds_b64 += '=' * (-len(creds_b64) % 4)
        # base64 디코딩
        decoded = base64.b64decode(creds_b64)
        info = json.loads(decoded.decode('utf-8'))

        # private_key 줄바꿈 복원
        pk = info.get('private_key', '')
        if '\\n' in pk and '\n' not in pk:
            pk = pk.replace('\\n', '\n')
        info['private_key'] = pk

        # 디버그 출력
        print(f"[startup] client_email: {info.get('client_email')}")
        print(f"[startup] private_key starts: {info['private_key'][:40]}")

        # credentials.json 파일로 저장
        with open('/app/credentials.json', 'w') as f:
            json.dump(info, f, indent=2)
        print("[startup] credentials.json 저장 완료")

    except Exception as e:
        print(f"[startup] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
else:
    print("[startup] GOOGLE_CREDENTIALS_BASE64 없음 → credentials.json 직접 사용")

# rank.py watch 실행
os.execv(sys.executable, [sys.executable, '/app/rank.py', 'watch'])
