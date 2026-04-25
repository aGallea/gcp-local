import pytest

from gcp_local.services.bigquery.names import (
    DatasetRef,
    InvalidName,
    JobRef,
    TableRef,
    duckdb_schema_name,
    duckdb_table_qualname,
    parse_dataset_path,
    parse_job_path,
    parse_table_path,
    parse_three_part,
    validate_dataset_id,
    validate_job_id,
    validate_project_id,
    validate_table_id,
)

# project IDs


def test_project_id_accepts_lowercase_alnum_dash() -> None:
    validate_project_id("my-project-1")


def test_project_id_rejects_uppercase() -> None:
    with pytest.raises(InvalidName):
        validate_project_id("MyProject")


def test_project_id_rejects_underscore() -> None:
    with pytest.raises(InvalidName):
        validate_project_id("my_project")


def test_project_id_rejects_colon() -> None:
    with pytest.raises(InvalidName):
        validate_project_id("a:b")


def test_project_id_rejects_empty_or_too_long() -> None:
    with pytest.raises(InvalidName):
        validate_project_id("")
    with pytest.raises(InvalidName):
        validate_project_id("a" * 64)


# dataset IDs


def test_dataset_id_accepts_alnum_underscore() -> None:
    validate_dataset_id("My_Dataset_1")


def test_dataset_id_accepts_starting_with_digit() -> None:
    validate_dataset_id("1day")  # BQ allows this


def test_dataset_id_rejects_dash() -> None:
    with pytest.raises(InvalidName):
        validate_dataset_id("a-b")


def test_dataset_id_rejects_colon() -> None:
    with pytest.raises(InvalidName):
        validate_dataset_id("a:b")


def test_dataset_id_rejects_empty_or_too_long() -> None:
    with pytest.raises(InvalidName):
        validate_dataset_id("")
    with pytest.raises(InvalidName):
        validate_dataset_id("a" * 1025)


# table IDs


def test_table_id_accepts_alnum_underscore_dash() -> None:
    validate_table_id("events-2024_01")


def test_table_id_rejects_colon() -> None:
    with pytest.raises(InvalidName):
        validate_table_id("a:b")


# job IDs


def test_job_id_accepts_alnum_underscore_dash() -> None:
    validate_job_id("job_abc-123")


def test_job_id_rejects_dot() -> None:
    with pytest.raises(InvalidName):
        validate_job_id("a.b")


# parse paths


def test_parse_dataset_path() -> None:
    ref = parse_dataset_path("projects/my-proj/datasets/my_ds")
    assert ref == DatasetRef(project="my-proj", dataset_id="my_ds")


def test_parse_table_path() -> None:
    ref = parse_table_path("projects/my-proj/datasets/my_ds/tables/users")
    assert ref == TableRef(project="my-proj", dataset_id="my_ds", table_id="users")


def test_parse_job_path() -> None:
    ref = parse_job_path("projects/my-proj/jobs/job_abc")
    assert ref == JobRef(project="my-proj", job_id="job_abc")


def test_parse_dataset_path_rejects_bad_shape() -> None:
    with pytest.raises(InvalidName):
        parse_dataset_path("projects/my-proj/dataset/my_ds")


def test_parse_dataset_path_validates_components() -> None:
    with pytest.raises(InvalidName):
        parse_dataset_path("projects/MY-PROJ/datasets/my_ds")


# three-part backtick names


def test_parse_three_part_dotted() -> None:
    ref = parse_three_part("my-proj.my_ds.users")
    assert ref == TableRef(project="my-proj", dataset_id="my_ds", table_id="users")


def test_parse_three_part_with_colon_separator() -> None:
    ref = parse_three_part("my-proj:my_ds.users")
    assert ref == TableRef(project="my-proj", dataset_id="my_ds", table_id="users")


def test_parse_three_part_strips_backticks() -> None:
    ref = parse_three_part("`my-proj.my_ds.users`")
    assert ref == TableRef(project="my-proj", dataset_id="my_ds", table_id="users")


def test_parse_three_part_rejects_two_part() -> None:
    with pytest.raises(InvalidName):
        parse_three_part("my_ds.users")


# DuckDB identifiers


def test_duckdb_schema_name_uses_colon_separator() -> None:
    assert duckdb_schema_name("my-proj", "my_ds") == "my-proj:my_ds"


def test_duckdb_table_qualname_quotes_each_part() -> None:
    assert duckdb_table_qualname("my-proj", "my_ds", "users") == '"my-proj:my_ds"."users"'


def test_duckdb_table_qualname_validates_inputs() -> None:
    with pytest.raises(InvalidName):
        duckdb_table_qualname("BadProj", "my_ds", "users")
