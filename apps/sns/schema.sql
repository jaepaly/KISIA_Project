-- 가상 SNS v0 스키마.
--
-- 정본은 docs/contracts/sns-minimal-spec.md 다. 이 파일이 아니다.
-- 필드마다 왜 있는지는 docs/roles/howto/e-sns.md §3 에 적혀 있다.
--
-- ⚠️ post_time 을 컬럼으로 만들지 않는다. created_at 에서 파생시킨다.
--    같은 사실을 두 곳에 저장하면 한쪽만 고쳐졌을 때 조용히 어긋난다.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS authors (
  author_id   TEXT PRIMARY KEY,          -- 'S01' — 합성 인물 ID 와 같게 맞춘다 (플랫폼 내부용)
  user_ref    TEXT NOT NULL UNIQUE,      -- 'u_3f2a91c4' — 계약이 요구하는 익명 핸들 ^u_[0-9a-f]{8,}$
  nickname    TEXT NOT NULL,             -- 활동 메타 ①. 그 자체가 단서다
  bio         TEXT,                      -- 채널 profile_bio
  joined_at   TEXT NOT NULL              -- ISO8601 'YYYY-MM-DDTHH:MM:SS+09:00'
);

CREATE TABLE IF NOT EXISTS posts (
  post_id     TEXT PRIMARY KEY,          -- 'S01_b07'
  author_id   TEXT NOT NULL REFERENCES authors(author_id),
  title       TEXT,                      -- 채널 title
  body        TEXT NOT NULL,             -- 채널 body
  created_at  TEXT NOT NULL,             -- 활동 메타 ③. 임의 지정 가능해야 한다
  geo_tag     TEXT,                      -- 활동 메타 ②. '용인시 기흥구' 또는 NULL
  visibility  TEXT NOT NULL DEFAULT 'public'
                CHECK (visibility IN ('public','private')),
  source      TEXT NOT NULL DEFAULT 'manual'
                CHECK (source IN ('manual','seed'))
);

-- 채널 photo_caption:N. 한 글에 여러 장이라 별도 테이블이다.
-- idx 는 0 부터다 — label-schema §5-3 이 「0부터, texts[] 배열 인덱스와 어긋나지 않게」로 못박았다.
CREATE TABLE IF NOT EXISTS photos (
  post_id     TEXT NOT NULL REFERENCES posts(post_id),
  idx         INTEGER NOT NULL,
  caption     TEXT,
  PRIMARY KEY (post_id, idx)
);

CREATE INDEX IF NOT EXISTS idx_posts_author_created
  ON posts(author_id, created_at DESC);

-- ── 방문자 체험용 (세션 사본마다 따로) — export 에는 나가지 않는다 ──
-- 시드 사본·옛 세션 사본엔 이 표가 없다 → db.ensure_visitor_tables() 가 열 때마다 IF NOT EXISTS 로 만든다.

-- 「내 계정」 — 방문자가 고른 가상 인물 하나. 행은 늘 0개나 1개다
CREATE TABLE IF NOT EXISTS me (
  id          INTEGER PRIMARY KEY CHECK (id = 1),
  author_id   TEXT NOT NULL,
  chosen_at   TEXT NOT NULL
);

-- 조치 이력 — 비공개·공개 전환 · 위치 태그 변경 · 고쳐 쓰기(새 글로 옮김). 되돌리기의 재료.
-- posts 에 FK 를 걸지 않는다: 되돌리기·「처음 상태로」가 글을 지워도 이력은 남아야 한다
CREATE TABLE IF NOT EXISTS action_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  at          TEXT NOT NULL,             -- ISO8601 KST
  kind        TEXT NOT NULL CHECK (kind IN ('private','public','geo','rewrite')),
  author_id   TEXT NOT NULL,
  post_id     TEXT NOT NULL,             -- 바꾼 글 (rewrite 는 원래 글)
  before_val  TEXT,                      -- 바꾸기 전 값 (visibility · geo_tag)
  after_val   TEXT,
  new_post_id TEXT,                      -- rewrite 로 새로 올린 글
  undone_at   TEXT                       -- 되돌렸으면 그 시각. NULL 이면 아직 살아 있는 조치
);

CREATE INDEX IF NOT EXISTS idx_action_log_author ON action_log(author_id, undone_at);

-- 위험 배지 — 「내 계정」 글의 단서 수. 브라우저가 글 점검 API 로 센 값을 저장해 두고 다시 부르지 않는다.
-- body_hash 가 지금 본문과 다르면 무효 (본문이 바뀌면 다시 센다)
CREATE TABLE IF NOT EXISTS clue_cache (
  post_id     TEXT PRIMARY KEY,
  body_hash   TEXT NOT NULL,
  n_clues     INTEGER NOT NULL,
  at          TEXT NOT NULL
);
