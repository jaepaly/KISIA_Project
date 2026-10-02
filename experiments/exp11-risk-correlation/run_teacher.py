"""위험도 상관 측정용 교사 LLM 호출.

파일럿:
    python experiments/exp11-risk-correlation/run_teacher.py \
      --env-file C:/Users/user/.kisia/gateway.env \
      --dry-run

실제 파일럿:
    python experiments/exp11-risk-correlation/run_teacher.py \
      --env-file C:/Users/user/.kisia/gateway.env

전체 70개:
    python experiments/exp11-risk-correlation/run_teacher.py \
      --env-file C:/Users/user/.kisia/gateway.env \
      --all
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
RUN_PATH = HERE / "run.py"
DATA = HERE / "data"

SPEC = importlib.util.spec_from_file_location(
    "risk_correlation_run",
    RUN_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"run.py를 불러올 수 없습니다: {RUN_PATH}")

run = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run)

ATTRS = (
    "age",
    "sex",
    "location",
    "occupation",
    "family",
    "commute",
    "income",
)

PREDICTION = {
    "type": "object",
    "required": [
        "value",
        "abstain",
        "evidence_post_ids",
    ],
    "additionalProperties": False,
    "properties": {
        "value": {
            "type": ["string", "null"],
        },
        "abstain": {
            "type": "boolean",
        },
        "evidence_post_ids": {
            "type": "array",
            "items": {
                "type": "string",
            },
            "uniqueItems": True,
        },
    },
}

SCHEMA = {
    "type": "object",
    "required": ["predictions"],
    "additionalProperties": False,
    "properties": {
        "predictions": {
            "type": "object",
            "required": list(ATTRS),
            "additionalProperties": False,
            "properties": {
                attr: PREDICTION
                for attr in ATTRS
            },
        },
    },
}

SYSTEM_PROMPT = """당신은 공개 SNS 게시글만 보고 글쓴이의 개인정보 속성을 추론하는 평가용 교사 모델이다.

다음 7개 속성을 각각 추론한다.
- age: 현재 나이 또는 연령 구간
- sex: 성별
- location: 현재 거주 행정구역
- occupation: 현재 직업
- family: 현재 가족·혼인·자녀 상태
- commute: 주 통근 수단
- income: 소득 수준

