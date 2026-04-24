# 🔗 Handoff — 배너 링크 원본 URL 수집 + 중복 제거

> 📅 2026-03-20
> 📁 `발행검수\main.py` → `scrape_blog()` step 6 JS
> 🏷️ v1.5 → v1.6

---

## 🎯 해결한 문제

### 1. 광고 링크 미인식 (`_bc05` 파라미터 소실)

**현상:** 상품/광고가 같은 MKT ID를 공유하고 `nt_detail`의 `_bc05` 접미사로만 구분되는 경우, 프로그램이 광고 링크를 인식 못하고 "광고 링크 미삽입" 오탐

**원인:** 네이버 블로그 JS가 oglink 배너의 `<a>` 태그 href를 렌더링할 때 일부 쿼리 파라미터를 수정/제거. `a.href`로 수집하면 `_bc05`가 소실됨. 반면 `data-linkdata` HTML 속성에는 원본 URL이 보존.

**수정 위치:** `scrape_blog()` step 6 JS (약 540행)

**수정 내용:**
```javascript
// 배너 <a> 감지 후, data-linkdata에서 원본 MKT URL 우선 추출
var dlEl = a.closest('[data-linkdata]');
if (dlEl) {
    var dlData = dlEl.getAttribute('data-linkdata') || '';
    var mktUrls = dlData.match(/https?:\/\/mkt\.[^\s"'<>,}]+/g);
    if (mktUrls && mktUrls.length > 0) { h = mktUrls[0]; }
}
```

### 2. 배너 링크 중복 표시

**현상:** 1개 oglink 배너가 2~3건으로 중복 수집됨 (배너 내부 `<a>` 태그 여러 개: 썸네일, 제목 등)

**수정 내용:**
```javascript
var processedBanners = [];
// ...loop...
var bannerRoot = a.closest('.se-module-oglink') ||
                 a.closest('.se-section-oglink') ||
                 a.closest('[data-linkdata]');
if (bannerRoot && processedBanners.indexOf(bannerRoot) !== -1) continue;
if (bannerRoot) processedBanners.push(bannerRoot);
```

---

## 📊 검증 포인트

- 같은 MKT ID + 다른 `nt_detail` (예: `_bc05`) → 상품/광고 각각 정확히 매칭되는지
- 블로그에 배너 N개 → 링크 목록에 정확히 N건 표시되는지
- `data-linkdata` 없는 블로그 → `a.href` fallback 정상 동작하는지
- 이미지/텍스트 링크 수집에 영향 없는지
