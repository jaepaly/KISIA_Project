-- 시딩 검증 SQL 3줄 (docs/roles/howto/e-sns.md §5)
--
--     sqlite3 data/interim/sns.db < scripts/check_seed.sql

-- 1. 인물별 글 수 — 기대한 대로 들어갔나
SELECT author_id, COUNT(*) FROM posts GROUP BY author_id;

-- 2. 시각이 빈 글이 있나 (0이어야 한다)
SELECT COUNT(*) AS null_created_at FROM posts WHERE created_at IS NULL OR created_at = '';

-- 3. 시간대 분포 — 한 시각에 몰려 있으면 ②가 안 된 것이다
SELECT substr(created_at,12,2) AS h, COUNT(*) FROM posts GROUP BY h ORDER BY h;
