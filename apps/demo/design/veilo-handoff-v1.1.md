# Veilo 웹디자인 핸드오프 v1.1 — 팀 확정본 텍스트 (2026-09-12)

> 원본: 카카오톡으로 받은 `Veilo_웹디자인_디자이너_핸드오프_v1.1.docx` (팀 투표로 확정). 저장소엔 텍스트만 둔다.
> 서비스명 **Veilo / 베일로** — 「베일로 가린다」의 중의. 게시물은 그대로 공유하되, 개인을 특정할 수 있는 단서는 veil 처럼 가린다.
> 로고 심볼 SVG 재현본: `veilo-symbol.svg` (겹친 잎 두 장, Terracotta + Sand).

WEB DESIGN SYSTEM · DESIGNER HANDOFF · v1.1
Veilo 웹디자인 핸드오프 가이드
중요한 이야기는 그대로, 개인을 특정할 수 있는 정보는 더 안전하게.
  Veilo
Share What Matters
문서 목적웹디자이너가 별도 해석 없이 화면 설계를 시작할 수 있도록, 확정된 로고·컬러·레이아웃·컴포넌트·개인정보 보호 UX를 한 문서에 고정한다. 본 문서를 1차 디자인 기준선으로 사용한다.
현재 기준
브랜드명
Veilo
핵심 메시지
Share What Matters / 중요한 이야기는, 그대로.
UI 방향
차분한 웜 뉴트럴 + 컴팩트한 SNS/블로그형 정보 구조
핵심 경험
게시물 작성/열람 중 개인 식별 가능 단서를 감지하고, 부담스럽지 않게 보호 안내
01 · BRAND IDENTITY
로고 시스템
확정 심볼은 겹쳐진 두 개의 잎/베일 형태로, “드러냄과 보호의 균형”을 상징한다. 웹에서는 심볼과 워드마크를 분리해 사용할 수 있으나 형태 비율은 변경하지 않는다.
  Veilo
