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
