from pathlib import Path


def test_api_requirements_is_an_explicit_duplicate_of_root_requirements():
    root = Path(__file__).parents[1]
    api_lines = (root / "api" / "requirements.txt").read_text(encoding="utf-8").splitlines()
    root_lines = (root / "requirements.txt").read_text(encoding="utf-8").splitlines()

    assert api_lines[2:] == root_lines
