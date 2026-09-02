"""exp04: R1~R6 교차모델 추론 결과를 실행하고 일치율을 집계한다.

정본: README.md W3 B, docs/plan.md §6, docs/roles/B-detector.md §6.

원본 R1~R6 게시글은 저장소에 없다. 따라서 정본 문서에 남은 조건을 아래
``INPUT_DATA``에 손으로 넣어 실행하며, 결과나 일치 여부는 미리 넣지 않는다.

실행 순서
1. 손으로 옮긴 조건 점검
   python experiments/exp04-cross-model/run.py --validate
2. 팀원이 웹 UI에서 실행해야 하면 동일 프롬프트 출력
   python experiments/exp04-cross-model/run.py --print-prompt
3. 서로 다른 두 모델 실행 (각 명령은 stdin으로 프롬프트를 받고 stdout으로 JSON 반환)
   python experiments/exp04-cross-model/run.py --command-a "..." --command-b "..."
4. 생성된 review.json의 42개 ``agree``를 사람이 검토해 true/false로 채운다.
5. 검토 결과 집계
   python experiments/exp04-cross-model/run.py --score

모델 호출 없이 이미 받은 JSON을 사용할 수도 있다.
   python experiments/exp04-cross-model/run.py --output-a a.json --output-b b.json
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ATTRIBUTES = ("age", "sex", "location", "occupation", "family", "commute", "income")
REQUIRED_RESULT_FIELDS = ("value", "confidence", "evidence")

SYSTEM_PROMPT = """너는 공개 게시글의 누적 단서로부터 글쓴이의 준식별자를 분석한다.
입력에 직접 주어진 사실과 합리적으로 추론 가능한 내용만 사용한다.
근거가 부족하면 value를 빈 문자열로, confidence를 0으로, evidence를 빈 배열로 둔다.
학력·학교·전공·정치성향·건강·지적 수준은 추론하거나 출력하지 않는다.
설명이나 마크다운 없이 지정된 JSON 객체만 출력한다.

