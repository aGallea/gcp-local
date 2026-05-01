from datetime import UTC, datetime

from gcp_local.services.firestore.models import DocumentRecord, IndexRecord, TransactionRecord


def test_document_record_holds_fields():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    rec = DocumentRecord("p", "(default)", "u/a", {"x": 1}, now, now, 7)
    assert rec.version == 7
    assert rec.fields == {"x": 1}


def test_transaction_record_defaults_empty_read_set_and_writes():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    txn = TransactionRecord("t-1", "p", "(default)", 5, False, now)
    assert txn.read_set == set()
    assert txn.writes == []
    assert txn.read_time is None


def test_index_record_defaults_state_ready():
    idx = IndexRecord(name="projects/p/.../indexes/i1", fields=[])
    assert idx.state == "READY"
