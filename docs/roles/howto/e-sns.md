# 가상 SNS 만드는 법 (E 실무)

> **화면 4개 · 테이블 2개 · API 1개.** 그게 전부다.
> 스펙은 W2에 문서로, 구현은 W3에 골격, W4~W6에 시딩·메타.
> 배경은 [E-system.md §4](../E-system.md).

---

## 0. 무엇을 만드는 게 아닌지부터

**우리 제품이 아니다.** 이건 네이버 블로그·인스타그램이 있어야 할 자리를 대신하는 **실험 환경**이다. 그래서:

| ✗ 하지 않는다 | ○ 한다 |
|---|---|
| 로그인·회원가입·비밀번호 | 작성자를 **드롭다운으로 선택** (실험 환경이므로) |
| 좋아요·댓글·팔로우·알림 | **글 목록 / 본문 / 작성 / 프로필** 4개 |
| 반응형 디자인·다크모드 | 브라우저에서 읽히기만 하면 된다 |
| React·SPA·상태관리 | **서버가 HTML을 그려서 준다** |
| 배포·도커·CI | `python app.py` 로 뜨면 된다 |

> ⚠️ **비밀번호를 다루지 않는 것이 설계다.** 인증을 붙이면 계정·비밀번호라는 개인정보가 생기고, 개인정보 트랙 팀이 그걸 SQLite에 평문으로 두는 그림이 된다. **처음부터 만들지 않는다.**

**심사에서 보는 것은 화면 완성도가 아니라 *"글이 쌓이면 위험이 올라간다"* 는 현상이다.** 거기에 필요한 최소가 위 4개다.

---

## 1. 기술 스택 — 30분 안에 정한다

### 권장

| | 무엇 | 왜 |
|---|---|---|
| 언어 | **Python** | B·C·D의 산출물이 전부 파이썬 함수다. 다른 언어를 쓰면 프로세스 경계가 하나 더 생긴다 |
| SNS 서버 | **Flask + Jinja2 템플릿** | 서버가 HTML을 만들어 주는 가장 짧은 길. 파일 2개면 뜬다 |
| 분석기 서버 | **FastAPI** (또는 Flask) | JSON API가 주력. 어느 쪽이든 상관없다 |
| DB | **SQLite** | 파일 하나. 서버 설치가 없다. `.env`에 이미 `SNS_DB_URL=sqlite:///./data/interim/sns.db` |
| ORM | **쓰지 않는다.** `sqlite3` 표준 모듈 + 생 SQL | 테이블이 2개다. ORM을 배우는 시간이 더 든다 |

```bash
pip install flask jinja2 fastapi uvicorn python-multipart check-jsonschema
```

### 폴백 — 다른 걸 써도 된다

익숙한 스택이 따로 있으면 그걸 쓴다. **조건은 2개뿐이다.**

1. **분석기는 파이썬**이어야 한다 (모델을 직접 부른다)
2. **SNS와 분석기는 다른 프로세스, 다른 포트**여야 한다 (`.env`: SNS 3000 / 분석기 8000)

이 둘만 지키면 프레임워크는 아무래도 좋다.

---

## 2. 디렉터리 — 계층이 폴더로 보여야 한다

```
apps/
├─ sns/                     ⑦ 가상 SNS 플랫폼   포트 3000
│  ├─ app.py
│  ├─ schema.sql
│  ├─ db.py
│  └─ templates/            list.html · post.html · new.html · profile.html
└─ analyzer/                ⑥ 분석 도구         포트 8000
   ├─ app.py
   ├─ adapters/             sns_adapter.py · file_adapter.py
   ├─ engines/              c1~c4 호출 래퍼 (초기엔 mock)
   ├─ external.py           ⚠️ 외부 호출은 이 파일에만
   └─ templates/            scan.html · diagnose.html · act.html
```

`.github/CODEOWNERS`에 `/apps/ @팀원E` 줄이 이미 준비되어 있다.

