// 세 화면 <head> 에서 가장 먼저 — Veilo 주소를 정하고 Veilo 디자인(veilo.css · 글꼴 · 파비콘)을 붙인다.
// 파도풀 화면이 Veilo 안의 한 화면으로 보여야 한다 — 상단바 · 글꼴 · 색은 veilo.css 를 그대로 쓰고, 파도풀 전용만 style.css 에.
//
// Veilo 주소(VEILO_BASE):
//   - config.js 의 SNS_PUBLIC (server.py SNS_PUBLIC_URL) 이 있으면 그것 — 로컬 분리 실행은 SNS_PUBLIC_URL=http://localhost:3000
//   - 비어 있고 이 화면이 /check/static/ 아래면(인스턴스 · 같은 도메인) 루트 "" — /static/veilo.css 는 Veilo 것이다
//   - 비어 있고 분석기를 따로 띄운 로컬(/static/…)이면 같은 호스트의 3000 — 이때 /static/ 은 분석기 자신의 폴더라 Veilo 가 아니다
window.VEILO_BASE = window.SNS_PUBLIC
  || (location.pathname.indexOf("/static/") === 0 ? location.protocol + "//" + location.hostname + ":3000" : "");

// 파서가 멈춘 자리에서 바로 써야 첫 그림부터 Veilo 모양이다 (나중에 붙이면 맨 모양이 한 번 깜빡인다).
// style.css 는 이 스크립트 다음 줄에 있어 veilo.css 보다 뒤에 적용된다
// 글꼴도 Veilo 것을 그대로 받는다 — 운영(같은 도메인)에서는 Veilo 화면과 주소가 같아 브라우저 캐시를 나눠 쓴다.
// 분석기에 따로 사본을 두면 「내 글 점검」으로 넘어갈 때 같은 글꼴을 다른 주소로 또 받는다.
// 로컬 분리 실행(:8000 → :3000)은 교차 출처 글꼴이라 Veilo 가 /static/fonts/ 에 CORS 헤더를 붙인다 (Veilo 앱)
document.write(
  '<link rel="icon" type="image/svg+xml" href="' + window.VEILO_BASE + '/static/padopool-symbol.svg">' +
  '<link rel="stylesheet" href="' + window.VEILO_BASE + '/static/fonts/pretendard.css">' +
  '<link rel="stylesheet" href="' + window.VEILO_BASE + '/static/veilo.css?v=381">'
);
