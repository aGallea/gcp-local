import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { UiApi } from "../../api/client";
import { BlobPreview } from "./BlobPreview";

const mkApi = (overrides: Partial<UiApi>): UiApi => {
  const api = new UiApi();
  Object.assign(api, overrides);
  return api;
};

describe("BlobPreview", () => {
  it("renders text content", async () => {
    const api = mkApi({
      getBlobMetadata: vi.fn().mockResolvedValue({
        bucket: "b",
        name: "x.txt",
        size: 2,
        content_type: "text/plain",
        time_created: "t",
        updated: "t",
        generation: 1,
        metageneration: 1,
        md5_hash: "",
        crc32c: "",
        metadata: {},
        preview: { kind: "text", text: "hi", image_data_url: null, truncated: false, reason: null },
      }),
    });
    render(<BlobPreview api={api} bucket="b" name="x.txt" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("hi")).toBeInTheDocument());
  });

  it("renders truncated banner when text was cut", async () => {
    const api = mkApi({
      getBlobMetadata: vi.fn().mockResolvedValue({
        bucket: "b",
        name: "big.txt",
        size: 999999,
        content_type: "text/plain",
        time_created: "t",
        updated: "t",
        generation: 1,
        metageneration: 1,
        md5_hash: "",
        crc32c: "",
        metadata: {},
        preview: { kind: "text", text: "abc", image_data_url: null, truncated: true, reason: null },
      }),
    });
    render(<BlobPreview api={api} bucket="b" name="big.txt" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/truncated/i)).toBeInTheDocument());
  });

  it("falls back to a download link for non-previewable content", async () => {
    const api = mkApi({
      getBlobMetadata: vi.fn().mockResolvedValue({
        bucket: "b",
        name: "x.bin",
        size: 4,
        content_type: "application/octet-stream",
        time_created: "t",
        updated: "t",
        generation: 1,
        metageneration: 1,
        md5_hash: "",
        crc32c: "",
        metadata: {},
        preview: { kind: "none", text: null, image_data_url: null, truncated: false, reason: "no preview" },
      }),
    });
    render(<BlobPreview api={api} bucket="b" name="x.bin" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/no preview/i)).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /download/i })).toHaveAttribute(
      "href",
      expect.stringContaining("/_emulator/ui-api/v1/gcs/buckets/b/blobs/x.bin/download"),
    );
  });
});
