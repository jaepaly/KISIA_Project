"""내보내기 계약 테스트 — E 완료 기준 「내보내기가 sns-minimal-spec.md 와 맞는다 (테스트 1개)」.

    python -m pytest apps/sns/test_export.py -v

**이 테스트가 계약이다.** 통과하면 W5 통합에서 분석기가 이 응답을 읽을 수 있다.
화면 4개를 어떻게 만들든 이 테스트만 통과하면 계층 경계는 지켜진다.

⚠️ 여기서 검사하는 것은 형식이지 내용이 아니다. 내용은 W4 시딩이 채운다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import app                                    # noqa: E402
from db import connect, init                           # noqa: E402

# 계약 §2 — 익명 핸들 형식. 실제 닉네임을 넣으면 여기서 튕긴다
USER_REF_RE = re.compile(r"^u_[0-9a-f]{8,}$")
# label-schema §5-3 — 텍스트 채널은 이 넷뿐이다
TEXT_ID_RE = re.compile(r"^(title|body|profile_bio|photo_caption:\d+)$")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SNS_DB_PATH", str(tmp_path / "t.db"))
    with connect() as c:
        init(c)
        c.execute(
            "INSERT INTO authors(author_id,user_ref,nickname,bio,joined_at)"
            " VALUES('S01','u_3f2a91c4','골목 사진','동네 사진 찍습니다',"
            "'2026-01-02T09:00:00+09:00')")
        c.executemany(
            "INSERT INTO posts(post_id,author_id,title,body,created_at,geo_tag,visibility)"
            " VALUES(?,?,?,?,?,?,?)",
            [("S01_b01", "S01", "비 그친 아침", "골목이 젖어 있었다",
              "2026-03-10T21:38:20+09:00", "성동구 성수동", "public"),
             ("S01_b02", "S01", None, "제목 없는 글도 있다",
              "2026-03-11T02:10:00+09:00", None, "public"),
             # ⚠️ 비공개 글 — 내보내기에서 빠져야 한다 (조치 ③)
             ("S01_b03", "S01", "이건 비공개", "나가면 안 된다",
              "2026-03-12T10:00:00+09:00", None, "private")])
        c.executemany(
            "INSERT INTO photos(post_id,idx,caption) VALUES(?,?,?)",
            [("S01_b01", 0, "골목 초입"), ("S01_b01", 1, "물웅덩이")])
        c.commit()
    app.config["TESTING"] = True
    with app.test_client() as cl:
        yield cl


def get(client):
    r = client.get("/api/export/u_3f2a91c4")
    assert r.status_code == 200, r.data[:200]
    return r.get_json()


# ── 계약 §2 사용자 ──────────────────────────────────────────────────
def test_user_ref_형식(client):
    d = get(client)
    assert USER_REF_RE.match(d["user_ref"]), d["user_ref"]
    for p in d["posts"]:
        assert USER_REF_RE.match(p["user_ref"])


def test_내부_식별자를_안_내보낸다(client):
    """author_id·source·visibility 는 계약에 없다. 플랫폼 내부 사정이다."""
    d = get(client)
    금지 = {"author_id", "user_id", "source", "visibility"}
    assert not (금지 & set(d)), 금지 & set(d)
    for p in d["posts"]:
        assert not (금지 & set(p)), 금지 & set(p)


# ── 계약 §1 글 · §3 텍스트 채널 4개 ─────────────────────────────────
def test_글_필수_필드(client):
    d = get(client)
    for p in d["posts"]:
        for k in ("post_id", "user_ref", "body", "activity_meta"):
            assert k in p, f"{k} 없음: {sorted(p)}"


def test_채널_넷이_모두_있다(client):
    """title · body · photo_caption:N · profile_bio.

    하나라도 빠지면 그 채널의 단서는 골드셋에 있어도 분석기가 볼 수 없다.
    """
    d = get(client)
    assert "profile_bio" in d, "profile_bio 는 사용자 단위 채널이다"
    p = next(x for x in d["posts"] if x["post_id"] == "S01_b01")
    assert p.get("title") == "비 그친 아침"
    assert p.get("body")
    assert [c["caption"] for c in p["photos"]] == ["골목 초입", "물웅덩이"], \
        "사진 순서를 보존해야 한다 — photo_caption:N 의 N 이 이 순서다"


def test_캡션_색인이_0부터_이고_형식이_맞는다(client):
    d = get(client)
    p = next(x for x in d["posts"] if x["post_id"] == "S01_b01")
    for i, _ in enumerate(p["photos"]):
        assert TEXT_ID_RE.match(f"photo_caption:{i}")
    assert TEXT_ID_RE.match("photo_caption:0")


def test_제목이_없어도_된다(client):
    """계약상 title 은 선택이다. 없으면 null 이지 키가 사라지면 안 된다."""
    d = get(client)
    p = next(x for x in d["posts"] if x["post_id"] == "S01_b02")
    assert "title" in p and p["title"] is None


# ── 계약 §4 활동 메타 ───────────────────────────────────────────────
def test_활동_메타_셋(client):
    """nickname · geo_tag · post_time. 조치 ②가 이 셋을 개별 지목한다."""
    d = get(client)
    for p in d["posts"]:
        m = p["activity_meta"]
        assert set(m) == {"nickname", "geo_tag", "post_time"}, sorted(m)
        assert re.match(r"^\d{2}:\d{2}$", m["post_time"]), m["post_time"]


def test_post_time_이_created_at_에서_파생된다(client):
    d = get(client)
    p = next(x for x in d["posts"] if x["post_id"] == "S01_b02")
    assert p["activity_meta"]["post_time"] == "02:10"


def test_post_date_는_날짜만_activity_meta_밖에(client):
    """시점 역산의 기준점(#332). 시각까지 내보내면 조치 ②로 post_time 을 감춰도 새므로 날짜만."""
    d = get(client)
    for p in d["posts"]:
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", p["post_date"]), p["post_date"]
        assert "post_date" not in p["activity_meta"]
    p = next(x for x in d["posts"] if x["post_id"] == "S01_b02")
    assert p["post_date"] == "2026-03-11"


# ── 조치 ③ 비공개 ──────────────────────────────────────────────────
def test_비공개_글은_안_나간다(client):
    """조치 → 재스캔 → 위험도 하락이 실제로 일어나려면 여기서 빠져야 한다."""
    d = get(client)
    assert "S01_b03" not in {p["post_id"] for p in d["posts"]}
    assert len(d["posts"]) == 2


def test_모르는_사용자는_404(client):
    assert client.get("/api/export/u_deadbeef").status_code == 404


# ── W6 — 작성 화면 공개범위 선택 ────────────────────────────────────
def test_작성_화면에서_비공개로_올린_글은_export에_없다(client):
    """최초 공개범위 선택 — app.py:113 이 'public' 고정이던 것의 회귀 테스트."""
    before = len(get(client)["posts"])
    client.post("/posts", data={
        "author_id": "S01", "body": "비공개로 씁니다",
        "created_at": "2026-03-13T09:00", "visibility": "private",
    })
    d = get(client)
    assert len(d["posts"]) == before
    assert "비공개로 씁니다" not in [p["body"] for p in d["posts"]]


def test_작성_화면_기본값은_공개다(client):
    before = len(get(client)["posts"])
    client.post("/posts", data={
        "author_id": "S01", "body": "공개로 씁니다",
        "created_at": "2026-03-13T09:05",
    })
    d = get(client)
    assert len(d["posts"]) == before + 1
    assert "공개로 씁니다" in [p["body"] for p in d["posts"]]


def test_작성시각_형식이_틀리면_400_이고_글이_안_생긴다(client):
    """post_date · post_time 이 created_at 을 잘라 쓰므로 형식이 틀린 값은 저장 전에 막는다 (#334 Codex 검토)."""
    before = len(get(client)["posts"])
    for bad in ("bad", "2026-13-01T09:00", "2026-03-13", "2026-03-13T09:00+09:00", "２０２６-03-13T09:05"):
        r = client.post("/posts", data={"author_id": "S01", "body": "형식 검사", "created_at": bad})
        assert r.status_code == 400, bad
    assert len(get(client)["posts"]) == before
    ok = client.post("/posts", data={"author_id": "S01", "body": "초까지", "created_at": "2026-03-13T09:05:30"})
    assert ok.status_code in (200, 302)
    p = next(x for x in get(client)["posts"] if x["body"] == "초까지")
    assert p["post_date"] == "2026-03-13" and p["activity_meta"]["post_time"] == "09:05"


# ── W6 — 활동 메타 편집 라우트 ──────────────────────────────────────
def test_닉네임을_빈값으로_보내면_기존값이_유지된다(client):
    """실수로 닉네임을 지워버리는 걸 막는 안전장치."""
    before = get(client)["nickname"]
    client.post("/u/u_3f2a91c4/edit", data={"nickname": "", "bio": ""})
    assert get(client)["nickname"] == before == "골목 사진"


def test_geo_tag를_빈값으로_보내면_NULL이_된다(client):
    """위치태그를 지우는 정상 동작 — 빈 문자열이 아니라 None으로 나가야 한다."""
    p0 = next(x for x in get(client)["posts"] if x["post_id"] == "S01_b01")
    assert p0["activity_meta"]["geo_tag"] == "성동구 성수동"  # 사전 확인

    client.post("/posts/S01_b01/edit", data={"geo_tag": ""})

    p1 = next(x for x in get(client)["posts"] if x["post_id"] == "S01_b01")
    assert p1["activity_meta"]["geo_tag"] is None


# ── 계약 §6 두 번째 창구 · 파도풀 주소 (PADO_BASE) ─────────────────────
def test_계정찾기는_user_ref_nickname_n_posts_만(client):
    """분석기에 넘기는 값이라 export 와 같은 규칙 — 플랫폼 내부 값(author_id)은 나가지 않는다 (#337 리뷰 (나))."""
    r = client.get("/api/authors?q=골목")
    assert r.status_code == 200
    rows = r.get_json()
    assert rows and all(set(a) == {"user_ref", "nickname", "n_posts"} for a in rows), rows
    a = next(x for x in rows if x["user_ref"] == "u_3f2a91c4")
    assert a["n_posts"] == 2, "공개 글만 센다 — 비공개 S01_b03 은 빠진다"


def test_파도풀_진입점이_PADO_BASE_를_따른다(client, monkeypatch):
    """기본은 인스턴스 경로 /check, 로컬은 분석 앱 주소로 (#324 리뷰 (가))."""
    import app as sns_app
    html = client.get("/u/u_3f2a91c4").get_data(as_text=True)
    assert 'href="/check/static/scan.html?u=u_3f2a91c4"' in html
    assert 'window.PADO_BASE = "/check"' in html
    monkeypatch.setattr(sns_app, "PADO_BASE", "http://localhost:8000")
    html = client.get("/u/u_3f2a91c4").get_data(as_text=True)
    assert 'href="http://localhost:8000/static/scan.html?u=u_3f2a91c4"' in html
    assert 'window.PADO_BASE = "http://localhost:8000"' in html


def test_계정찾기_빈_검색어는_둘러보기_글많은순_limit(client):
    """처음 온 사람은 계정 이름을 모른다 — 빈 검색어는 공개 글 많은 순 목록 · limit 으로 더 보기 (10/14)."""
    with connect() as c:
        c.execute("INSERT INTO authors(author_id,user_ref,nickname,bio,joined_at)"
                  " VALUES('S02','u_4b5c6d7e','가나다','','2026-01-03T09:00:00+09:00')")
        c.execute("INSERT INTO posts(post_id,author_id,title,body,created_at,visibility)"
                  " VALUES('S02_b01','S02',NULL,'한 편','2026-03-10T21:38:20+09:00','public')")
        c.commit()
    rows = client.get("/api/authors").get_json()
    assert [a["user_ref"] for a in rows][:2] == ["u_3f2a91c4", "u_4b5c6d7e"], "글 2편인 계정이 1편보다 먼저(가나다 순이면 뒤집힌다)"
    assert len(client.get("/api/authors?limit=1").get_json()) == 1
    assert client.get("/api/authors?limit=abc").status_code == 200   # 잘못된 값은 기본 12