> **폴더가 두 개로 갈려 있는 것 자체가 발표 자료다.** *"두 계층을 분리했다"* 를 말로 하는 것보다 트리를 보여주는 쪽이 빠르다.

---

## 3. 데이터 모델 — 테이블 2개

### `apps/sns/schema.sql`

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS authors (
  author_id   TEXT PRIMARY KEY,          -- 'S01' — 합성 인물 ID와 같게 맞춘다
  nickname    TEXT NOT NULL,             -- 활동 메타 ①. 그 자체가 단서다
  bio         TEXT,
  joined_at   TEXT NOT NULL              -- ISO8601 'YYYY-MM-DDTHH:MM:SS+09:00'
);

CREATE TABLE IF NOT EXISTS posts (
  post_id     TEXT PRIMARY KEY,          -- 'S01_b07'
  author_id   TEXT NOT NULL REFERENCES authors(author_id),
  title       TEXT,
  body        TEXT NOT NULL,
  created_at  TEXT NOT NULL,             -- 활동 메타 ③. 임의 지정 가능해야 한다
  geo_tag     TEXT,                      -- 활동 메타 ②. '용인시 기흥구' 또는 NULL
  visibility  TEXT NOT NULL DEFAULT 'public'
                CHECK (visibility IN ('public','private')),
  source      TEXT NOT NULL DEFAULT 'manual'
                CHECK (source IN ('manual','seed'))
);

CREATE INDEX IF NOT EXISTS idx_posts_author_created
  ON posts(author_id, created_at DESC);
```

### 필드마다 이유가 있다

| 필드 | 없으면 |
|---|---|
| `nickname` `geo_tag` `created_at` | **조치 ②「활동 메타 관리」를 시연할 수 없다.** 선행 PoC 자체 측정에서 조치 3종 중 **위험도 감소 폭 1위**가 이것이었다. 이 세 필드가 이 플랫폼을 만드는 가장 큰 이유다 |
| `visibility` | **조치 ③「비공개」를 시연할 수 없다.** 글을 지워서 보여주면 되돌릴 수 없어 리허설을 두 번 못 한다 |
| `source` | 시딩된 글과 시연 중 손으로 쓴 글이 섞여 구분이 안 된다 |
| `created_at`이 ISO8601 **문자열** | SQLite에는 날짜 타입이 없다. ISO8601 문자열은 **정렬 순서 = 시간 순서**라 인덱스가 그대로 먹는다 |

### `post_time`을 컬럼으로 만들지 않는다 ⚠️

계약([DEC-001](../../decisions.md))의 `activity_meta`에는 `post_time`이 있지만, **DB에는 두지 않는다.** `created_at`에서 뽑아 쓴다.

```python
post_time = created_at[11:16]      # '23:41'
```

같은 사실을 두 컬럼에 저장하면 한쪽만 고쳐졌을 때 조용히 어긋난다. **파생값은 파생시킨다.**

---

## 4. 화면 4개와 라우트

| 화면 | 라우트 | 보여줄 것 |
|---|---|---|
| 글 목록 | `GET /` | 최신순. 작성자 필터. `visibility='private'`는 회색으로 표시 |
| 글 본문 | `GET /posts/<post_id>` | 제목·본문·작성시각·위치태그·작성자 |
| 글 작성 | `GET /new` · `POST /posts` | 작성자 선택 · 제목 · 본문 · 위치태그 · **작성시각 직접 입력** |
| 프로필 | `GET /u/<author_id>` | 닉네임·소개·그 사람 글 목록·글 수 |
| **내보내기** | `GET /api/export/<user_ref>` | ⭐ **입력 어댑터. 분석기는 여기만 본다** |

### 작성 화면에서 작성시각을 직접 입력받는다

실제 SNS에는 없는 기능이지만 **여기서는 있어야 한다.**

- 시연에서 *"이 사람은 새벽 2시에 글을 자주 쓴다 → 육아 또는 교대근무"* 를 보여주려면 시각을 흩뿌려야 한다
- 외부 플랫폼은 발행일 소급이 불가해서 이 항목을 포기했었다. 자체 플랫폼이라 복구된 것이다 ([DEC-001](../../decisions.md))

기본값은 현재 시각으로 채워두고, 고칠 수 있게만 해둔다.

### `app.py` 골격

```python
# apps/sns/app.py
import os, sqlite3, json
from flask import Flask, g, render_template, request, redirect, jsonify

