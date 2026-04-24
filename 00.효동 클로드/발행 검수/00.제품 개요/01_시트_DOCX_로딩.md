# 01. 시트 조회 + DOCX 다운로드/파싱

> main.py: `fetch_items()`, `find_and_download()`, `parse_docx()`

---

## 1. 시트 조회 (fetch_items)

### 사용 탭

| 탭 | 용도 | 조인 키 |
|----|------|---------|
| 자사 발행리스트 | 발행 건 목록 | H열(파라미터) |
| 원고리스트 | 원고 메타데이터 | J열(파라미터) |

### 자사 발행리스트 컬럼

| 열(idx) | 내용 |
|---------|------|
| A(0) | 날짜 |
| H(7) | 파라미터 |
| L(11) | 제목 |
| M(12) | 발행 링크 (블로그 URL) |
| N(13) | 발행처 |

### 원고리스트 컬럼

| 열(idx) | 내용 |
|---------|------|
| J(9) | 파라미터 (조인 키) |
| AB(27) | 상품 링크 |
| AC(28) | 광고 링크 |
| AG(32) | DOCX 파일명 |

### 날짜 매칭

`date_variants(d)` → 6가지 형식으로 유연 매칭:
`M/D`, `MM/DD`, `MM/D`, `M/DD`, `YYYY-MM-DD`, `YYYY.MM.DD`

### 반환 구조

```python
item = {
    "row": 2, "param": "효동_고혈압",
    "title": "고혈압 관리법",
    "link": "https://blog.naver.com/...",
    "publisher": "업체명",
    "product_link": "https://mkt.shopping.naver.com/...",
    "ad_link": "https://smartstore.naver.com/...",
    "filename": "작성자_260316고혈압_후기형_bc.docx",
}
```

---

## 2. DOCX 다운로드 (find_and_download)

### 2단계 검색

| 단계 | 방식 |
|------|------|
| 1차 | 전체 파일명으로 Drive 검색 |
| 2차 | `_strip_pub_date()`로 날짜 패턴 제거 후 재검색 |

### 파일 우선순위
DOCX > ZIP > 기타

### ZIP 처리
ZIP 내 첫 `.docx` 파일 자동 추출 (`__MACOSX/` 제외)

---

## 3. DOCX 파싱 (parse_docx)

### 반환 구조

```python
{
    "instructions": [...],      # 지시사항 (ㄴ줄, ★요청사항★, 해시태그 등)
    "image_numbers": [...],     # 이미지 번호 ("1", "2,3,4" 등)
    "ad_links": [...],          # 광고 링크 URL
    "content": [...],           # 본문 (5자 이상 텍스트)
    "format_reqs": [...],       # 서식 요구 [{text, quote, font_size, bold, color}]
    "full_text": "",            # 전체 텍스트
}
```

### 파싱 규칙

| 라인 유형 | 판별 기준 | 분류 |
|----------|-----------|------|
| ★요청사항★ 블록 | `★...요청...★` ~ `---` | instructions |
| ㄴ지시사항 | ㄴ접두사 + INSTRUCTION_KEYWORDS 매칭 or ≤30자 | instructions |
| ㄴ서식 | ㄴ접두사 + 서식 정보 포함 | content + format_reqs |
| 이미지 번호 | regex `^(\d{1,2}|(\d{1,2},\s*)+)$` | image_numbers |
| URL | `https?://` 포함 | ad_links (쇼핑 링크만) |
| 본문 | 길이 ≥5자 | content |

### INSTRUCTION_KEYWORDS (47개, 예시)

```
글씨, 글자, 폰트, 크기, 색, 컬러, 볼드, 두껍게, 밑줄, 기울임,
형광, 하이라이트, 인용, 정렬, 가운데, 왼쪽, 오른쪽, 제목, 소제목,
구분선, 줄간격, 자간, 배경, 스티커, 지도, 동영상, 해시, 태그, ...
```

---

## 4. 평가

**잘된 점:**
- 파라미터 조인으로 발행리스트↔원고리스트 자동 매칭
- 2단계 검색 + 날짜 패턴 제거로 파일명 변형 대응
- ZIP 자동 해제 지원
- 47개 키워드로 지시사항/서식 정확히 분류

**부족한 점:**
- DOCX 다운로드 실패 빈번 — 파일명 변형 패턴이 더 다양할 수 있음
- Drive 검색이 순차적 (2단계) — 시간 소요
- 서식 요구 파싱이 regex 기반 → 복잡한 ㄴ지시에서 누락 가능
