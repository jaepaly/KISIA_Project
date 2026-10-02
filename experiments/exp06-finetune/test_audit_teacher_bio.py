"""같은 스팬이 여러 창에 나타나도 유형별로 한 번만 세는지 확인한다."""
import unittest

import audit_teacher_bio


class TeacherBioAuditTest(unittest.TestCase):
    def test_window_tokens_and_unique_spans(self):
        base = {
            "reviewed": False, "post_id": "P01_b01", "text_id": "body",
            "spans": [{"span_id": "P01_b01_s01", "type": "AGE"}],
            "labels": [-100, 0, 1],
        }
        result = audit_teacher_bio.summarize([base, {**base, "labels": [-100, 0, 2]}])
        self.assertEqual(result["teacher"]["windows"], 2)
        self.assertEqual(result["teacher"]["positive_tokens"], 2)
        self.assertEqual(result["teacher"]["unique_spans"], 1)
        self.assertEqual(result["teacher"]["type_AGE"], 1)
        self.assertEqual(result["reviewed"], {})


if __name__ == "__main__":
    unittest.main()
