import asyncio

from gcp_local.services.gcs.ids import (
    GenerationCounter,
    compute_crc32c_b64,
    compute_md5_b64,
    new_session_id,
    rfc3339_now,
)


def test_generation_counter_monotonic() -> None:
    c = GenerationCounter()
    v1 = c.next("my-bucket")
    v2 = c.next("my-bucket")
    v3 = c.next("my-bucket")
    assert v1 == 1 and v2 == 2 and v3 == 3


def test_generation_counter_per_bucket() -> None:
    c = GenerationCounter()
    c.next("a")
    c.next("a")
    assert c.next("b") == 1
    assert c.next("a") == 3


def test_generation_counter_reset() -> None:
    c = GenerationCounter()
    c.next("a")
    c.next("a")
    c.reset_bucket("a")
    assert c.next("a") == 1


def test_generation_counter_concurrent() -> None:
    c = GenerationCounter()
    N = 200

    async def bump() -> int:
        return c.next("bucket")

    async def main() -> list[int]:
        return await asyncio.gather(*(bump() for _ in range(N)))

    results = asyncio.run(main())
    assert sorted(results) == list(range(1, N + 1))


def test_new_session_id_unique() -> None:
    ids = {new_session_id() for _ in range(100)}
    assert len(ids) == 100


def test_compute_md5_b64() -> None:
    assert compute_md5_b64(b"hello") == "XUFAKrxLKna5cZ2REBfFkg=="


def test_compute_crc32c_b64() -> None:
    # google-crc32c of b"hello" is 0x9a71bb4c = base64 "mnG7TA=="
    assert compute_crc32c_b64(b"hello") == "mnG7TA=="


def test_rfc3339_now_format() -> None:
    s = rfc3339_now()
    assert s.endswith("Z")
    assert "T" in s
