from pathlib import Path

from gcp_local.core.storage import data_path


def test_data_path_creates_nested_dir(tmp_path: Path):
    result = data_path("gcs", tmp_path)
    assert result == tmp_path / "gcs"
    assert result.is_dir()


def test_data_path_idempotent(tmp_path: Path):
    p1 = data_path("bigquery", tmp_path)
    p2 = data_path("bigquery", tmp_path)
    assert p1 == p2
    assert p1.is_dir()