출력 형식:
{
  "R1": {
    "age": {"value": "", "confidence": 0.0, "evidence": []},
    "sex": {"value": "", "confidence": 0.0, "evidence": []},
    "location": {"value": "", "confidence": 0.0, "evidence": []},
    "occupation": {"value": "", "confidence": 0.0, "evidence": []},
    "family": {"value": "", "confidence": 0.0, "evidence": []},
    "commute": {"value": "", "confidence": 0.0, "evidence": []},
    "income": {"value": "", "confidence": 0.0, "evidence": []}
  }
}
R1부터 R6까지 모두 같은 구조로 포함한다. confidence는 0 이상 1 이하이다.
evidence에는 입력의 known_conditions 문장을 그대로 인용한다."""

# README W3 B가 지시한 "조건 몇 개를 손으로 적어 넣어" 실행하기 위한 입력이다.
# docs/plan.md §1·§6에 실제로 남아 있는 요약만 사용한다. 문서에 없는 상세 값이나
# 선행 PoC 원문을 복원했다고 주장하지 않는다.
INPUT_DATA = {
    "experiment": "exp04-cross-model",
    "input_status": "reconstructed_summary",
    "provenance": ["docs/plan.md §1", "docs/plan.md §6", "README.md W3 B"],
    "limitations": [
        "선행 PoC의 R1~R6 원문 게시글과 원 조건은 저장소에 없다.",
        "정본 문서에 남은 요약만 사용하므로 선행 PoC 수치의 직접 재현은 아니다.",
        "문서에 없는 거주지·직업·가족·통근·소득 값은 추가하지 않았다.",
    ],
    "attributes": list(ATTRIBUTES),
    "personas": [
        {
            "persona_id": "R1",
            "known_conditions": [
                "40대 남성",
                "등산과 낚시 관련 공개 게시글을 작성했다.",
                "주소를 직접 언급하지 않았다.",
                "게시글에 신갈저수지와 기흥호수라는 장소가 등장한다.",
            ],
        },
        {
            "persona_id": "R2",
            "known_conditions": ["20대 여성", "취미와 팬 활동 관련 공개 게시글을 작성했다."],
        },
        {
            "persona_id": "R3",
            "known_conditions": ["30대 여성", "직장 생활과 육아 관련 공개 게시글을 작성했다."],
        },
        {
            "persona_id": "R4",
            "known_conditions": ["60대 여성", "손주와 일상에 관한 공개 게시글을 작성했다."],
        },
        {
            "persona_id": "R5",
            "known_conditions": ["20대 남성", "해외 체류와 근로 생활에 관한 공개 게시글을 작성했다."],
        },
        {
            "persona_id": "R6",
            "known_conditions": [
                "30대 여성",
                "지방에서 운영하는 카페와 일상에 관한 공개 게시글을 작성했다.",
            ],
        },
    ],
}


class ExperimentError(RuntimeError):
    """사용자가 바로 고칠 수 있는 실험 입력/실행 오류."""


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ExperimentError(f"파일이 없다: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExperimentError(f"JSON 형식 오류: {path}:{exc.lineno}:{exc.colno} {exc.msg}") from exc


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_input(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise ExperimentError("input.json 최상위는 객체여야 한다")
    if data.get("input_status") != "reconstructed_summary":
        raise ExperimentError("원본 부재를 숨기지 않도록 input_status는 reconstructed_summary여야 한다")
    if data.get("attributes") != list(ATTRIBUTES):
        raise ExperimentError(f"attributes는 다음 순서여야 한다: {', '.join(ATTRIBUTES)}")
    personas = data.get("personas")
    if not isinstance(personas, list) or len(personas) != 6:
        raise ExperimentError("R1~R6 페르소나 6개가 필요하다")
    expected_ids = [f"R{i}" for i in range(1, 7)]
    actual_ids = [p.get("persona_id") for p in personas if isinstance(p, dict)]
    if actual_ids != expected_ids:
        raise ExperimentError(f"persona_id 순서는 {expected_ids}여야 한다")
    for persona in personas:
        conditions = persona.get("known_conditions")
        if not isinstance(conditions, list) or not conditions or not all(
            isinstance(item, str) and item.strip() for item in conditions
        ):
            raise ExperimentError(f"{persona['persona_id']}: known_conditions가 비어 있다")
    return personas


def build_prompt(data: dict[str, Any]) -> str:
    payload = {
        "input_status": data["input_status"],
        "limitations": data.get("limitations", []),
        "personas": [
            {"persona_id": p["persona_id"], "known_conditions": p["known_conditions"]}
            for p in data["personas"]
        ],
    }
    return SYSTEM_PROMPT + "\n\n입력:\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def parse_model_json(text: str, label: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ExperimentError(f"{label} 출력이 JSON이 아니다: {exc.msg}") from exc
    validate_model_output(result, label)
    return result


def validate_model_output(result: Any, label: str) -> None:
    if not isinstance(result, dict):
        raise ExperimentError(f"{label} 출력 최상위는 객체여야 한다")
    expected_ids = {f"R{i}" for i in range(1, 7)}
    if set(result) != expected_ids:
        raise ExperimentError(f"{label} 출력은 R1~R6만 포함해야 한다")
    for persona_id in sorted(expected_ids):
        attrs = result[persona_id]
        if not isinstance(attrs, dict) or set(attrs) != set(ATTRIBUTES):
            raise ExperimentError(f"{label} {persona_id}: 7속성이 정확히 필요하다")
        for attr in ATTRIBUTES:
            finding = attrs[attr]
            if not isinstance(finding, dict) or not all(k in finding for k in REQUIRED_RESULT_FIELDS):
                raise ExperimentError(f"{label} {persona_id}.{attr}: value/confidence/evidence가 필요하다")
            if not isinstance(finding["value"], str):
                raise ExperimentError(f"{label} {persona_id}.{attr}.value는 문자열이어야 한다")
            confidence = finding["confidence"]
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise ExperimentError(f"{label} {persona_id}.{attr}.confidence는 0~1 숫자여야 한다")
            if not isinstance(finding["evidence"], list) or not all(
                isinstance(item, str) for item in finding["evidence"]
            ):
                raise ExperimentError(f"{label} {persona_id}.{attr}.evidence는 문자열 배열이어야 한다")


def run_command(command: str, prompt: str, label: str) -> dict[str, Any]:
    parts = shlex.split(command, posix=sys.platform != "win32")
    if not parts:
        raise ExperimentError(f"{label} 실행 명령이 비어 있다")
    executable = shutil.which(parts[0]) or parts[0]
    try:
        completed = subprocess.run(
            [executable, *parts[1:]],
            input=prompt,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExperimentError(f"{label} 실행 실패: {exc}") from exc
    if completed.returncode != 0:
        raise ExperimentError(
            f"{label} 명령 종료 코드 {completed.returncode}: {completed.stderr[-500:]}"
        )
    if not completed.stdout.strip():
        raise ExperimentError(f"{label} 명령이 빈 출력을 반환했다: {completed.stderr[-500:]}")
    return parse_model_json(completed.stdout, label)


def load_or_run(output_path: str, command: str, prompt: str, label: str) -> dict[str, Any]:
    if bool(output_path) == bool(command):
        raise ExperimentError(f"{label}: --output 또는 --command 중 정확히 하나를 지정해야 한다")
    if output_path:
        result = read_json(Path(output_path))
        validate_model_output(result, label)
        return result
    return run_command(command, prompt, label)


def make_review(model_a: dict[str, Any], model_b: dict[str, Any], name_a: str, name_b: str) -> dict[str, Any]:
    rows = []
    for persona_id in (f"R{i}" for i in range(1, 7)):
        for attr in ATTRIBUTES:
            rows.append(
                {
                    "persona_id": persona_id,
                    "attribute": attr,
                    "model_a_value": model_a[persona_id][attr]["value"],
                    "model_b_value": model_b[persona_id][attr]["value"],
                    "agree": None,
                    "note": "",
                }
            )
    return {
        "experiment": "exp04-cross-model",
        "models": {"model_a": name_a, "model_b": name_b},
        "review_rule": "두 값이 의미상 같은 범위를 가리키면 true, 다르거나 한쪽만 기권하면 false",
        "rows": rows,
    }


def score_review(review: Any, input_data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(review, dict) or not isinstance(review.get("rows"), list):
        raise ExperimentError("review.json에 rows 배열이 필요하다")
    rows = review["rows"]
    if len(rows) != 42:
        raise ExperimentError(f"review.json은 6명 × 7속성 = 42행이어야 한다 (현재 {len(rows)}행)")
    seen: set[tuple[str, str]] = set()
    by_attribute = {attr: {"agreed": 0, "total": 0} for attr in ATTRIBUTES}
    by_persona = {f"R{i}": {"agreed": 0, "total": 0} for i in range(1, 7)}
    pending = 0
    agreed = 0
    for row in rows:
        key = (row.get("persona_id"), row.get("attribute"))
        if key in seen or key[0] not in by_persona or key[1] not in by_attribute:
            raise ExperimentError(f"review.json의 잘못되거나 중복된 행: {key}")
        seen.add(key)
        verdict = row.get("agree")
        if verdict is None:
            pending += 1
            continue
        if not isinstance(verdict, bool):
            raise ExperimentError(f"{key}: agree는 true/false/null 중 하나여야 한다")
        by_attribute[key[1]]["total"] += 1
        by_persona[key[0]]["total"] += 1
        if verdict:
            agreed += 1
            by_attribute[key[1]]["agreed"] += 1
            by_persona[key[0]]["agreed"] += 1
    reviewed = 42 - pending
    rate = agreed / reviewed if reviewed else None
    complete = pending == 0
    return {
        "experiment": "exp04-cross-model",
        "measured_at": date.today().isoformat(),
        "input_status": input_data["input_status"],
        "directly_comparable_to_prior_poc": False,
        "models": review.get("models", {}),
        "gate_threshold": 0.85,
        "reviewed_slots": reviewed,
        "pending_slots": pending,
        "agreed_slots": agreed,
        "agreement_rate": round(rate, 4) if rate is not None else None,
        "gate_status": "PENDING" if not complete else ("PASS" if rate is not None and rate >= 0.85 else "FAIL"),
        "by_attribute": by_attribute,
        "by_persona": by_persona,
        "limitations": input_data.get("limitations", []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="exp04 R1~R6 교차모델 실행·검토·집계")
    parser.add_argument("--validate", action="store_true", help="입력만 검사하고 종료")
    parser.add_argument("--print-prompt", action="store_true", help="두 모델에 동일하게 넣을 프롬프트 출력")
    parser.add_argument("--command-a", default="", help="모델 A 실행 명령")
    parser.add_argument("--command-b", default="", help="모델 B 실행 명령")
    parser.add_argument("--output-a", default="", help="이미 받은 모델 A JSON")
    parser.add_argument("--output-b", default="", help="이미 받은 모델 B JSON")
    parser.add_argument("--name-a", default="Claude")
    parser.add_argument("--name-b", default="GPT-5.5")
    parser.add_argument("--score", action="store_true", help="review.json을 metrics.json으로 집계")
    parser.add_argument("--review", default=str(HERE / "review.json"))
    parser.add_argument("--metrics", default=str(HERE / "metrics.json"))
    args = parser.parse_args()

    try:
        input_data = INPUT_DATA
        validate_input(input_data)
        if args.validate:
            print("OK: R1~R6 요약 입력 6건과 7속성 정의를 확인했다.")
            return 0
        if args.print_prompt:
            print(build_prompt(input_data))
            return 0
        if args.score:
            metrics = score_review(read_json(Path(args.review)), input_data)
            write_json(Path(args.metrics), metrics)
            print(
                f"{metrics['gate_status']}: {metrics['agreed_slots']}/{metrics['reviewed_slots']} "
                f"(pending={metrics['pending_slots']}) -> {args.metrics}"
            )
            return 0

        prompt = build_prompt(input_data)
        model_a = load_or_run(args.output_a, args.command_a, prompt, "model-a")
        model_b = load_or_run(args.output_b, args.command_b, prompt, "model-b")
        results_dir = HERE / "results"
        write_json(results_dir / "model_a.json", model_a)
        write_json(results_dir / "model_b.json", model_b)
        write_json(Path(args.review), make_review(model_a, model_b, args.name_a, args.name_b))
        print(f"두 모델 출력 저장: {results_dir}")
        print(f"사람 검토 필요: {args.review}의 agree 42개를 true/false로 채운 뒤 --score")
        return 0
    except ExperimentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
