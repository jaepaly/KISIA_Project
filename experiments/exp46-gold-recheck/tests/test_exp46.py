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


def fake_key():
    items = []
    for n in range(1, 5):
        cands = {"X": {"golds": ["official239"], "label": f"a{n}"},
                 "Y": {"golds": ["conservative239", "previous_ai239"], "label": f"b{n}"}}
        items.append({"item_id": f"G{n:02d}", "stratum": "O_alone|type" if n <= 2 else "P_alone|type",
                      "candidates": cands})
    return {"items": items}


def write_review(path, key, choices):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=B.SHEET_COLUMNS)
        w.writeheader()
        for it, ch in zip(key["items"], choices):
            c = it["candidates"]
            w.writerow({"item_id": it["item_id"], "후보_X": c["X"]["label"], "후보_Y": c["Y"]["label"],
                        "후보_Z": "", "선택": ch, "메모": ""})


class TallyTests(unittest.TestCase):
    def test_fake_reviews(self):
        key = fake_key()
        with tempfile.TemporaryDirectory() as d:
            write_review(Path(d) / "A.csv", key, ["X", "y", "모두틀림", "Y"])
            write_review(Path(d) / "B.csv", key, ["X", "Y", "애매", "Y"])
            write_review(Path(d) / "C.csv", key, ["X", "X", "X", "X"])
            reviews = T.load_reviews(d, key)
        res = T.tally(key, reviews, {"O_alone|type": 30, "P_alone|type": 10})
        self.assertEqual(res["pooled_roles"], ["A", "B"])
        a = res["per_reviewer"]["A"]
        self.assertEqual((a["official239"]["k"], a["previous_ai239"]["k"], a["모두 틀림"]["k"]), (1, 2, 1))
        m = res["majority_pooled"]
        # G03 은 A·B 가 갈려 동률 → 애매
        self.assertEqual((m["official239"]["k"], m["conservative239"]["k"], m["애매"]["k"]), (1, 2, 1))
        # 층 가중: O 층(가중 .75) 지지율 .5, P 층 0 → .375
        self.assertAlmostEqual(m["stratum_weighted"]["official239"]["rate"], .375)
        self.assertEqual(res["fleiss_pooled"]["items"], 4)
        self.assertAlmostEqual(res["cohen_pairs"]["A~B"]["agree"], .75)
        lo, hi = m["official239"]["ci95"]
        self.assertTrue(0 <= lo < .25 < hi <= 1)

    def test_rejects_edited_candidates_and_bad_choice(self):
        key = fake_key()
        with tempfile.TemporaryDirectory() as d:
            write_review(Path(d) / "A.csv", key, ["W", "", "", ""])
            with self.assertRaises(ValueError):
                T.load_reviews(d, key)
            write_review(Path(d) / "A.csv", key, ["Z", "", "", ""])
            with self.assertRaises(ValueError):
                T.load_reviews(d, key)

    def test_cohen_perfect(self):
        a = {"G1": "X", "G2": "Y", "G3": "애매"}
        self.assertEqual(T.cohen(a, dict(a))["kappa"], 1.0)


if __name__ == "__main__":
    unittest.main()
