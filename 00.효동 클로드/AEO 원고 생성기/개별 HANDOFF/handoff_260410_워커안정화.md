# handoff 260410 — 워커 안정화 (재연결 + 영구 실패 마킹)

> 작업일: 2026-04-10 (당일 추가 작업)<br>
> 버전: v1.3 → **v1.3.1**<br>
> 작업자: 효동(Claude Opus 4.6) + 효진

<br>

## 🎯 작업 목적

대량 입력 시 발생할 수 있는 **시간 관련 두 가지 문제**를 해결.

1. **구글 OAuth 토큰 1시간 만료** — 한 루프에서 1시간 넘게 처리하면 시트 기입이 401 인증 만료로 실패
2. **영구 실패 행 무한 재시도** — 카테고리 오타 등으로 영원히 실패하는 행이 폴링마다 재시도되어 API 비용 낭비

> 참고: Railway gunicorn 300초 timeout은 **web 프로세스 전용**이고, worker는 gunicorn 안 쓰는 별개 프로세스라 무관.

<br>

## 🔁 Before / After

### Before (v1.3 초안)

```python
while True:
    spreadsheet = connect_sheet(SHEET_ID)   # 한 번만 연결
    pending = find_pending_rows(ws)
    for item in pending:
        process_row(spreadsheet, ...)        # 같은 클라이언트 재사용
```

- 100건 처리에 1.5시간 → OAuth 토큰 만료 → 후반 실패
- 실패 행 마킹 없음 → 같은 행 무한 재시도

### After (v1.3.1)

```python
while True:
    spreadsheet = connect_sheet(SHEET_ID)   # 행 탐색용
    pending = find_pending_rows(ws)
    del spreadsheet                          # 즉시 버림

    for item in pending:
        process_row(api_key, item)           # 매 행마다 새 클라이언트
```

```python
def process_row(api_key, item):
    try:
        result = generate_aeo(...)           # Claude 호출
    except Exception as e:
        _record_failure(row, ...)            # 카운트 +1, 한도 시 마킹
        return

    spreadsheet = connect_sheet(SHEET_ID)    # 시트 기입 직전 새 연결
    update_aeo_row(spreadsheet, row, ...)
```

- **매 행마다 새 OAuth 토큰** → 1시간 만료 무관
- **3회 실패 시 I열에 ❌ 마킹** → 다음 폴링에서 자동 스킵 (본문이 채워졌으니)

<br>

## 🛠️ 구현 변경

### 1. 환경변수 추가

| 변수 | 기본값 | 용도 |
| --- | --- | --- |
| `WORKER_FAILURE_LIMIT` | 3 | 같은 행 연속 실패 시 영구 실패로 간주할 횟수 |

### 2. 실패 카운터 (메모리)

```python
_failure_counts = {}  # {row_num: count}
```

- 워커 재시작 시 초기화 (의도된 동작 — 사용자가 수정 후 재시작하면 다시 시도 가능)
- 성공 시 카운터 즉시 삭제

### 3. 영구 실패 마킹

```python
def _mark_permanent_failure(row, error_msg):
    spreadsheet = connect_sheet(SHEET_ID)
    ws = spreadsheet.worksheet(TAB_NAME)
    marker = f"❌ 자동 처리 실패 ({FAILURE_LIMIT}회 시도): {error_msg[:120]}"
    ws.update(values=[[marker]], range_name=f"I{row}", value_input_option="USER_ENTERED")
```

→ I(본문)열에 마킹하면 `find_pending_rows()`의 `if body.strip(): continue` 조건에서 걸러져 다음 폴링부터 스킵.

### 4. process_row 시그니처 변경

| 변경 전 | 변경 후 |
| --- | --- |
| `process_row(spreadsheet, api_key, item)` | `process_row(api_key, item)` |

`spreadsheet` 인자 제거 — 함수 내부에서 매번 새로 만든다.

<br>

## 🛡️ 사용자 복구 시나리오

| 상황 | 복구 방법 |
| --- | --- |
| 카테고리 오타로 3회 실패 → I열에 ❌ 마킹됨 | 사용자가 C열 카테고리 수정 + I열의 ❌ 텍스트 삭제 → 다음 폴링에서 재처리 |
| Claude API 일시적 장애로 실패 | 1~2회 실패 후 다음 폴링에서 자동 재시도 (3회 미만이면 마킹 안 됨) |
| 워커 재시작 직후 | 모든 카운터 초기화. 영구 실패 마킹된 행은 그대로 (I열에 마킹 있으니 자동 스킵) |

<br>

## 📊 성능 영향

| 항목 | 영향 |
| --- | --- |
| connect_sheet() 추가 호출 | 1행당 약 0.5~1초 추가 (네트워크 OAuth) |
| 100건 처리 시 총 추가 시간 | 약 1.5분 (전체 1.5시간의 1.6%) |
| 메모리 | `_failure_counts` 딕셔너리 — 무시 가능 |

→ **추가 비용은 무시할 수준, 안정성 이득은 큼.**

<br>

## ✅ 검증

```bash
python -c "import worker; print('OK', worker.FAILURE_LIMIT, worker.POLL_INTERVAL)"
# → OK 3 60
```

<br>

## 📂 변경 파일

- `worker.py` — `_failure_counts`, `_mark_permanent_failure()`, `_record_failure()` 추가, `process_row()` 시그니처 변경

<br>

## 🧭 남은 개선 후보

1. ~~OAuth 토큰 만료~~ ✅ 해결
2. ~~영구 실패 무한 재시도~~ ✅ 해결
3. 처리 중 마커 (H열 "⏳") — 동시 실행 충돌 방지 (단일 인스턴스면 불필요)
4. 시트 onEdit 웹훅 — 폴링 60초 대기 제거
5. 실패 알림 (슬랙/이메일)