Primary lockup
Symbol
Square icon
사용 규칙
• 기본형은 밝은 Ivory 배경 위 Charcoal 워드마크 + Terracotta/Sand 심볼을 사용한다.
• 헤더가 좁은 경우 심볼 + “Veilo” 워드마크만 사용하고 슬로건은 생략한다.
• 파비콘/프로필/알림 아이콘에는 심볼 단독형을 사용한다.
• 로고 주변 최소 여백은 심볼 높이의 0.5배 이상 확보한다.
• 금지: 비율 왜곡, 임의 회전, 과도한 그림자, 네온/고채도 색상 치환, 외곽선 추가.
컬러 시스템
Token
Swatch
HEX
Use
Terracotta
#D8896F
Primary / CTA / highlight
Sand
#D9C9B8
Secondary / surface
Taupe
#A89B91
Border / muted UI
Ivory
#F8F3ED
Main background
Charcoal
#3E3A36
Primary text / dark UI
권장 비율  Ivory 60–70% · Charcoal 15–20% · Terracotta 8–12% · Sand/Taupe 8–12%. Terracotta는 액션/강조에만 제한한다.
02 · FOUNDATIONS
타이포그래피
Role
Font
Weight
Desktop
Mobile
Display / Hero
Pretendard
700
36–44px
28–32px
Page title
Pretendard
700
28–32px
22–26px
Section title
Pretendard
600
20–24px
18–20px
Body
Pretendard
400
15–16px
14–16px
English accent
Plus Jakarta Sans
400–600
12–16px
12–14px
문장 톤: 짧고 설명적인 문장. “위험”, “차단”, “경고”를 과도하게 반복하지 않고, 사용자가 선택권을 가진다는 느낌을 유지한다.
레이아웃 및 간격
항목
권장값
디자인 의도
Max content width
1200–1280px
블로그/SNS형 데스크톱 화면의 안정적인 밀도
Desktop grid
12 columns, gutter 24px
프로필 사이드바 + 메인 피드 조합
Page side padding
32px / mobile 16–20px
화면 가장자리 여백 유지
Base spacing
8px
8, 16, 24, 32, 48 단위 사용
Card radius
14–18px
부드럽고 친근한 인상
Button height
40–44px
충분한 클릭 영역
Input height
44–48px
검색/작성 UI 통일
Shadow
매우 약하게 또는 없음
플랫하고 차분한 인상 유지
페이지 구조 기준
• 상단: Veilo 로고 / 검색 / 글쓰기 / 알림 / 프로필 / 전체 메뉴
• 브랜드 헤더: 심볼 + Veilo + 짧은 메시지. 실사 사진 대신 추상 그래픽을 우선한다.
• 카테고리 탭: 홈 · 글 · 사진 · 영상 · 방명록 형태의 단순 탭 구조
• 데스크톱: 좌측 프로필·메뉴 280–320px / 우측 메인 콘텐츠 가변 영역
• 모바일: 사이드바를 접고 상단 메뉴 또는 드로어로 이동
• 정보 구조는 블로그형 익숙함을 참고하되, 특정 외부 서비스의 로고·브랜드 요소를 복제하지 않는다.
03 · UI COMPONENTS
핵심 컴포넌트 규격
Component
Visual
States
Designer note
Primary button
Terracotta fill / Ivory text
default, hover, pressed, disabled
한 화면의 1차 액션만 사용
Secondary button
Ivory/Sand surface / Charcoal text
default, hover, pressed
보조 액션
Search field
Ivory + Taupe border
empty, focused, filled
pill 또는 12px radius
Content card
Ivory/white surface
default, hover, selected
정보 우선
Profile card
Symbol avatar + name + bio
default
짧고 압축적으로
Tabs
Text + 2px active underline
default, active, hover
활성색 Terracotta
Toast / Alert
Ivory surface + small symbol
info, caution, success
보호 기능 알림의 핵심 표현
Privacy chip
Sand/Taupe tint
detected, protected, review
본문 가독성 유지
개인 식별 가능 정보 보호 UX
Veilo의 차별점은 “보호 기능이 눈에 보이되, 글쓰기를 방해하지 않는 것”이다. 경고창 중심이 아니라 작은 알림 → 확인 → 선택의 흐름으로 설계한다.
1. 감지
게시글 입력 중 단서 감지
“개인 식별 가능 정보가 포함될 수 있어요.”
2. 표시
약한 highlight/chip
본문 가독성 유지
3. 선택
가리기 / 그대로 두기 / 자세히 보기
자동 강제 삭제 금지
4. 완료
보호 적용 후 success toast
“식별 가능 정보를 가렸어요.”
알림 비주얼 원칙
• 심볼을 알림 좌측에 20–24px 크기로 사용하면 브랜드 기능을 즉시 연상시키기 좋다.
• Terracotta는 주의/선택 필요 상태에 사용하고, 완료 상태는 보조 상태색으로 분리한다.
• 모달보다 toast, inline banner, chip을 우선한다. 작성 흐름을 멈추게 하지 않는다.
• 문구는 “노출되었습니다”보다 “포함될 수 있어요”, “가려드릴까요?”처럼 부드럽게 표현한다.
04 · RESPONSIVE & SCREEN SPECS
반응형 기준
Viewport
Breakpoint
Layout
Notes
Desktop
≥ 1200px
Left sidebar + main feed
브랜드 헤더 전체 노출
Tablet
768–1199px
Narrow sidebar or collapsible
카드 2열 가능
Mobile
< 768px
Single column
사이드바는 drawer, 카드 1열
우선 제작 화면
Priority
Screen
Required content
Status
P0
메인/홈
상단 검색 + 브랜드 헤더 + 프로필/메뉴 + 주요 게시물 + 최근 게시물
Design needed
P0
게시글 상세
본문, 작성자, 미디어, 보호 처리된 표현 상태, 댓글 영역
Design needed
P0
글쓰기
에디터 + 실시간 감지 + privacy chip + 최종 게시 전 보호 확인
Design needed
P0
보호 알림
toast / inline banner / review panel 상태 세트
Design needed
P1
프로필
소개, 게시글 목록, 카테고리
Design needed
P1
검색 결과
검색어, 필터, 결과 카드
Design needed
P1
알림 센터
댓글/반응 알림과 개인정보 보호 관련 알림을 구분
Design needed
디자인 파일 권장 구조
00_Cover01_Foundations  (Logo / Color / Type / Grid / Spacing)02_Components   (Buttons / Inputs / Cards / Tabs / Alerts / Chips)03_Desktop      (Home / Detail / Write / Profile / Search)04_Mobile       (Responsive variants)05_Prototype    (Privacy detection flow)99_Archive
개발 전달용 디자인 토큰
--veilo-terracotta: #D8896F;   --veilo-sand: #D9C9B8;   --veilo-taupe: #A89B91;--veilo-ivory: #F8F3ED;       --veilo-charcoal: #3E3A36;--radius-card: 16px;  --space-unit: 8px;  --content-max: 1280px;
05 · HANDOFF CHECKLIST
웹디자이너 전달 체크리스트
☐  로고 Primary / Symbol / Icon 세 가지 변형을 컴포넌트화한다.
☐  Foundations 페이지에 컬러·타입·8px spacing·grid를 먼저 고정한다.
☐  웹 화면은 실사 사진보다 추상 도형, 일러스트, UI 중심으로 설계한다.
☐  개인정보 보호 기능은 최소 4상태(감지/검토/보호완료/사용자 유지)를 설계한다.
☐  Desktop·Mobile 두 breakpoint에서 P0 화면을 모두 완성한다.
☐  버튼·입력·탭·카드·알림의 hover/focus/disabled 상태를 포함한다.
☐  텍스트 대비와 키보드 focus가 보이도록 접근성을 확인한다.
☐  개발 전달 시 토큰명과 컴포넌트명을 디자인 파일과 동일하게 맞춘다.
☐  확정 전 임의로 브랜드 색/심볼 형태를 변경하지 않는다.
디자이너에게 전달할 한 문장
“Veilo는 블로그형 SNS의 익숙한 구조 위에, 개인을 특정할 수 있는 단서를 자연스럽게 감지·보호하는 경험을 얹는 서비스입니다. 보호 기능이 강한 보안 솔루션처럼 보이기보다, 차분하고 친근한 일상형 웹서비스로 느껴지게 디자인해 주세요.”
최종 산출물 기대치
• Figma Foundations + Components + Desktop/Mobile screen set
• Privacy detection flow prototype
• 개발자가 inspect 가능한 spacing/color/type tokens
• 로고 원본을 변형하지 않은 SVG/PNG export set
Version 1.1 · 디자인 기준선. 브랜드/기능 정책 변경 시 버전을 올려 갱신합니다.
