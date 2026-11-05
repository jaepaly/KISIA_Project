"""python -X utf8 -m unittest discover -s experiments/exp46-gold-recheck/tests -v"""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import build_sheet as B  # noqa: E402
import tally as T  # noqa: E402


def sp(start, end, typ="AGE", level="explicit", text="x", tid="body"):
    return {"text_id": tid, "start": start, "end": end, "type": typ, "level": level, "text": text}


class UnitTests(unittest.TestCase):
    def test_partition_patterns(self):
        # 조사 차이(IoU .8)는 같은 것으로, 스팬 없음은 다른 것으로
        per = {"official239": [sp(0, 4)], "previous_ai239": [sp(0, 5)], "conservative239": [sp(0, 5)]}
        self.assertEqual(B.partition(per)[1], "agree")
        per = {"official239": [], "previous_ai239": [sp(0, 5)], "conservative239": [sp(0, 5)]}
        classes, pat = B.partition(per)
        self.assertEqual(pat, "O_alone")
        self.assertEqual(B.kind(per, classes), "lone_missing")
        per = {"official239": [sp(0, 5, "JOB")], "previous_ai239": [sp(0, 5)], "conservative239": [sp(0, 5, "JOB")]}
        classes, pat = B.partition(per)
        self.assertEqual((pat, B.kind(per, classes)), ("P_alone", "type"))
        per = {"official239": [sp(0, 10)], "previous_ai239": [sp(0, 3)], "conservative239": [sp(0, 10)]}
        classes, pat = B.partition(per)
        self.assertEqual((pat, B.kind(per, classes)), ("P_alone", "boundary"))

    def test_components_link_any_overlap(self):
        per = {"official239": [sp(0, 10, "COMMUTE")],
               "previous_ai239": [sp(0, 3, "COMMUTE"), sp(4, 10, "LOC_ADMIN"), sp(20, 22)],
               "conservative239": []}
        comps = B.components(per)
        self.assertEqual(len(comps), 2)
        self.assertEqual(len(comps[0]["previous_ai239"]), 2)

    def test_committed_sheet_is_blind(self):
        text = (HERE / "sheet.csv").read_text(encoding="utf-8-sig")
        for word in B.GOLDS + ("official", "previous", "conservative", "U0", "O_alone", "P_alone"):
            self.assertNotIn(word, text)


def fake_key(n_items=4):
    """O_alone 2개 · P_alone 2개. X = official 쪽, Y = previous·conservative 쪽."""
    items = []
    for n in range(1, n_items + 1):
        o, pc = [sp(0, 4)], [sp(10, 14, "JOB")]
        items.append({"item_id": f"G{n:02d}", "stratum": "O_alone|type" if n <= n_items // 2 else "P_alone|type",
                      "spans": {"official239": o, "previous_ai239": pc, "conservative239": pc},
                      "candidates": {"X": {"golds_exact": ["official239"], "spans": o, "label": f"a{n}"},
                                     "Y": {"golds_exact": ["conservative239", "previous_ai239"], "spans": pc,
                                           "label": f"b{n}"}}})
    return {"items": items}


def write_review(path, key, choices, encoding="utf-8-sig", rows=None):
    with open(path, "w", encoding=encoding, newline="") as f:
        w = csv.DictWriter(f, fieldnames=B.SHEET_COLUMNS)
        w.writeheader()
        for it, ch in zip(key["items"], choices):
            c = it["candidates"]
            w.writerow({"item_id": it["item_id"], "후보_X": c["X"]["label"], "후보_Y": c["Y"]["label"],
                        "후보_Z": "", "선택": ch, "메모": ""})
        for extra in rows or []:
            w.writerow(extra)


