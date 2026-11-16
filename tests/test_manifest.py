"""工单验收：`PY312M -I -m pytest tests/test_manifest.py -q`。真调宿主 ManifestValidator。
证据源 r-maibot §7：SUPPORTED_MANIFEST_VERSIONS=[2]（manifest_validator.py:818 @478f671e6）、
最小 dict 报缺 11 项、is_in_range 返二元组、is_reserved_plugin_directory 只收 Path。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _validator(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIBOT_INSTANCE_DIR", str(tmp_path))
    from src.plugin_runtime.runner.manifest_validator import ManifestValidator

    return ManifestValidator(host_version="1.4.5", sdk_version="2.23.0",
                             project_root=tmp_path,
                             validate_python_package_dependencies=False)


def _manifest() -> dict:
    with open(REPO_ROOT / "_manifest.json", encoding="utf-8") as fh:
        return json.load(fh)


def test_manifest_v2_only_and_real_file_passes(tmp_path, monkeypatch):
    v = _validator(tmp_path, monkeypatch)
    assert v.SUPPORTED_MANIFEST_VERSIONS == [2]
    assert v.validate(_manifest()) is True, v.errors


def test_missing_field_reports(tmp_path, monkeypatch):
    v = _validator(tmp_path, monkeypatch)
    bad = _manifest()
    del bad["license"]
    assert v.validate(bad) is False
    assert any("license" in e for e in v.errors)


def test_minimal_dict_gives_eleven_missing(tmp_path, monkeypatch):
    v = _validator(tmp_path, monkeypatch)
    assert v.validate({"manifest_version": 2}) is False
    assert len(v.errors) == 11  # r-maibot §7 逐字：11 个缺项


def test_host_range_is_inclusive_tuple(tmp_path, monkeypatch):
    from src.plugin_runtime.runner.manifest_validator import VersionComparator

    ok, why = VersionComparator.is_in_range("1.4.5", "1.4.5", "1.4.99")
    assert (ok, why) == (True, "")
    assert VersionComparator.is_in_range("1.5.0", "1.4.5", "1.4.99")[0] is False


def test_reserved_dir_requires_path(tmp_path, monkeypatch):
    from src.plugin_runtime.runner.manifest_validator import is_reserved_plugin_directory

    assert is_reserved_plugin_directory(Path("x/__pycache__")) is True
    with pytest.raises(AttributeError):  # 只收 Path，不收 str（r-maibot §7 实测）
        is_reserved_plugin_directory("__pycache__")
