from pathlib import Path


WORKFLOW = Path(".github/workflows/weekly-us-fundamental-validation.yml")


def test_weekly_validation_requires_repository_sec_identity() -> None:
    content = WORKFLOW.read_text(encoding="utf-8")
    env_line = next(
        line.strip()
        for line in content.splitlines()
        if line.strip().startswith("SEC_USER_AGENT:")
    )

    assert env_line == "SEC_USER_AGENT: ${{ vars.SEC_USER_AGENT }}"
    assert "github.com/liuh886/alpha_engine" not in env_line
    assert "||" not in env_line