DB = os.getenv("SNS_DB_PATH", "data/interim/sns.db")
app = Flask(__name__)

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row     # dict 처럼 쓸 수 있게
    return g.db

@app.teardown_appcontext
def close(_):
    if (c := g.pop("db", None)):
        c.close()

@app.get("/")
def index():
    author = request.args.get("author")
    q = "SELECT * FROM posts"
    args = []
    if author:
        q += " WHERE author_id = ?"
        args.append(author)
    q += " ORDER BY created_at DESC LIMIT 200"
    posts = db().execute(q, args).fetchall()
    authors = db().execute("SELECT * FROM authors ORDER BY author_id").fetchall()
    return render_template("list.html", posts=posts, authors=authors)

@app.get("/posts/<post_id>")
def detail(post_id):
    p = db().execute("SELECT * FROM posts WHERE post_id=?", (post_id,)).fetchone()
    return render_template("post.html", p=p)

@app.get("/new")
def new_form():
    authors = db().execute("SELECT * FROM authors ORDER BY author_id").fetchall()
    return render_template("new.html", authors=authors)

@app.post("/posts")
def create():
    f = request.form
    pid = f["post_id"] or f"{f['author_id']}_m{os.urandom(3).hex()}"
    db().execute(
        "INSERT INTO posts(post_id,author_id,title,body,created_at,geo_tag,source)"
        " VALUES(?,?,?,?,?,?, 'manual')",
        (pid, f["author_id"], f["title"], f["body"], f["created_at"], f.get("geo_tag") or None))
    db().commit()
    return redirect(f"/posts/{pid}")

@app.post("/posts/<post_id>/visibility")
def toggle(post_id):
    """조치 ③ 비공개 — 사용자가 '플랫폼에서' 실행한다. 분석기가 아니다"""
    v = request.form["visibility"]          # 'public' | 'private'
    db().execute("UPDATE posts SET visibility=? WHERE post_id=?", (v, post_id))
    db().commit()
    return redirect(f"/u/{request.form['author_id']}")

@app.get("/u/<author_id>")
def profile(author_id):
    a = db().execute("SELECT * FROM authors WHERE author_id=?", (author_id,)).fetchone()
    posts = db().execute(
        "SELECT * FROM posts WHERE author_id=? ORDER BY created_at DESC", (author_id,)).fetchall()
    return render_template("profile.html", a=a, posts=posts)

# ⭐ 이 함수는 apps/sns/app.py 에 이미 채워져 있다 (D 가 계약에 맞춰 넣었다).
# 계약 적합성은 apps/sns/test_export.py 가 강제한다 — 고칠 때 그 테스트를 돌린다.
#
#     python -m pytest apps/sns/test_export.py

if __name__ == "__main__":
    app.run(port=int(os.getenv("SNS_PORT", 3000)), debug=True)
