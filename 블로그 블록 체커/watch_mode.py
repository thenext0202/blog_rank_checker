# -*- coding: utf-8 -*-
"""60초마다 블록 체커 탭 확인 → 체크 감지 시 run_once 실행."""
import time
from datetime import datetime
import sheets
import main as m

def watch(interval=60):
    print("블록 체커 감시 모드 (60초 간격, Ctrl+C 종료)")
    try:
        while True:
            ws = sheets.connect()
            targets = sheets.read_targets(ws)
            if targets:
                print(f"\n>> 체크 감지 {len(targets)}개 — 처리 시작")
                m.run_once()
            else:
                now = datetime.now().strftime("%H:%M:%S")
                print(f"\r[{now}] 대기 중...", end="", flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n감시 종료")
