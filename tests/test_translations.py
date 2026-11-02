"""Every translation covers exactly what the English strings do."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

INTEGRATION = Path(__file__).parent.parent / "custom_components/spot_heating_planner"
STRINGS = INTEGRATION / "strings.json"
TRANSLATIONS = sorted((INTEGRATION / "translations").glob("*.json"))
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def flatten(tree: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Every text by its dotted key."""
    texts: dict[str, str] = {}
    for key, value in tree.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            texts |= flatten(value, f"{path}.")
        else:
            texts[path] = value
    return texts


def test_english_translation_is_the_strings_file() -> None:
    assert load(INTEGRATION / "translations/en.json") == load(STRINGS)


@pytest.mark.parametrize("path", TRANSLATIONS, ids=lambda p: p.stem)
def test_same_keys_as_the_english_strings(path: Path) -> None:
    english = flatten(load(STRINGS))
    translated = flatten(load(path))
    assert sorted(translated) == sorted(english)


@pytest.mark.parametrize("path", TRANSLATIONS, ids=lambda p: p.stem)
def test_same_placeholders_as_the_english_strings(path: Path) -> None:
    english = flatten(load(STRINGS))
    translated = flatten(load(path))
    for key, text in english.items():
        assert set(PLACEHOLDER.findall(translated[key])) == set(
            PLACEHOLDER.findall(text)
        ), key


def test_finnish_is_there() -> None:
    assert "fi" in {path.stem for path in TRANSLATIONS}
