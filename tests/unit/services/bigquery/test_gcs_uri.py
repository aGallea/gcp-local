"""GCS-URI parsing, glob matching, and fetcher behavior."""

from typing import Any

import httpx
import pytest

from gcp_local.services.bigquery.engine.gcs_uri import (
    GcsUriError,
    GcsUriFetcher,
    parse_gcs_uri,
)


def test_parse_simple_uri() -> None:
    p = parse_gcs_uri("gs://my-bucket/path/to/object.ndjson")
    assert p.bucket == "my-bucket"
    assert p.pattern == "path/to/object.ndjson"
    assert not p.has_glob
    assert p.list_prefix == "path/to/object.ndjson"


def test_parse_glob_uri() -> None:
    p = parse_gcs_uri("gs://b/dir/*.ndjson")
    assert p.has_glob
    assert p.list_prefix == "dir/"


def test_parse_doublestar_uri() -> None:
    p = parse_gcs_uri("gs://b/data/**")
    assert p.has_glob
    assert p.list_prefix == "data/"


def test_parse_rejects_non_gs() -> None:
    with pytest.raises(GcsUriError):
        parse_gcs_uri("s3://b/o")


def test_parse_rejects_missing_object() -> None:
    with pytest.raises(GcsUriError):
        parse_gcs_uri("gs://bucket")
    with pytest.raises(GcsUriError):
        parse_gcs_uri("gs://bucket/")


class _MockTransport(httpx.AsyncBaseTransport):
    """Minimal transport that serves an in-memory bucket over the GCS REST shape."""

    def __init__(self, bucket: str, objects: dict[str, bytes]) -> None:
        self._bucket = bucket
        self._objects = objects

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        # list-objects: /storage/v1/b/{bucket}/o
        list_prefix = f"/storage/v1/b/{self._bucket}/o"
        if path == list_prefix:
            prefix = request.url.params.get("prefix") or ""
            items: list[dict[str, Any]] = [
                {"name": name} for name in sorted(self._objects) if name.startswith(prefix)
            ]
            return httpx.Response(200, json={"items": items})
        # download: /storage/v1/b/{bucket}/o/{name}?alt=media
        prefix2 = f"/storage/v1/b/{self._bucket}/o/"
        if path.startswith(prefix2):
            name = path[len(prefix2) :]
            if name not in self._objects:
                return httpx.Response(404, json={"error": "not found"})
            return httpx.Response(200, content=self._objects[name])
        return httpx.Response(404)


class _PatchedFetcher(GcsUriFetcher):
    def __init__(self, transport: _MockTransport) -> None:
        super().__init__(endpoint="http://gcs.test")
        self._transport = transport

    async def fetch_concat(self, uris: list[str]) -> tuple[bytes, int]:
        # Override to inject the mock transport.
        if not uris:
            raise GcsUriError("sourceUris must contain at least one URI")
        async with httpx.AsyncClient(transport=self._transport) as client:
            resolved: list[tuple[str, str]] = []
            seen: set[tuple[str, str]] = set()
            for uri in uris:
                parsed = parse_gcs_uri(uri)
                if parsed.has_glob:
                    matches = await self._list_glob(client, parsed)
                    if not matches:
                        raise GcsUriError(f"no objects matched {uri!r}")
                    for name in matches:
                        key = (parsed.bucket, name)
                        if key not in seen:
                            seen.add(key)
                            resolved.append(key)
                else:
                    key = (parsed.bucket, parsed.pattern)
                    if key not in seen:
                        seen.add(key)
                        resolved.append(key)
            chunks = [await self._download(client, b, n) for b, n in resolved]
            return b"".join(chunks), len(resolved)


@pytest.mark.asyncio
async def test_fetch_single_uri() -> None:
    transport = _MockTransport("b", {"a.ndjson": b'{"id":1}\n'})
    fetcher = _PatchedFetcher(transport)
    data, n = await fetcher.fetch_concat(["gs://b/a.ndjson"])
    assert data == b'{"id":1}\n'
    assert n == 1


@pytest.mark.asyncio
async def test_fetch_concat_multi_uri_preserves_order() -> None:
    transport = _MockTransport(
        "b",
        {"a.ndjson": b"A\n", "b.ndjson": b"B\n", "c.ndjson": b"C\n"},
    )
    fetcher = _PatchedFetcher(transport)
    data, n = await fetcher.fetch_concat(["gs://b/c.ndjson", "gs://b/a.ndjson"])
    assert data == b"C\nA\n"
    assert n == 2


@pytest.mark.asyncio
async def test_fetch_glob_expands_and_dedupes() -> None:
    transport = _MockTransport(
        "b",
        {
            "dir/a.ndjson": b"1\n",
            "dir/b.ndjson": b"2\n",
            "dir/skip.csv": b"X",
            "other/c.ndjson": b"3\n",
        },
    )
    fetcher = _PatchedFetcher(transport)
    # Glob plus an explicit URI that overlaps with the glob -> dedupe.
    data, n = await fetcher.fetch_concat(["gs://b/dir/*.ndjson", "gs://b/dir/a.ndjson"])
    assert n == 2
    assert data == b"1\n2\n"


@pytest.mark.asyncio
async def test_fetch_doublestar_recurses() -> None:
    transport = _MockTransport(
        "b",
        {"data/2024/a.ndjson": b"x", "data/2025/b.ndjson": b"y"},
    )
    fetcher = _PatchedFetcher(transport)
    data, n = await fetcher.fetch_concat(["gs://b/data/**"])
    assert n == 2
    assert data == b"xy"


@pytest.mark.asyncio
async def test_fetch_glob_no_match() -> None:
    transport = _MockTransport("b", {"a.csv": b"X"})
    fetcher = _PatchedFetcher(transport)
    with pytest.raises(GcsUriError, match="no objects matched"):
        await fetcher.fetch_concat(["gs://b/*.ndjson"])


@pytest.mark.asyncio
async def test_fetch_missing_object() -> None:
    transport = _MockTransport("b", {})
    fetcher = _PatchedFetcher(transport)
    with pytest.raises(GcsUriError, match="not found"):
        await fetcher.fetch_concat(["gs://b/missing.ndjson"])


@pytest.mark.asyncio
async def test_fetch_empty_list_raises() -> None:
    fetcher = GcsUriFetcher(endpoint="http://x")
    with pytest.raises(GcsUriError):
        await fetcher.fetch_concat([])
