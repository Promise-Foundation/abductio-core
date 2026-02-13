from __future__ import annotations

import json
from pathlib import Path

from case_studies.tools.aaib_bench.aaib_bench import run


def test_parse_env_file_reads_key_values(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "# comment",
                "OPENAI_API_KEY=test-key",
                "OPENAI_BASE_URL=\"https://example.invalid/v1\"",
                "EMPTY_VALUE=",
                "BAD LINE",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    values = run._parse_env_file(env_path)
    assert values["OPENAI_API_KEY"] == "test-key"
    assert values["OPENAI_BASE_URL"] == "https://example.invalid/v1"
    assert values["EMPTY_VALUE"] == ""
    assert "BAD LINE" not in values


def test_load_local_env_defaults_does_not_override_existing(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=from-file\nOTHER_KEY=from-file\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "already-set")
    monkeypatch.delenv("OTHER_KEY", raising=False)

    run._load_local_env_defaults()

    assert run.os.getenv("OPENAI_API_KEY") == "already-set"
    assert run.os.getenv("OTHER_KEY") == "from-file"


def test_env_helpers_parse_int_float_csv(monkeypatch) -> None:
    monkeypatch.setenv("INT_OK", "7")
    monkeypatch.setenv("INT_BAD", "x")
    monkeypatch.setenv("FLOAT_OK", "1.5")
    monkeypatch.setenv("FLOAT_BAD", "x")
    monkeypatch.setenv("CSV", "a, b, ,c")

    assert run._env_int("INT_OK", 1) == 7
    assert run._env_int("INT_BAD", 1) == 1
    assert run._env_float("FLOAT_OK", 1.0) == 1.5
    assert run._env_float("FLOAT_BAD", 1.0) == 1.0
    assert run._env_csv("CSV") == ("a", "b", "c")


def test_load_roots_includes_root_set_metadata(tmp_path: Path, monkeypatch) -> None:
    corpus = tmp_path / "corpus"
    spec = corpus / "spec"
    spec.mkdir(parents=True)
    (spec / "roots_library.json").write_text(
        json.dumps(
            {
                "root_sets": {
                    "AAIB_GROUND_COLLISION_S1_v1": {
                        "strict_mece_default": True,
                        "max_pair_overlap": 1.0,
                        "mece_certificate": {
                            "max_pair_overlap": 1.0,
                            "pairwise_overlaps": {"R1|R2": 1},
                            "pairwise_discriminators": {"R1|R2": "Distinct operational marker"},
                        },
                        "roots": [
                            {"id": "R1", "label": "Root One"},
                            {"id": "R2", "label": "Root Two"},
                            {"id": "H_OTHER", "label": "Other"},
                        ],
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    case_dir = corpus / "cases" / "sample_case"
    case_dir.mkdir(parents=True)
    (case_dir / "roots.yaml").write_text(
        "\n".join(
            [
                "case_id: sample_case",
                "root_set_id: AAIB_GROUND_COLLISION_S1_v1",
                "roots:",
                "  - id: R1",
                "  - id: R2",
                "  - id: H_OTHER",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AAIB_CORPUS_ROOT", str(corpus))

    root_set_id, roots, root_statements, root_set = run._load_roots(case_dir)
    assert root_set_id == "AAIB_GROUND_COLLISION_S1_v1"
    assert [root.root_id for root in roots] == ["R1", "R2"]
    assert root_statements == {"R1": "Root One", "R2": "Root Two"}
    assert root_set["strict_mece_default"] is True
    assert root_set["max_pair_overlap"] == 1.0


def test_resolve_mece_controls_uses_root_defaults_and_override() -> None:
    root_set = {
        "strict_mece_default": True,
        "max_pair_overlap": 1.0,
        "mece_certificate": {
            "max_pair_overlap": 1.0,
            "pairwise_overlaps": {"R1|R2": 1},
            "pairwise_discriminators": {"R1|R2": "distinct marker"},
        },
    }

    certificate, strict_mece, max_pair_overlap = run._resolve_mece_controls(
        root_set=root_set,
        strict_mece=None,
        max_pair_overlap=None,
        mece_certificate_override={"pairwise_overlaps": {"R1|R2": 0}},
    )

    assert strict_mece is True
    assert max_pair_overlap == 1.0
    assert certificate == {"pairwise_overlaps": {"R1|R2": 0}}


def test_validate_policy_preflight_rejects_empty_profile() -> None:
    try:
        run._validate_policy_preflight(
            policy_profile_id="",
            policy_payload={"pair_resolution_engine_enabled": True},
        )
    except ValueError as exc:
        assert "non-empty policy_profile_id" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected ValueError for empty policy profile")


def test_validate_policy_preflight_rejects_pair_engine_disabled() -> None:
    try:
        run._validate_policy_preflight(
            policy_profile_id="boeing_inference_v1",
            policy_payload={"pair_resolution_engine_enabled": False},
        )
    except ValueError as exc:
        assert "pair_resolution_engine_enabled must be true" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected ValueError when pair resolution engine is disabled")
