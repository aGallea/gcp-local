export interface Port {
  number: number;
  protocol: string;
}

export interface ServiceInfo {
  name: string;
  ports: Port[];
  ui_supported: boolean;
}

export interface ServiceList {
  services: ServiceInfo[];
  version: string;
}

export interface BucketSummary {
  name: string;
  location: string;
  storage_class: string;
  time_created: string;
}

export interface BucketList {
  buckets: BucketSummary[];
}

export interface BlobSummary {
  name: string;
  size: number;
  content_type: string;
  updated: string;
  generation: number;
}

export interface BlobList {
  bucket: string;
  prefix: string;
  blobs: BlobSummary[];
  folders: string[];
  next_page_token: string | null;
}

export interface BlobPreview {
  kind: "text" | "json" | "image" | "none";
  text: string | null;
  image_data_url: string | null;
  truncated: boolean;
  reason: string | null;
}

export interface BlobMetadata {
  bucket: string;
  name: string;
  size: number;
  content_type: string;
  time_created: string;
  updated: string;
  generation: number;
  metageneration: number;
  md5_hash: string;
  crc32c: string;
  metadata: Record<string, string>;
  preview: BlobPreview | null;
}

// ---- BigQuery -------------------------------------------------------------

export interface BqFieldInfo {
  name: string;
  type: string;
  mode: string;
  fields: BqFieldInfo[] | null;
}

export interface BqProjectInfo {
  project: string;
  dataset_count: number;
}

export interface BqProjectList {
  projects: BqProjectInfo[];
}

export interface BqDatasetSummary {
  project: string;
  dataset_id: string;
  location: string;
  create_time: string;
  last_modified_time: string;
}

export interface BqDatasetList {
  datasets: BqDatasetSummary[];
}

export interface BqTableSummary {
  project: string;
  dataset_id: string;
  table_id: string;
  create_time: string;
  last_modified_time: string;
  num_rows: number;
}

export interface BqTableList {
  tables: BqTableSummary[];
}

export interface BqTableMetadata {
  project: string;
  dataset_id: string;
  table_id: string;
  table_schema: BqFieldInfo[];
  create_time: string;
  last_modified_time: string;
  description: string | null;
  num_rows: number;
}

export type BqCell = string | number | boolean | null | BqCell[] | { [k: string]: BqCell };

export interface BqTablePreview {
  table_schema: BqFieldInfo[];
  rows: BqCell[][];
  total_rows: number;
  next_offset: number | null;
}

export interface BqQueryResult {
  job_id: string;
  statement_type: string;
  table_schema: BqFieldInfo[];
  rows: BqCell[][];
  total_rows: number;
  error: string | null;
}