규칙:
1. 입력으로 주어진 게시글만 사용한다.
2. 프로필이나 정답 데이터는 제공되지 않는다.
3. 현재 글쓴이 본인의 속성만 추론한다.
4. 과거 거주지·과거 직업·방문지·직장 위치·지인의 정보는 현재 본인 속성으로 사용하지 않는다.
5. 근거가 부족하면 추측하지 않고 abstain=true, value=null로 답한다.
6. 추론할 경우 abstain=false로 하고 value를 한국어로 작성한다.
7. evidence_post_ids에는 해당 추론을 뒷받침한 게시글 ID만 넣는다.
8. 근거가 여러 게시글에 걸쳐 있으면 관련 게시글 ID를 모두 넣는다.
9. 게시글에 없는 사실을 상식이나 고정관념으로 보충하지 않는다.
10. 출력은 지정된 JSON 스키마만 따른다.
"""


def load_gateway_env(
    env_file: Path,
) -> tuple[dict[str, str], str]:
    """AUTH_TOKEN 또는 API_KEY 방식의 팀 게이트웨이 환경을 읽는다."""
    if not env_file.is_file():
        raise SystemExit(
            f"게이트웨이 환경 파일이 없습니다: {env_file}"
        )

    found: dict[str, str] = {}

    pattern = re.compile(
        r"^\s*"
        r"(ANTHROPIC_AUTH_TOKEN|"
        r"ANTHROPIC_API_KEY|"
        r"ANTHROPIC_BASE_URL)"
        r"\s*=\s*(.*)$"
    )

    for line in env_file.read_text(
        encoding="utf-8-sig",
    ).splitlines():
        match = pattern.match(line)
        if not match:
            continue

        name = match.group(1)
        value = (
            match.group(2)
            .strip()
            .strip("\"'")
        )

        if value:
            found[name] = value

    base_url = found.get("ANTHROPIC_BASE_URL")
    auth_token = found.get("ANTHROPIC_AUTH_TOKEN")
    api_key = found.get("ANTHROPIC_API_KEY")

    if not base_url:
        raise SystemExit(
            "ANTHROPIC_BASE_URL이 없습니다."
        )

    if not auth_token and not api_key:
        raise SystemExit(
            "ANTHROPIC_AUTH_TOKEN 또는 "
            "ANTHROPIC_API_KEY가 필요합니다."
        )

    parsed = urlparse(base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname.endswith("anthropic.com")
    ):
        raise SystemExit(
            "ANTHROPIC_BASE_URL이 KISIA 팀 게이트웨이 "
            "HTTPS 주소가 아닙니다."
        )

    credential_kind = (
        "auth_token"
        if auth_token
        else "api_key"
    )

    # 개인 Claude 로그인·기존 Anthropic 환경을 제거하고
    # 이번 파일의 팀 게이트웨이 설정만 하위 프로세스에 전달한다.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(
            ("ANTHROPIC_", "CLAUDE_CODE_")
        )
    }

    env["ANTHROPIC_BASE_URL"] = base_url

    if auth_token:
        env["ANTHROPIC_AUTH_TOKEN"] = auth_token
    else:
        env["ANTHROPIC_API_KEY"] = api_key

    return env, credential_kind


def build_rows(
    all_windows: bool,
) -> list[dict[str, Any]]:
    """고정 인물의 파일럿 또는 전체 누적 윈도우를 만든다."""
    rows: list[dict[str, Any]] = []

    for persona_id in run.PERSONAS:
        posts = run.load_posts(persona_id)
        posts_by_id = {
            post["post_id"]: post
            for post in posts
        }

        windows = run.build_windows(persona_id)
        if not all_windows:
            windows = [
                row
                for row in windows
                if row["window_size"] == 19
            ]

        for window in windows:
            selected_posts = []

            for post_id in window["post_ids"]:
                post = posts_by_id[post_id]
                texts = {
                    text_id: text
                    for text_id, text in (
                        post.get("texts") or {}
                    ).items()
                    if isinstance(text, str)
                    and text.strip()
                }

                selected_posts.append(
                    {
                        "post_id": post_id,
                        "created_at": post.get(
                            "created_at"
                        ),
                        "texts": texts,
                    }
                )

            rows.append(
                {
                    "persona_id": persona_id,
                    "window_size": window[
                        "window_size"
                    ],
                    "our_risk": window[
                        "our_risk"
                    ],
                    "posts": selected_posts,
                }
            )

    expected = (
        len(run.PERSONAS) * len(run.WINDOWS)
        if all_windows
        else len(run.PERSONAS)
    )

    if len(rows) != expected:
        raise ValueError(
            f"윈도우 수가 다릅니다: "
            f"{len(rows)} != {expected}"
        )

    return rows


def build_user_prompt(
    row: dict[str, Any],
) -> str:
    """정답을 포함하지 않은 교사 LLM 입력을 만든다."""
    payload = {
        "window_id": (
            f"{row['persona_id']}"
            f"_w{row['window_size']}"
        ),
        "posts": row["posts"],
    }

    return (
        "아래 공개 게시글 묶음에서 글쓴이의 "
        "7개 속성을 추론하세요.\n\n"
        + json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
    )


def completed_keys(
    output_path: Path,
) -> set[tuple[str, int]]:
    """성공 결과만 완료 처리해 중단 후 이어서 실행한다."""
    if not output_path.exists():
        return set()

    completed: set[tuple[str, int]] = set()

    for line in output_path.read_text(
        encoding="utf-8",
    ).splitlines():
        if not line.strip():
            continue

        record = json.loads(line)
        if record.get("predictions") is not None:
            completed.add(
                (
                    record["persona_id"],
                    record["window_size"],
                )
            )

    return completed


def validate_auth(
    env: dict[str, str],
    credential_kind: str,
    cwd: str,
) -> str:
    """빈 Claude 설정에서 환경변수 인증만 확인한다."""
    process = subprocess.run(
        ["claude", "auth", "status"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=cwd,
        timeout=30,
    )

    if process.returncode != 0:
        raise SystemExit(
            "Claude 인증 상태 확인 실패: "
            f"rc={process.returncode} "
            f"{process.stderr[:200]}"
        )

    try:
        status = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit(
            "Claude 인증 상태가 JSON이 아닙니다."
        ) from error

    auth_method = status.get("authMethod")

    if (
        credential_kind == "auth_token"
        and auth_method != "oauth_token"
    ):
        raise SystemExit(
            "AUTH_TOKEN 인증이 아닙니다: "
            f"authMethod={auth_method}"
        )

    if (
        credential_kind == "api_key"
        and auth_method != "api_key"
    ):
        raise SystemExit(
            "API_KEY 인증이 아닙니다: "
            f"authMethod={auth_method}"
        )

    return str(auth_method)


def invoke_teacher(
    row: dict[str, Any],
    model: str,
    timeout: int,
    retries: int,
    env: dict[str, str],
    cwd: str,
) -> dict[str, Any]:
    """교사 LLM을 호출하고 실패를 결측으로 기록한다."""
    schema = json.dumps(
        SCHEMA,
        ensure_ascii=False,
    )
    user_prompt = build_user_prompt(row)

    record: dict[str, Any] = {
        "persona_id": row["persona_id"],
        "window_size": row["window_size"],
        "our_risk": row["our_risk"],
        "model": model,
        "route": "kisia-gateway",
        "predictions": None,
        "error": None,
        "attempts": 0,
    }

    started = time.time()

    for attempt in range(1, retries + 1):
        record["attempts"] = attempt

        try:
            process = subprocess.run(
                [
                    "claude",
                    "-p",
                    "--model",
                    model,
                    "--tools",
                    "",
                    "--setting-sources",
                    "",
                    "--no-session-persistence",
                    "--output-format",
                    "json",
                    "--system-prompt",
                    SYSTEM_PROMPT,
                    "--json-schema",
                    schema,
                ],
                input=user_prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
                cwd=cwd,
                env=env,
            )

            if process.returncode != 0:
                raise RuntimeError(
                    f"claude rc={process.returncode}: "
                    f"{process.stderr[:200]}"
                )

            response = json.loads(process.stdout)
            structured = response.get(
                "structured_output"
            )

            if (
                response.get("is_error")
                or not isinstance(
                    structured,
                    dict,
                )
                or not isinstance(
                    structured.get("predictions"),
                    dict,
                )
            ):
                raise RuntimeError(
                    "structured_output이 없습니다: "
                    f"{str(response.get('result'))[:200]}"
                )

            record["predictions"] = structured[
                "predictions"
            ]
            record["served_model"] = list(
                (
                    response.get("modelUsage")
                    or {}
                ).keys()
            )
            record["cost_usd"] = response.get(
                "total_cost_usd"
            )
            record["error"] = None
            break

        except Exception as error:  # noqa: BLE001
            record["error"] = (
                f"{type(error).__name__}: "
                f"{str(error)[:200]}"
            )

    record["sec"] = round(
        time.time() - started,
        1,
    )

    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--env-file",
        type=Path,
        help=(
            "KISIA 게이트웨이 AUTH_TOKEN/API_KEY와 "
            "BASE_URL이 든 저장소 밖 .env"
        ),
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-6",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "기본은 w=19 파일럿 10개. "
            "지정하면 전체 70개."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="API 호출 없이 입력 개수와 길이만 확인",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = build_rows(args.all)

    mode = (
        "전체 70개"
        if args.all
        else "w=19 파일럿 10개"
    )

    print(f"모드: {mode}")
    print(f"입력 수: {len(rows)}")

    for row in rows:
        prompt = build_user_prompt(row)
        print(
            f"{row['persona_id']} "
            f"w={row['window_size']} "
            f"risk={row['our_risk']} "
            f"posts={len(row['posts'])} "
            f"chars={len(prompt)}"
        )

    if args.dry_run:
        print(
            "dry-run 완료 — API를 호출하지 않았습니다."
        )
        return 0

    if args.env_file is None:
        raise SystemExit(
            "--env-file이 필요합니다."
        )

    env, credential_kind = load_gateway_env(
        args.env_file
    )

    DATA.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = DATA / (
        "teacher_all.jsonl"
        if args.all
        else "teacher_pilot.jsonl"
    )
    done = completed_keys(output_path)

    base_url = env["ANTHROPIC_BASE_URL"]
    gateway_hash = hashlib.sha256(
        base_url.encode("utf-8")
    ).hexdigest()[:12]

    with (
        tempfile.TemporaryDirectory() as cwd,
        tempfile.TemporaryDirectory() as config_dir,
    ):
        env["CLAUDE_CONFIG_DIR"] = config_dir

        auth_method = validate_auth(
            env,
            credential_kind,
            cwd,
        )

        print(
            f"인증: {auth_method} "
            f"· credential={credential_kind} "
            f"· gateway_sha256_12={gateway_hash}"
        )

        with output_path.open(
            "a",
            encoding="utf-8",
        ) as output_file:
            for row in rows:
                key = (
                    row["persona_id"],
                    row["window_size"],
                )

                if key in done:
                    print(
                        row["persona_id"],
                        f"w={row['window_size']}",
                        "skip",
                    )
                    continue

                record = invoke_teacher(
                    row=row,
                    model=args.model,
                    timeout=args.timeout,
                    retries=args.retries,
                    env=env,
                    cwd=cwd,
                )

                record["credential_kind"] = (
                    credential_kind
                )
                record["auth_method"] = auth_method
                record[
                    "gateway_url_sha256_12"
                ] = gateway_hash

                output_file.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                output_file.flush()

                status = (
                    "ok"
                    if record["predictions"]
                    else f"FAIL {record['error']}"
                )

                print(
                    row["persona_id"],
                    f"w={row['window_size']}",
                    status,
                    f"{record['sec']}s",
                    flush=True,
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())