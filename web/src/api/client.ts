import type {
  BlobList,
  BlobMetadata,
  BlobSummary,
  BucketList,
  BucketSummary,
  ServiceList,
} from "./types";

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const BASE = "/_emulator/ui-api/v1";

type FetchInit = Parameters<typeof fetch>[1];

async function request<T>(path: string, init?: FetchInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch (e) {
    throw new ApiError("network", 0, e instanceof Error ? e.message : "network error");
  }
  const text = await res.text();
  let body: unknown = undefined;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      // Non-JSON response (e.g., raw download). Caller handled separately.
    }
  }
  if (!res.ok) {
    const envelope = body as { error?: { code?: string; message?: string } } | undefined;
    throw new ApiError(
      envelope?.error?.code ?? "unknown",
      res.status,
      envelope?.error?.message ?? res.statusText,
    );
  }
  return body as T;
}

export class UiApi {
  listServices(): Promise<ServiceList> {
    return request("/services");
  }

  listBuckets(): Promise<BucketList> {
    return request("/gcs/buckets");
  }

  createBucket(payload: { name: string; location?: string }): Promise<BucketSummary> {
    return request("/gcs/buckets", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  deleteBucket(name: string, force = false): Promise<void> {
    return request(`/gcs/buckets/${encodeURIComponent(name)}?force=${force}`, {
      method: "DELETE",
    });
  }

  listBlobs(
    bucket: string,
    options: { prefix?: string; delimiter?: string; pageToken?: string } = {},
  ): Promise<BlobList> {
    const params = new URLSearchParams();
    if (options.prefix) params.set("prefix", options.prefix);
    if (options.delimiter) params.set("delimiter", options.delimiter);
    if (options.pageToken) params.set("page_token", options.pageToken);
    const qs = params.toString();
    return request(`/gcs/buckets/${encodeURIComponent(bucket)}/blobs${qs ? `?${qs}` : ""}`);
  }

  async uploadBlob(bucket: string, file: File, name?: string): Promise<BlobSummary> {
    const fd = new FormData();
    fd.append("file", file);
    if (name) fd.append("name", name);
    return request(`/gcs/buckets/${encodeURIComponent(bucket)}/blobs`, {
      method: "POST",
      body: fd,
    });
  }

  getBlobMetadata(bucket: string, name: string): Promise<BlobMetadata> {
    return request(
      `/gcs/buckets/${encodeURIComponent(bucket)}/blobs/${encodeURIComponent(name)}`,
    );
  }

  downloadBlobUrl(bucket: string, name: string): string {
    return `${BASE}/gcs/buckets/${encodeURIComponent(bucket)}/blobs/${encodeURIComponent(name)}/download`;
  }

  deleteBlob(bucket: string, name: string): Promise<void> {
    return request(
      `/gcs/buckets/${encodeURIComponent(bucket)}/blobs/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    );
  }
}

export const api = new UiApi();
