# handoff 260410 — 시트 자동 워커 + N열 모델

> 작업일: 2026-04-10<br>
> 버전: v1.2 → **v1.3**<br>
> 작업자: 효동(Claude Opus 4.6) + 효진

<br>

## 🎯 작업 목적

> "구글 시트에 일부 작성일 / 채널 / 카테고리 / 구조 / 키워드 입력해 두면 원고가 자동으로 뽑히면 좋겠어. 웹이랑 별도로 돌아가는 거야. 담당자는 원고에 영향 안 끼치니까 상관 없고, n열에 모델 칸 새롭게 만들게. 모델에 따로 안 써 있으면 sonnet으로 돌려주고, 체크 표시해 두면 opus로 돌려줘"

→ 웹 UI를 거치지 않고 시트만 채우면 백그라운드에서 자동 생성되는 워커가 필요.

<br>

## 🔁 Before / After

### Before (v1.2)

```
사용자 → 웹 UI → 카테고리/구조/키워드 입력 → 생성 → 시트 새 행 A~M 기입
```

- 한 번에 1건씩, 손으로 직접 입력
- 대량 처리 시 사람이 계속 클릭해야 함

### After (v1.3)

```
사용자 → 시트 빈 행 A~E 입력 (+ N 체크 선택) → 알아서 끝
                                    ↓
       워커 (60초 폴링) → 빈 행 발견 → 원고 생성 → 같은 행 H~M 채움
```

- 사용자가 미리 키워드 여러 개 입력만 해 두면 워커가 알아서 다 처리
- 웹은 그대로 즉시 생성용으로 유지 (둘 다 가능)

<br>

## 🛠️ 구현 변경

### 1. `generator.py` (신규)

원고 생성 / 채점 / 포스트 분할 로직을 모듈로 분리. 웹과 워커가 같은 함수를 호출.

```python
def generate_aeo(api_key, category, structure_key, channel, keyword, model_key="Sonnet"):
    """Returns: {"manuscript", "score_result", "post_text", "posts"}"""
```

→ 코어 로직 변경 시 한 곳만 수정하면 됨.

<br>

### 2. `sheet_writer.py`

#### HEADERS에 N열 추가

```python
HEADERS = [
    "발행일", "채널", "카테고리", "구조", "키워드",
    "담당자", "발행 링크", "제목", "본문",
    "문단 구분 글", "AEO 점수", "등급", "영역별 점수",
    "모델"  # ← 추가
]
```

#### `update_aeo_row()` 신규

```python
def update_aeo_row(spreadsheet, row, manuscript, score_result=None, post_split_text=""):
    """기존 행의 H~M만 업데이트. A~G·N 보존."""
    cell_range = f"H{row}:M{row}"  # 정확한 범위
    ws.update(values=[row_data], range_name=cell_range, value_input_option="USER_ENTERED")
```

→ 워커가 사용. 사용자 입력 영역(A~G)과 모델 체크(N)는 절대 안 건드림.

#### `_set_row_height()` 헬퍼 추출

기존에 `write_aeo_result()`에 있던 행 높이 21px 고정 코드를 별도 함수로 분리. `update_aeo_row()`도 동일하게 사용.

<br>

### 3. `app.py` 리팩터

기존 `_call_claude()`와 인라인된 카테고리 검색·프롬프트 조립·채점·분할 로직을 모두 제거. `generator.generate_aeo()` 한 줄로 대체.

```python
# Before
prompt = build_aeo_prompt(...)
manuscript = _call_claude(api_key, prompt, model_key)
score_response = _call_claude(...)
score_result = parse_score_response(...)
posts = split_into_posts(manuscript)
post_text = format_posts_for_display(posts)

# After
result = generate_aeo(api_key, category, structure_key, channel, keyword, model_key)
manuscript = result["manuscript"]
score_result = result["score_result"]
post_text = result["post_text"]
posts = result["posts"]
```

<br>

### 4. `worker.py` (신규)

```python
POLL_INTERVAL = int(os.environ.get("WORKER_POLL_INTERVAL", "60"))

def parse_model(cell_value):
    """N열 → 모델 키 ('TRUE','체크','O','OPUS' 등 → Opus, 그 외 → Sonnet)"""

def find_pending_rows(ws):
    """A~E 채워졌고 I 비어 있는 행 탐색 (2행부터, 14열까지 패딩)"""

def process_row(spreadsheet, api_key, item):
    result = generate_aeo(...)
    update_aeo_row(spreadsheet, item["row"], ...)

def main():
    while True:
        spreadsheet = connect_sheet(SHEET_ID)
        ws = spreadsheet.worksheet(TAB_NAME)
        for item in find_pending_rows(ws):
            process_row(spreadsheet, api_key, item)
        time.sleep(POLL_INTERVAL)
```

- Google credentials base64 디코딩 로직은 app.py와 동일하게 복사 (별도 모듈로 분리하지 않음 — 단순함 유지)
- 실패해도 다음 행/다음 루프 계속 (예외는 잡고 로그만 출력)

<br>

### 5. `Procfile`

```diff
  web: gunicorn app:app --bind 0.0.0.0:$PORT --timeout 300 --workers 2
+ worker: python worker.py
```

Railway에서 worker 프로세스를 활성화하면 백그라운드로 계속 돌아감.

<br>

## 🔬 N열 모델 해석 로직

```python
def parse_model(cell_value):
    if cell_value is None: return "Sonnet"
    s = str(cell_value).strip().upper()
    if not s: return "Sonnet"
    if s in ("TRUE", "O", "OPUS", "체크", "1", "Y", "YES", "V"):
        return "Opus"
    return "Sonnet"
```

| N열 셀 값 | 결과 |
| --- | --- |
| (빈 셀) | Sonnet |
| 체크박스 ✅ → "TRUE" | Opus |
| 체크박스 ❌ → "FALSE" | Sonnet |
| "O" / "체크" / "Opus" | Opus |
| 그 외 임의 텍스트 | Sonnet (안전한 기본값) |

→ 사용자가 체크박스를 만들든, "체크"라고 적든, "O"라고 적든 모두 Opus로 처리.

<br>

## 🛡️ 데이터 보호

| 보호 대상 | 방법 |
| --- | --- |
| A~G(사용자 입력 영역) | 워커는 `H{row}:M{row}` 범위만 update |
| N(모델 선택) | 워커는 N열 read만, write 안 함 |
| 시트 사전 설정 드롭다운/색상 chip | 사전 설정 그대로 보존 (이전 v1.2에서 처리한 부분 그대로) |
| 행 추가 시 뒷 데이터 영향 | 워커는 신규 행 추가 안 함, 기존 행 update만 |

<br>

## ✅ 검증

```bash
python -c "import generator; import worker; import app; import sheet_writer; print('OK')"
# → OK
```

모든 import 성공. 실 시트 테스트는 사용자가 다음 단계로 진행 예정.

<br>

## 📂 변경 파일

| 파일 | 변경 종류 |
| --- | --- |
| `generator.py` | 신규 |
| `worker.py` | 신규 |
| `sheet_writer.py` | HEADERS N열 추가, `update_aeo_row()` `_set_row_height()` 추가 |
| `app.py` | generator 사용으로 리팩터, 미사용 import 정리 |
| `Procfile` | worker 프로세스 추가 |

<br>

## 🧭 다음 작업 후보

1. 처리 중 마커 (H열 "⏳") — 동시 실행 충돌 방지
2. 실패 카운트/스킵 로직 — 영구 실패 방지
3. 시트 onEdit 웹훅 — 60초 대기 제거
4. 시트에 워커 상태 표시 (마지막 체크 시각, 처리 건수)
