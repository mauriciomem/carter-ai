"""``carter._yaml``: the C parser when libyaml is present, the pure-Python one otherwise."""

from __future__ import annotations

import importlib

import pytest
import yaml

from carter import _yaml

DOC = "name: carter\nagents: [a, b]\nwhen: 2026-11-12\ndup: 1\ndup: 2\n"


def test_it_uses_libyaml_when_present_and_falls_back_without(monkeypatch) -> None:
    assert _yaml.SafeLoader is getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    monkeypatch.delattr(yaml, "CSafeLoader", raising=False)
    try:
        importlib.reload(_yaml)
        assert _yaml.SafeLoader is yaml.SafeLoader
        assert _yaml.load(DOC) == yaml.safe_load(DOC)
    finally:
        monkeypatch.undo()
        importlib.reload(_yaml)


def test_it_parses_like_safe_load_and_rejects_what_it_rejected(tmp_path) -> None:
    assert _yaml.load(DOC) == yaml.safe_load(DOC)
    path = tmp_path / "x.yaml"
    path.write_text(DOC)
    with open(path) as fh:
        assert _yaml.load(fh) == yaml.safe_load(DOC)
    for bad in ("a: [1, 2", "a: b: c", "d: 2026-02-30"):
        with pytest.raises((yaml.YAMLError, ValueError)):
            _yaml.load(bad)
