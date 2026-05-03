import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { UiApi } from "../../api/client";
import { BlobList } from "./BlobList";

const mkApi = (overrides: Partial<UiApi>): UiApi => {
  const api = new UiApi();
  Object.assign(api, overrides);
  return api;
};

const renderAt = (path: string, api: UiApi) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/gcs/buckets/:bucket/*" element={<BlobList api={api} />} />
      </Routes>
    </MemoryRouter>,
  );

describe("BlobList", () => {
  it("renders blobs and folders for the current prefix", async () => {
    const api = mkApi({
      listBlobs: vi.fn().mockResolvedValue({
        bucket: "b",
        prefix: "",
        blobs: [
          { name: "a.txt", size: 3, content_type: "text/plain", updated: "t", generation: 1 },
        ],
        folders: ["logs/"],
        next_page_token: null,
      }),
    });
    renderAt("/gcs/buckets/b", api);
    await waitFor(() => expect(screen.getByText(/a\.txt/)).toBeInTheDocument());
    expect(screen.getByText(/logs\//)).toBeInTheDocument();
  });

  it("navigates into a folder when the row is clicked", async () => {
    const list = vi
      .fn()
      .mockResolvedValueOnce({
        bucket: "b",
        prefix: "",
        blobs: [],
        folders: ["logs/"],
        next_page_token: null,
      })
      .mockResolvedValueOnce({
        bucket: "b",
        prefix: "logs/",
        blobs: [
          { name: "logs/a.log", size: 1, content_type: "text/plain", updated: "t", generation: 1 },
        ],
        folders: [],
        next_page_token: null,
      });
    const api = mkApi({ listBlobs: list });
    renderAt("/gcs/buckets/b", api);
    await userEvent.click(await screen.findByText(/logs\//));
    await waitFor(() => expect(screen.getByText(/a\.log/)).toBeInTheDocument());
    expect(list).toHaveBeenLastCalledWith("b", { prefix: "logs/", delimiter: "/" });
  });

  it("renders empty state when bucket has no blobs and no folders", async () => {
    const api = mkApi({
      listBlobs: vi.fn().mockResolvedValue({
        bucket: "b",
        prefix: "",
        blobs: [],
        folders: [],
        next_page_token: null,
      }),
    });
    renderAt("/gcs/buckets/b", api);
    await waitFor(() =>
      expect(screen.getByText(/this folder is empty/i)).toBeInTheDocument(),
    );
  });

  it("deletes a blob via the confirm dialog and refreshes", async () => {
    const list = vi
      .fn()
      .mockResolvedValueOnce({
        bucket: "b",
        prefix: "",
        blobs: [
          { name: "a.txt", size: 3, content_type: "text/plain", updated: "t", generation: 1 },
        ],
        folders: [],
        next_page_token: null,
      })
      .mockResolvedValueOnce({
        bucket: "b",
        prefix: "",
        blobs: [],
        folders: [],
        next_page_token: null,
      });
    const del = vi.fn().mockResolvedValue(undefined);
    const api = mkApi({ listBlobs: list, deleteBlob: del });
    renderAt("/gcs/buckets/b", api);
    await userEvent.click(await screen.findByRole("button", { name: /^delete$/i }));
    await userEvent.click(screen.getAllByRole("button", { name: /^delete$/i }).pop()!);
    await waitFor(() => expect(del).toHaveBeenCalledWith("b", "a.txt"));
    await waitFor(() =>
      expect(screen.getByText(/this folder is empty/i)).toBeInTheDocument(),
    );
  });
});
