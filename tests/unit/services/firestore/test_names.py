import pytest

from gcp_local.services.firestore.errors import InvalidName
from gcp_local.services.firestore.names import (
    parse_database_root,
    parse_document_path,
    validate_collection_id,
    validate_document_id,
)


class TestParseDatabaseRoot:
    def test_default_database(self):
        project, database = parse_database_root("projects/p1/databases/(default)")
        assert project == "p1"
        assert database == "(default)"

    def test_named_database(self):
        project, database = parse_database_root("projects/p1/databases/staging")
        assert project == "p1"
        assert database == "staging"

    def test_rejects_garbage(self):
        with pytest.raises(InvalidName):
            parse_database_root("nope")

    def test_rejects_empty_project(self):
        with pytest.raises(InvalidName):
            parse_database_root("projects//databases/db")

    def test_rejects_empty_database(self):
        with pytest.raises(InvalidName):
            parse_database_root("projects/p/databases/")


class TestParseDocumentPath:
    def test_simple_path(self):
        project, database, path = parse_document_path(
            "projects/p1/databases/(default)/documents/users/alice"
        )
        assert project == "p1"
        assert database == "(default)"
        assert path == "users/alice"

    def test_subcollection_path(self):
        _project, _database, path = parse_document_path(
            "projects/p/databases/(default)/documents/users/alice/posts/p1"
        )
        assert path == "users/alice/posts/p1"

    def test_rejects_odd_segment_count(self):
        # documents path must have even segment count (collection/doc pairs)
        with pytest.raises(InvalidName):
            parse_document_path("projects/p/databases/(default)/documents/users")


class TestValidateDocumentId:
    @pytest.mark.parametrize("doc_id", ["alice", "alice-1", "a.b", "x_y", "🦀"])
    def test_accepts_valid(self, doc_id):
        validate_document_id(doc_id)

    @pytest.mark.parametrize("doc_id", ["", ".", "..", "a/b", "x" * 1501])
    def test_rejects_invalid(self, doc_id):
        with pytest.raises(InvalidName):
            validate_document_id(doc_id)


class TestValidateCollectionId:
    def test_rejects_reserved_prefix(self):
        with pytest.raises(InvalidName):
            validate_collection_id("__name__")
        with pytest.raises(InvalidName):
            validate_collection_id("__custom__")

    def test_accepts_double_underscore_only_at_one_end(self):
        validate_collection_id("__name")  # not surrounded
        validate_collection_id("name__")