class TallyTests(unittest.TestCase):
    def test_fake_reviews(self):
        key = fake_key()
        with tempfile.TemporaryDirectory() as d:
            write_review(Path(d) / "A.csv", key, ["X", "y", "모두틀림", "Y"])
            write_review(Path(d) / "B.csv", key, ["X", "Y", "애매", "Y"])
            write_review(Path(d) / "C.csv", key, ["X", "X", "X", "X"])
            reviews = T.load_reviews(d, key)
        pop = {"O_alone|type": 30, "P_alone|type": 10}
        res = T.tally(key, reviews, pop)
        self.assertEqual(res["pooled_roles"], ["A", "B"])
        a = res["per_reviewer"]["A"]
        self.assertEqual((a["official239"]["k"], a["previous_ai239"]["k"], a["모두 틀림"]["k"]), (1, 2, 1))
        m = res["majority_pooled"]
        # G03 은 A·B 가 갈려 과반 없음 — 애매로 세지 않는다
        self.assertEqual((m["official239"]["k"], m["conservative239"]["k"], m["애매"]["k"], m[T.NO_MAJORITY]["k"]),
                         (1, 2, 0, 1))
        self.assertEqual(res["abstain_rate_pooled"], .25)
        self.assertEqual(res["fleiss_pooled"]["items"], 4)
        self.assertAlmostEqual(res["cohen_pairs"]["A~B"]["agree"], .75)
        lo, hi = m["official239"]["ci95"]
        self.assertTrue(0 <= lo < .25 < hi <= 1)

    def test_support_follows_chosen_spans(self):
        # 고른 후보와 계약 채점으로 짝지어지는 정답만 지지받는다
        key = fake_key(2)
        it = key["items"][0]
        it["spans"]["conservative239"] = [sp(0, 5)]       # official 과 IoU .8
        self.assertEqual(T.supported(it, "X"), {"official239", "conservative239"})
        self.assertEqual(T.supported(it, "Y"), {"previous_ai239"})
        self.assertEqual(T.supported(it, "애매"), set())

    def test_weighted_ci_does_not_collapse_and_requires_coverage(self):
        key = fake_key(16)
        items = {it["item_id"]: it for it in key["items"]}
        pop = {"O_alone|type": 110, "P_alone|type": 9}
        allx = {i: "X" for i in items}
        w = T.weighted_support(items, allx, pop)
        self.assertEqual(w["official239"]["rate"], 1.0)
        self.assertLess(w["official239"]["ci95"][0], 1.0)          # 만장일치여도 구간이 [1,1] 이 아니다
        self.assertLess(w["diff_previous_minus_official"]["ci95"][1], 0)
        partial = {i: ("X" if items[i]["stratum"].startswith("O") else None) for i in items}
        self.assertEqual(T.weighted_support(items, partial, pop)["status"], "insufficient")

    def test_input_validation(self):
        key = fake_key()
        bad = [
            ("A.csv", ["W", "", "", ""], {}),                       # 없는 선택 값
            ("A.csv", ["Z", "", "", ""], {}),                       # 빈 후보 선택
            ("A.csv", ["X", "X", "X"], {}),                         # 행 누락
            ("a.csv", ["X", "X", "X", "X"], {}),                    # 역할 이름(C 제외 우회 방지)
            ("A_backup.csv", ["X", "X", "X", "X"], {}),
            ("A.csv", ["X", "X", "X", "X"], {"rows": [{"item_id": "G01", "후보_X": "a1", "후보_Y": "b1", "선택": "Y"}]}),
            ("A.csv", ["X", "X", "X", "X"], {"encoding": "cp949"}),  # 일반 CSV 저장
        ]
        for name, choices, kw in bad:
            with self.subTest(name=name, kw=kw), tempfile.TemporaryDirectory() as d:
                if kw.get("encoding") == "cp949":
                    key2 = fake_key()
                    key2["items"][0]["candidates"]["X"]["label"] = "가나"
                    write_review(Path(d) / name, key2, choices, encoding="cp949")
                    with self.assertRaises(ValueError):
                        T.load_reviews(d, key2)
                    continue
                write_review(Path(d) / name, key, choices, rows=kw.get("rows"))
                with self.assertRaises(ValueError):
                    T.load_reviews(d, key)

    def test_cohen_perfect(self):
        a = {"G1": "X", "G2": "Y", "G3": "애매"}
        self.assertEqual(T.cohen(a, dict(a))["kappa"], 1.0)


if __name__ == "__main__":
    unittest.main()
