from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE / "run_teacher.py"

SPEC = importlib.util.spec_from_file_location(
    "risk_correlation_teacher",
    MODULE_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(
        f"run_teacher.py를 불러올 수 없습니다: {MODULE_PATH}"
    )

teacher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(teacher)


def test_load_gateway_env_uses_auth_token_and_cleans_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / "gateway.env"
    env_file.write_text(
        "\n".join(
            [
                "ANTHROPIC_BASE_URL=https://gateway.example.test",
                "ANTHROPIC_AUTH_TOKEN=team-token",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "personal-key")
    monkeypatch.setenv("CLAUDE_CODE_SSE_PORT", "12345")
    monkeypatch.setenv("KEEP_ME", "yes")

    env, credential_kind = teacher.load_gateway_env(env_file)

    assert credential_kind == "auth_token"
    assert env["ANTHROPIC_BASE_URL"] == (
        "https://gateway.example.test"
    )
    assert env["ANTHROPIC_AUTH_TOKEN"] == "team-token"
    assert "ANTHROPIC_API_KEY" not in env
    assert "CLAUDE_CODE_SSE_PORT" not in env
    assert env["KEEP_ME"] == "yes"


def test_load_gateway_env_rejects_direct_anthropic_url(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "gateway.env"
    env_file.write_text(
        "\n".join(
            [
                "ANTHROPIC_BASE_URL=https://api.anthropic.com",
                "ANTHROPIC_AUTH_TOKEN=team-token",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        teacher.load_gateway_env(env_file)


def test_build_user_prompt_excludes_risk_and_contains_posts() -> None:
    row = {
        "persona_id": "A01",
        "window_size": 19,
        "our_risk": 42.86,
        "posts": [
            {
                "post_id": "A01_b01",
                "created_at": "2026-01-01",
                "texts": {
                    "body": "테스트 게시글입니다.",
                },
            }
        ],
    }

    prompt = teacher.build_user_prompt(row)

    assert "A01_w19" in prompt
    assert "A01_b01" in prompt
    assert "테스트 게시글입니다." in prompt
    assert "our_risk" not in prompt
    assert "42.86" not in prompt


def test_completed_keys_only_includes_successful_records(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "teacher.jsonl"
    records = [
        {
            "persona_id": "A01",
            "window_size": 19,
            "predictions": {
                "age": {
                    "value": "20대",
                    "abstain": False,
                    "evidence_post_ids": ["A01_b01"],
                }
            },
        },
        {
            "persona_id": "A02",
            "window_size": 19,
            "predictions": None,
            "error": "temporary failure",
        },
    ]

    output_path.write_text(
        "\n".join(
            json.dumps(record, ensure_ascii=False)
            for record in records
        )
        + "\n",
        encoding="utf-8",
    )

    assert teacher.completed_keys(output_path) == {
        ("A01", 19)
    }
    assert teacher.completed_keys(
        tmp_path / "missing.jsonl"
    ) == set()


def test_validate_auth_accepts_matching_oauth_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> SimpleNamespace:
        calls.append(
            {
                "command": command,
                **kwargs,
            }
        )
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "authMethod": "oauth_token",
                    "apiKeySource": "ANTHROPIC_AUTH_TOKEN",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        teacher.subprocess,
        "run",
        fake_run,
    )

    auth_method = teacher.validate_auth(
        env={
            "ANTHROPIC_BASE_URL": (
                "https://gateway.example.test"
            ),
            "ANTHROPIC_AUTH_TOKEN": "team-token",
        },
        credential_kind="auth_token",
        cwd="temporary-directory",
    )

    assert auth_method == "oauth_token"
    assert calls[0]["command"] == [
        "claude",
        "auth",
        "status",
    ]
    assert calls[0]["cwd"] == "temporary-directory"


def test_invoke_teacher_retries_then_returns_predictions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prediction = {
        attr: {
            "value": None,
            "abstain": True,
            "evidence_post_ids": [],
        }
        for attr in teacher.ATTRS
    }

    responses = iter(
        [
            SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="temporary gateway error",
            ),
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "is_error": False,
                        "structured_output": {
                            "predictions": prediction,
                        },
                        "modelUsage": {
                            "claude-sonnet-4-6": {},
                        },
                        "total_cost_usd": 0.01,
                    }
                ),
                stderr="",
            ),
        ]
    )

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> SimpleNamespace:
        return next(responses)

    monkeypatch.setattr(
        teacher.subprocess,
        "run",
        fake_run,
    )

    row = {
        "persona_id": "A01",
        "window_size": 19,
        "our_risk": 42.86,
        "posts": [
            {
                "post_id": "A01_b01",
                "created_at": "2026-01-01",
                "texts": {
                    "body": "테스트 게시글입니다.",
                },
            }
        ],
    }

    record = teacher.invoke_teacher(
        row=row,
        model="claude-sonnet-4-6",
        timeout=30,
        retries=2,
        env={
            "ANTHROPIC_BASE_URL": (
                "https://gateway.example.test"
            ),
            "ANTHROPIC_AUTH_TOKEN": "team-token",
        },
        cwd="temporary-directory",
    )

    assert record["persona_id"] == "A01"
    assert record["window_size"] == 19
    assert record["our_risk"] == 42.86
    assert record["attempts"] == 2
    assert record["predictions"] == prediction
    assert record["error"] is None
    assert record["served_model"] == [
        "claude-sonnet-4-6"
    ]