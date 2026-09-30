"""Enforce the repository convention: no hyphen or dash characters in any text file."""

from pathlib import Path

from trafficlegal.utils import DASH_CHARACTERS

ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {".py", ".md", ".txt", ".csv", ".json", ".cfg", ".toml", ".yml", ".yaml", ""}
SKIP_DIRS = {"artifacts", ".git", "__pycache__", ".pytest_cache", "build", "dist", ".venv", "venv"}


def _text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS or part.startswith("trafficlegal.egg") for part in path.parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            yield path


def test_no_dash_characters_anywhere():
    offenders = []
    for path in _text_files():
        text = path.read_text(encoding="utf8", errors="ignore")
        for number, line in enumerate(text.splitlines(), start=1):
            if any(ch in line for ch in DASH_CHARACTERS):
                offenders.append(str(path.relative_to(ROOT)) + ":" + str(number))
                break
    assert not offenders, "Dash characters found in: " + ", ".join(offenders[:20])


def test_file_names_have_no_dashes():
    bad = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*")
           if not any(part in SKIP_DIRS for part in p.parts) and any(ch in p.name for ch in DASH_CHARACTERS)
           and not p.name.startswith("trafficlegal.egg")]
    assert not bad, bad
