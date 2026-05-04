import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError } from "../../api/client";
import { BlobUploadDialog } from "./BlobUploadDialog";

describe("BlobUploadDialog", () => {
  it("uploads via the file input and closes on success", async () => {
    const onUpload = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(<BlobUploadDialog open onClose={onClose} onUpload={onUpload} />);
    const file = new File(["hi"], "hi.txt", { type: "text/plain" });
    await userEvent.upload(screen.getByLabelText(/select file/i), file);
    await userEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    await waitFor(() => expect(onUpload).toHaveBeenCalledWith(file));
    expect(onClose).toHaveBeenCalled();
  });

  it("shows API error on failure and stays open", async () => {
    const onUpload = vi.fn().mockRejectedValue(new ApiError("payload_too_large", 413, "too big"));
    const onClose = vi.fn();
    render(<BlobUploadDialog open onClose={onClose} onUpload={onUpload} />);
    const file = new File(["hi"], "hi.txt", { type: "text/plain" });
    await userEvent.upload(screen.getByLabelText(/select file/i), file);
    await userEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    await waitFor(() => expect(screen.getByText(/too big/)).toBeInTheDocument());
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does not render when open=false", () => {
    render(<BlobUploadDialog open={false} onClose={() => {}} onUpload={() => Promise.resolve()} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