```

### 이 코드에서 계층 경계가 드러나는 세 곳

1. **`export`가 `visibility='public'`만 내보낸다** — 비공개 전환의 효과가 분석 결과에 그대로 반영된다. 조치 → 재스캔 → 위험도 하락이 **실제로** 일어난다
2. **`export`에 `author_id`·`source`·`visibility` 내부 값이 없다** — 계약에 정의된 것만 나간다. 플랫폼 내부 사정은 넘기지 않는다
3. **`toggle`이 SNS 쪽에 있다** — 조치 실행은 플랫폼이 한다. 분석기는 *"이걸 비공개하라"* 까지만 말한다

> ⚠️ **`title` 은 내보낸다.** 이전 판의 이 문단이 `title` 을 「내부 값」으로 적었는데 틀렸다.
> `title` 은 `sns-minimal-spec.md` §1 의 선택 필드이고 §3 의 텍스트 채널이며,
> `label-schema` §5-3 의 네 채널 중 하나다. **빼면 제목 단서를 골드셋에 넣어도 분석기가 못 본다.**
> 같은 이유로 `photos[].caption`(→ `photo_caption:N`)과 `profile_bio` 도 내보낸다.
> 사용자 식별자는 `author_id` 가 아니라 **`user_ref`**(`^u_[0-9a-f]{8,}$`) 다 — `필드-대조표.md` ①.

---

## 5. 시딩 스크립트 (W4)

**수작업으로 글을 붙여넣지 않는다.** 3,000글이 아니라 12글이어도 스크립트로 넣는다 — 리허설 때마다 DB를 갈아엎게 되기 때문이다.

```bash
python scripts/seed_sns.py \
  --corpus data/corpus/v1/posts/ \
  --personas data/corpus/v1/personas/ \
  --db data/interim/sns.db \
  --authors S01,S03,S07
```

### 반드시 지킬 3가지

**① 멱등성 — 두 번 돌려도 글이 두 배가 되지 않는다.**

```python
cur.execute(
    "INSERT OR IGNORE INTO posts(post_id,author_id,body,created_at,geo_tag,source)"
    " VALUES(?,?,?,?,?, 'seed')", (...))
```

`INSERT OR IGNORE`. 리허설 중 두 번 돌리는 일이 반드시 생긴다.

**② 작성시각을 흩뿌린다.**

코퍼스에 시각이 있으면 그대로 쓰고, 없으면 인물별 활동 패턴에 맞춰 생성한다.

```python
# 인물의 typical_active_hours 를 반영한다. 전부 같은 시각이면 '작성 시각 단서'를 시연 못 한다
hour = random.choice(active_hours)          # 예: 육아 인물이면 [22,23,0,1,2]
```

**③ 초기화 옵션을 둔다.**

```bash
python scripts/seed_sns.py --reset      # DROP → schema.sql → 시딩
```

리허설 전에 항상 `--reset`으로 돌린다. 시연 중 만든 글이 섞여 있으면 위험도 숫자가 어제와 달라진다.

### 시딩 검증 SQL 3줄

```sql
-- 1. 인물별 글 수 — 기대한 대로 들어갔나
SELECT author_id, COUNT(*) FROM posts GROUP BY author_id;

-- 2. 시각이 빈 글이 있나 (0이어야 한다)
SELECT COUNT(*) FROM posts WHERE created_at IS NULL OR created_at = '';

-- 3. 시간대 분포 — 한 시각에 몰려 있으면 ②가 안 된 것이다
SELECT substr(created_at,12,2) AS h, COUNT(*) FROM posts GROUP BY h ORDER BY h;
```

```bash
sqlite3 data/interim/sns.db < scripts/check_seed.sql
```

> ⚠️ **`data/interim/sns.db`는 커밋하지 않는다.** `.gitignore`를 확인한다. 시딩 스크립트와 코퍼스가 있으면 언제든 다시 만들 수 있으므로 DB 파일 자체는 산출물이 아니다.

---

## 6. 활동 메타 (W6)

W3의 v0에는 필드만 만들어 두고 비워 놓아도 된다. W6에 채운다.

| 메타 | 어디에 | 화면에서 |
|---|---|---|
| 닉네임 | `authors.nickname` | 프로필·글 목록. **아이디 자체가 단서다** (`mtfish_lee` → 성씨·취미) |
| 위치태그 | `posts.geo_tag` | 본문 하단. 조치 화면에서 "이 태그를 지우면 −n" |
| 작성시각 | `posts.created_at` | 본문 상단 + 프로필의 **시간대 분포 막대** |

**프로필에 시간대 분포 막대 하나를 그려두면 시연에서 가장 잘 먹힌다.** 글 목록만 보면 시각이 단서라는 게 눈에 안 들어오는데, 새벽에 몰린 막대를 보면 한 번에 이해된다. SQL 3번을 그대로 쓰면 된다.

---

## 7. 에디터 실시간 경고 (W9)

작성 화면에서 타이핑하는 중에 *"이 표현이 이전 글의 ○○와 결합합니다"* 를 띄운다.

**구현은 단순하게.**

```
입력 멈춤 400ms → 본문을 분석기(8000)의 /api/preview 로 POST
                → 스팬 + 결합 경고 문구를 받아 표시
