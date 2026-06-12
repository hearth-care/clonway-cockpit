from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pdoc_docs_build_is_wired_into_project_config():
    pyproject = (ROOT / "pyproject.toml").read_text()
    makefile = (ROOT / "Makefile").read_text()
    ci = (ROOT / ".github/workflows/ci.yml").read_text()

    assert '"pdoc' in pyproject
    assert "\ndocs:" in makefile
    assert "uv run pdoc clonway_cockpit -o build/docs" in makefile
    assert "name: docs" in ci
    assert "make docs" in ci
    assert "actions/deploy-pages" in ci
    assert "github.ref == 'refs/heads/main'" in ci
