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

  it("creates a folder via the dialog and refreshes", async () => {
    const list = vi
      .fn()
      .mockResolvedValueOnce({
        bucket: "b",
        prefix: "",
        blobs: [],
        folders: [],
        next_page_token: null,
      })
      .mockResolvedValueOnce({
        bucket: "b",
        prefix: "",
        blobs: [],
        folders: ["new/"],
        next_page_token: null,
      });
    const upload = vi.fn().mockResolvedValue({
      name: "new/",
      size: 0,
      content_type: "application/x-directory",
      updated: "t",
      generation: 1,
    });
    const api = mkApi({ listBlobs: list, uploadBlob: upload });
    renderAt("/gcs/buckets/b", api);
    await userEvent.click(await screen.findByRole("button", { name: /create folder/i }));
    await userEvent.type(screen.getByLabelText(/name/i), "new");
    // Multiple "Create" buttons exist (the header CTA + the dialog confirm).
    // Click the last one (the dialog's confirm).
    const createButtons = screen.getAllByRole("button", { name: /^create$/i });
    await userEvent.click(createButtons[createButtons.length - 1]);
    await waitFor(() => expect(upload).toHaveBeenCalled());
    const args = upload.mock.calls[0];
    expect(args[0]).toBe("b");
    expect(args[1]).toBeInstanceOf(File);
    expect(args[2]).toBe("new/");
    await waitFor(() => expect(screen.getByText(/new\//)).toBeInTheDocument());
  });

  it("hides the placeholder object when listing inside a folder", async () => {
    const api = mkApi({
      listBlobs: vi.fn().mockResolvedValue({
        bucket: "b",
        prefix: "logs/",
        blobs: [
          {
            name: "logs/",
            size: 0,
            content_type: "application/x-directory",
            updated: "t",
            generation: 1,
          },
          {
            name: "logs/a.log",
            size: 1,
            content_type: "text/plain",
            updated: "t",
            generation: 1,
          },
        ],
        folders: [],
        next_page_token: null,
      }),
    });
    renderAt("/gcs/buckets/b?prefix=logs/", api);
    await waitFor(() => expect(screen.getByText(/a\.log/)).toBeInTheDocument());
    // The placeholder row "logs/" should not appear as a file row.
    expect(screen.queryByText("📄 ")).toBeNull();
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
