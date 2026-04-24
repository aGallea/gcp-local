import pytest

from gcp_local.services.gcs.models import ObjectRecord
from gcp_local.services.gcs.preconditions import (
    PreconditionFailed,
    Preconditions,
    evaluate_preconditions,
)


def make_rec(gen=5, mgen=2) -> ObjectRecord:
    return ObjectRecord(
        bucket="b",
        name="o",
        size=0,
        generation=gen,
        metageneration=mgen,
        content_type="application/octet-stream",
        md5_hash="",
        crc32c="",
        time_created="t",
        updated="t",
    )


def test_no_preconditions_passes():
    evaluate_preconditions(Preconditions(), current=make_rec())


def test_if_generation_match_matches():
    evaluate_preconditions(Preconditions(if_generation_match=5), current=make_rec(gen=5))


def test_if_generation_match_mismatch():
    with pytest.raises(PreconditionFailed):
        evaluate_preconditions(Preconditions(if_generation_match=5), current=make_rec(gen=6))


def test_if_generation_match_zero_when_object_exists():
    with pytest.raises(PreconditionFailed):
        evaluate_preconditions(Preconditions(if_generation_match=0), current=make_rec())


def test_if_generation_match_zero_when_no_object():
    evaluate_preconditions(Preconditions(if_generation_match=0), current=None)


def test_if_generation_match_nonzero_when_no_object():
    with pytest.raises(PreconditionFailed):
        evaluate_preconditions(Preconditions(if_generation_match=5), current=None)


def test_if_generation_not_match():
    evaluate_preconditions(Preconditions(if_generation_not_match=99), current=make_rec(gen=5))
    with pytest.raises(PreconditionFailed):
        evaluate_preconditions(Preconditions(if_generation_not_match=5), current=make_rec(gen=5))


def test_if_metageneration_match():
    evaluate_preconditions(Preconditions(if_metageneration_match=2), current=make_rec(mgen=2))
    with pytest.raises(PreconditionFailed):
        evaluate_preconditions(Preconditions(if_metageneration_match=99), current=make_rec(mgen=2))


def test_if_metageneration_not_match():
    evaluate_preconditions(Preconditions(if_metageneration_not_match=99), current=make_rec(mgen=2))
    with pytest.raises(PreconditionFailed):
        evaluate_preconditions(
            Preconditions(if_metageneration_not_match=2), current=make_rec(mgen=2)
        )
