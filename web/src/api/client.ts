import type {
  BlobList,
  BlobMetadata,
  BlobSummary,
  BqDatasetList,
  BqDatasetSummary,
  BqProjectList,
  BqQueryResult,
  BqTableList,
  BqTableMetadata,
  BqTablePreview,
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

  // ---- BigQuery -----------------------------------------------------------

  listBqProjects(): Promise<BqProjectList> {
    return request("/bigquery/projects");
  }

  listBqDatasets(project: string): Promise<BqDatasetList> {
    return request(`/bigquery/projects/${encodeURIComponent(project)}/datasets`);
  }

  createBqDataset(
    project: string,
    payload: { dataset_id: string; location?: string },
  ): Promise<BqDatasetSummary> {
    return request(`/bigquery/projects/${encodeURIComponent(project)}/datasets`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  deleteBqDataset(project: string, datasetId: string, deleteContents = false): Promise<void> {
    return request(
      `/bigquery/projects/${encodeURIComponent(project)}/datasets/${encodeURIComponent(datasetId)}?delete_contents=${deleteContents}`,
      { method: "DELETE" },
    );
  }

  listBqTables(project: string, datasetId: string): Promise<BqTableList> {
    return request(
      `/bigquery/projects/${encodeURIComponent(project)}/datasets/${encodeURIComponent(datasetId)}/tables`,
    );
  }

  getBqTable(
    project: string,
    datasetId: string,
    tableId: string,
  ): Promise<BqTableMetadata> {
    return request(
      `/bigquery/projects/${encodeURIComponent(project)}/datasets/${encodeURIComponent(datasetId)}/tables/${encodeURIComponent(tableId)}`,
    );
  }

  deleteBqTable(project: string, datasetId: string, tableId: string): Promise<void> {
    return request(
      `/bigquery/projects/${encodeURIComponent(project)}/datasets/${encodeURIComponent(datasetId)}/tables/${encodeURIComponent(tableId)}`,
      { method: "DELETE" },
    );
  }

  previewBqTable(
    project: string,
    datasetId: string,
    tableId: string,
    options: { maxResults?: number; offset?: number } = {},
  ): Promise<BqTablePreview> {
    const params = new URLSearchParams();
    if (options.maxResults !== undefined) params.set("max_results", String(options.maxResults));
    if (options.offset !== undefined) params.set("offset", String(options.offset));
    const qs = params.toString();
    return request(
      `/bigquery/projects/${encodeURIComponent(project)}/datasets/${encodeURIComponent(datasetId)}/tables/${encodeURIComponent(tableId)}/preview${qs ? `?${qs}` : ""}`,
    );
  }

  runBqQuery(payload: {
    project: string;
    sql: string;
    max_results?: number;
  }): Promise<BqQueryResult> {
    return request(`/bigquery/queries`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
  }
}

export const api = new UiApi();
