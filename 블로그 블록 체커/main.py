# -*- coding: utf-8 -*-
"""네이버 블록 체커 — 블록 체커 탭 B열 체크 → 인기글/스블/통검블로그 분석·기록.
실행: py main.py   (체크된 행 1회 처리)
      py main.py watch  (60초 감시)
"""
import sys, time
from datetime import date
import sheets
from serp_parser import create_driver, parse_keyword

def run_once():
    print("=" * 50); print("  네이버 블록 체커"); print("=" * 50)
    print("\n[1] 시트 연결...")
    ws = sheets.connect()
    targets = sheets.read_targets(ws)
    if not targets:
        print("    처리 대상 없음. 블록 체커 탭 B열에 체크하세요.")
        return
    print(f"    {len(targets)}개 처리 대상")
    sheets.clear_checkboxes(ws, [r for r, _ in targets])

    print("\n[2] 브라우저 준비...")
    driver = create_driver()
    today = date.today()
    try:
        for i, (row, kw) in enumerate(targets, 1):
            print(f"\n  [{i}/{len(targets)}] {kw} (행 {row})")
            try:
                result = parse_keyword(driver, kw, today)
                sheets.write_result(ws, row, result, today)
                print(f"        인기글 {len(result['인기글'])} / "
                      f"스블 {len(result['스블'])} / 통검 {len(result['통검블로그'])}")
            except Exception as e:
                print(f"        [!] 오류: {e}")
                sheets.write_error(ws, row, str(e)[:80])
            time.sleep(2)
    finally:
        try: driver.quit()
        except Exception: pass
    print("\n  완료!")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "watch":
        from watch_mode import watch
        watch()
    else:
        run_once()