```

- **타이핑마다 부르지 않는다.** 입력이 멈추고 400ms 뒤에 한 번(디바운스)
- 이전 글과의 결합 판정은 **D의 2단**이 한다. E는 화면만
- **폴백**: 시간이 없으면 *"이번 글에서 탐지된 스팬"* 만 밑줄로 표시하고 결합 경고는 뺀다. 그것만으로도 시연이 성립한다

> ⚠️ **여기서 계층 경계가 헷갈리기 쉽다.** SNS의 작성 화면이 분석기를 부르는 모양이 되는데, 이건 **사용자가 자기 브라우저에서 자기 도구를 부르는 것**이라 원칙에 맞다. 다만 **SNS 서버가 부르면 안 된다** — 브라우저에서 부른다. 서버가 부르면 원문이 SNS 서버를 경유하게 된다.

---

## 8. 자주 터지는 곳

| 증상 | 원인 / 대처 |
|---|---|
| 한글이 `?????` 로 나온다 | SQLite 연결에 인코딩 문제는 없다. **템플릿·응답의 charset**을 본다. Flask `jsonify`는 기본이 UTF-8이지만 `ensure_ascii`가 켜져 보기 나쁘면 `app.json.ensure_ascii = False` |
| `sqlite3.OperationalError: database is locked` | 시딩 스크립트와 서버가 동시에 쓰고 있다. **서버를 끄고 시딩**한다 |
| `FOREIGN KEY constraint failed` | `authors`를 먼저 넣지 않았다. 시딩은 **인물 → 글** 순서 |
| 글 순서가 이상하다 | `created_at`이 ISO8601이 아니다. `2026-3-5` 같은 값이 섞이면 문자열 정렬이 깨진다. **0을 채운 `2026-03-05T09:00:00+09:00`** 형식으로 통일 |
| 시딩을 두 번 돌려 글이 두 배 | `INSERT OR IGNORE` 를 안 썼다. `--reset` 후 다시 |
| 분석기에서 CORS 에러 | 포트가 달라서 그렇다. 분석기에 CORS 허용을 **`http://localhost:3000` 한 곳만** 열어둔다. `*`로 열지 않는다 |
| DB 파일이 커밋되려 한다 | 훅이 막는다. `.gitignore`에 `data/interim/` 확인 |

---

## 9. 완료 기준 (검증 가능하게)

### W3 — v0

- [ ] `python apps/sns/app.py` 로 서버가 뜨고 `http://localhost:3000` 이 열린다
- [ ] 화면 4개가 전부 열린다 (`/`, `/posts/<id>`, `/new`, `/u/<id>`)
- [ ] `/new` 에서 글을 하나 쓰면 `/` 목록 맨 위에 뜬다
- [ ] **작성시각을 과거로 지정한 글이 목록에서 그 위치에 정렬된다**
- [ ] `GET /api/export/<author_id>` 가 계약 형식의 JSON을 준다

### W4 — 시딩

- [ ] 스크립트 한 줄로 인물 3명 이상 · 글 30편 이상이 들어간다
- [ ] **두 번 돌려도 글 수가 그대로다**
- [ ] 검증 SQL 3줄이 전부 기대값 (빈 시각 0건, 시간대가 2개 이상으로 갈림)
- [ ] `--reset` 이 동작한다

### W6 — 활동 메타

- [ ] 닉네임·위치태그·작성시각이 본문/프로필에 보인다
- [ ] 프로필에 시간대 분포가 보인다
- [ ] `visibility`를 private로 바꾸면 **`/api/export`에서 그 글이 빠진다**
