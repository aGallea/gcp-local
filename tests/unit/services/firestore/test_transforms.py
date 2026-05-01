from datetime import UTC, datetime

from gcp_local.generated.google.firestore.v1 import document_pb2, write_pb2
from gcp_local.services.firestore.engine.transforms import apply_transform
from gcp_local.services.firestore.values import to_proto

NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


def _t(field_path: str, **kwargs) -> write_pb2.DocumentTransform.FieldTransform:
    return write_pb2.DocumentTransform.FieldTransform(field_path=field_path, **kwargs)


class TestServerTimestamp:
    def test_sets_to_server_time_on_missing_field(self):
        fields = {}
        t = _t(
            "created", set_to_server_value=write_pb2.DocumentTransform.FieldTransform.REQUEST_TIME
        )
        new_fields, _result = apply_transform(fields, t, NOW)
        assert new_fields["created"] == NOW

    def test_overwrites_existing(self):
        fields = {"created": datetime(2020, 1, 1, tzinfo=UTC)}
        t = _t(
            "created", set_to_server_value=write_pb2.DocumentTransform.FieldTransform.REQUEST_TIME
        )
        new_fields, _ = apply_transform(fields, t, NOW)
        assert new_fields["created"] == NOW


class TestIncrement:
    def test_int_plus_int_stays_int(self):
        fields = {"score": 10}
        t = _t("score", increment=to_proto(5))
        new_fields, _result = apply_transform(fields, t, NOW)
        assert new_fields["score"] == 15
        assert isinstance(new_fields["score"], int)

    def test_double_anywhere_promotes(self):
        fields = {"score": 10}
        t = _t("score", increment=to_proto(0.5))
        new_fields, _ = apply_transform(fields, t, NOW)
        assert new_fields["score"] == 10.5
        assert isinstance(new_fields["score"], float)

    def test_missing_field_treated_as_zero(self):
        fields = {}
        t = _t("counter", increment=to_proto(1))
        new_fields, _ = apply_transform(fields, t, NOW)
        assert new_fields["counter"] == 1


class TestMaximumMinimum:
    def test_maximum_picks_larger(self):
        fields = {"score": 10}
        t = _t("score", maximum=to_proto(20))
        new_fields, _ = apply_transform(fields, t, NOW)
        assert new_fields["score"] == 20

    def test_minimum_with_missing_uses_value(self):
        fields = {}
        t = _t("score", minimum=to_proto(5))
        new_fields, _ = apply_transform(fields, t, NOW)
        assert new_fields["score"] == 5


class TestArrayUnion:
    def test_appends_only_missing(self):
        fields = {"tags": ["a", "b"]}
        t = _t(
            "tags",
            append_missing_elements=document_pb2.ArrayValue(values=[to_proto("b"), to_proto("c")]),
        )
        new_fields, _ = apply_transform(fields, t, NOW)
        assert new_fields["tags"] == ["a", "b", "c"]

    def test_creates_array_when_missing(self):
        fields = {}
        t = _t("tags", append_missing_elements=document_pb2.ArrayValue(values=[to_proto("x")]))
        new_fields, _ = apply_transform(fields, t, NOW)
        assert new_fields["tags"] == ["x"]


class TestArrayRemove:
    def test_drops_all_matching(self):
        fields = {"tags": ["a", "b", "a", "c"]}
        t = _t("tags", remove_all_from_array=document_pb2.ArrayValue(values=[to_proto("a")]))
        new_fields, _ = apply_transform(fields, t, NOW)
        assert new_fields["tags"] == ["b", "c"]

    def test_no_op_on_missing_field(self):
        fields = {}
        t = _t("tags", remove_all_from_array=document_pb2.ArrayValue(values=[to_proto("a")]))
        new_fields, _ = apply_transform(fields, t, NOW)
        assert "tags" not in new_fields
