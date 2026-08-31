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
