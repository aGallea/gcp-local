"""GCS-URI source resolution for load jobs.

Resolves `configuration.load.sourceUris` (list of `gs://bucket/object`) into the
raw bytes the existing inline-load pipeline expects. URIs may contain glob
wildcards (`*`, `?`, `[...]`) and `**` (matches across `/`); globs are
expanded via the GCS list-objects REST API.

The fetcher talks to a configurable GCS HTTP endpoint. By default this is the
loopback URL of the in-process gcp-local GCS service, but it can be pointed at
an external GCS host (real GCS or another emulator) so cross-service tests
don't require co-locating both services.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

import httpx

_GLOB_CHARS = frozenset("*?[")


class GcsUriError(ValueError):
    """Invalid `gs://` URI or unfetchable source."""


@dataclass(frozen=True)
class ParsedUri:
    bucket: str
    pattern: str  # object name or glob pattern (no leading slash)

    @property
    def has_glob(self) -> bool:
        return any(c in _GLOB_CHARS for c in self.pattern)

    @property
    def list_prefix(self) -> str:
        """Longest literal prefix usable as a list-objects `prefix` filter."""
        for i, ch in enumerate(self.pattern):
            if ch in _GLOB_CHARS:
                return self.pattern[:i]
        return self.pattern


def parse_gcs_uri(uri: str) -> ParsedUri:
    if not uri.startswith("gs://"):
        raise GcsUriError(f"sourceUri must start with gs://, got {uri!r}")
    rest = uri[len("gs://") :]
    if "/" not in rest:
        raise GcsUriError(f"sourceUri missing object path: {uri!r}")
    bucket, _, name = rest.partition("/")
    if not bucket or not name:
        raise GcsUriError(f"sourceUri must be gs://bucket/object, got {uri!r}")
    return ParsedUri(bucket=bucket, pattern=name)


def _matches(name: str, pattern: str) -> bool:
    """fnmatch with `**` semantics (matches across `/`).

    Standard fnmatch's `*` already matches across `/` because it operates on
    full strings without path-component awareness, so plain fnmatch is enough
    for both `*` and `**`. We keep this as a thin wrapper to make intent clear
    and to centralize the rule if the semantics ever need to diverge.
    """
    return fnmatch.fnmatchcase(name, pattern)


class GcsUriFetcher:
    """Resolves and downloads `gs://` URIs over HTTP."""

    def __init__(self, *, endpoint: str, timeout: float = 30.0) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout

    async def fetch_concat(self, uris: list[str]) -> tuple[bytes, int]:
        """Resolve every URI (expanding globs) and return concatenated bytes.

        Returns (data, file_count). file_count is the number of distinct
        objects fetched, after glob expansion.
        """
        if not uris:
            raise GcsUriError("sourceUris must contain at least one URI")
        async with httpx.AsyncClient(timeout=self._timeout) as client:
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
            chunks: list[bytes] = []
            for bucket, name in resolved:
                chunks.append(await self._download(client, bucket, name))
            return b"".join(chunks), len(resolved)

    async def _list_glob(
        self,
        client: httpx.AsyncClient,
        parsed: ParsedUri,
    ) -> list[str]:
        """List objects in `bucket` whose names match `parsed.pattern`."""
        names: list[str] = []
        page_token: str | None = None
        prefix = parsed.list_prefix
        while True:
            params: dict[str, str] = {}
            if prefix:
                params["prefix"] = prefix
            if page_token:
                params["pageToken"] = page_token
            url = f"{self._endpoint}/storage/v1/b/{parsed.bucket}/o"
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                raise GcsUriError(
                    f"list-objects failed for gs://{parsed.bucket}/: "
                    f"HTTP {resp.status_code} {resp.text[:200]}"
                )
            payload = resp.json()
            for item in payload.get("items") or []:
                name = item.get("name")
                if isinstance(name, str) and _matches(name, parsed.pattern):
                    names.append(name)
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        return names

    async def _download(
        self,
        client: httpx.AsyncClient,
        bucket: str,
        name: str,
    ) -> bytes:
        url = f"{self._endpoint}/storage/v1/b/{bucket}/o/{name}"
        resp = await client.get(url, params={"alt": "media"})
        if resp.status_code == 404:
            raise GcsUriError(f"object not found: gs://{bucket}/{name}")
        if resp.status_code != 200:
            raise GcsUriError(
                f"download failed for gs://{bucket}/{name}: "
                f"HTTP {resp.status_code} {resp.text[:200]}"
            )
        return resp.content
