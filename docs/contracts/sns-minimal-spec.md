# 가상 SNS 최소 스펙 v0.1

> 소유: E 이지희 · 컴포넌트 ⑦
> 이 문서가 계약 4종의 텍스트 채널 목록을 결정한다.
> 여기 없는 칸은 다른 계약에도 없다.

## 1. 글

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `post_id`       | 문자열 | 필수 | 글의 식별자. 가상 SNS 가 발급한다 |
| `user_ref`      | 문자열 | 필수 | 이 글을 쓴 사용자. §2 사용자의 `user_ref` 값을 참조한다 |
| `title`         | 문자열 | 선택 | 제목 |
| `body`          | 문자열 | 필수 | 본문 |
| `photos`        | 배열   | 선택 | 사진 목록. 각 원소에 `caption` |
| `post_date`     | 문자열 | 필수 | 작성 날짜 `YYYY-MM-DD` (시각 없음). 「작성일 + n주차」 시점 역산의 기준점 (#332) |
| `activity_meta` | 객체   | 필수 | `{ nickname, geo_tag, post_time }`. 조치 ②(활동 메타 관리) 대상 |

※ 사진이 여러 장이면 캡션도 여러 개다. 순서를 보존한다. 스팬·복원키는 `photo_caption:0`, `photo_caption:1` 형식(콜론+숫자)으로 몇 번째 사진인지 가리킨다.

※ 작성 일시는 둘로 나눠 내보낸다 — 날짜는 `post_date`, 시각은 `activity_meta.post_time`(`HH:MM`). 시각은 조치 ②가 감추는 대상이라 `post_date` 에 넣지 않는다. 참고로 `stage2-io.schema.json` 의 `post_time` 은 `format: date-time` 이라 이 export 의 `post_time`(`HH:MM`)과 형식이 다르다. 지금 분석기는 `post_time` 을 2단 입력에 넘기지 않는다. 넘기게 되면 `post_date` 와 합쳐 date-time 으로 바꿔 넣어야 한다.

## 2. 사용자

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `user_ref`    | 문자열 | 필수 | 익명 핸들. 형식 `^u_[0-9a-f]{8,}$` |
| `nickname`    | 문자열 | 필수 | 닉네임 |
| `profile_bio` | 문자열 | 선택 | 프로필 소개란 |

## 3. 텍스트 채널 — 계약이 참조하는 목록

| 채널 | 단위 | 있음? |
|---|---|---|
| `title`         | 글          | 예 |
| `body`          | 글          | 예 |
| `photo_caption` | 글 (여러 개, `photo_caption:0` 형식) | 예 |
| `profile_bio`   | 사용자       | 예 |

## 4. 활동 메타 — 조치 대상이 되는 필드

| 필드 | 설명 |
|---|---|
| `nickname`  | 글에 표시되는 닉네임 |
| `geo_tag`   | 위치 태그 |
| `post_time` | 작성 시각 |

조치 추천(D 계약의 `Action.targets`)이 이 셋을 개별적으로 지목해서 "이 값을 바꾸면 위험도가 낮아진다"고 추천한다.

## 5. 분석 도구에 넘기지 않는 것

- 실명 · 이메일 · 전화번호 (애초에 수집하지 않는다)
- 비밀번호 · 로그인 정보
- 플랫폼 내부 값 — `author_id` · `source` · `visibility` (공개 글만 나가므로 visibility 는 필요 없다)

## 6. 분석 도구가 읽는 창구 — 둘뿐이다

| 창구 | 응답 | 쓰는 곳 |
|---|---|---|
| `GET /api/export/<user_ref>` | §1 글 · §2 사용자 (공개 글만) | 분석의 입력 전부 |
| `GET /api/authors?q=<검색어>` | `[{ user_ref, nickname, n_posts }]` — 닉네임·`user_ref` 앞부분으로 최대 12명 · `n_posts` 는 공개 글 수 | 스캔 화면 계정 찾기 (식별자를 외워 오게 하지 않는다) |

- 분석 도구는 이 둘을 `apps/analyzer/adapters/sns_adapter.py` 로만 부른다 — 화면(브라우저)이 가상 SNS 를 직접 부르지 않는다
- 방문자별 사본을 쓰는 서버에서는 두 창구 모두 `X-Veilo-Session` 헤더로 그 방문자의 사본을 읽는다
- 화면 연결 주소: 가상 SNS → 분석 앱은 `PADO_BASE`(기본 `/check`), 분석 앱 → 가상 SNS 는 `SNS_PUBLIC_URL`(기본 같은 도메인 루트). 링크·주소일 뿐 데이터 창구가 아니다
