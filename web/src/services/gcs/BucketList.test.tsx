import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { ApiError, UiApi } from "../../api/client";
import { BucketList } from "./BucketList";

const mkApi = (overrides: Partial<UiApi> = {}): UiApi => {
  const api = new UiApi();
  Object.assign(api, overrides);
  return api;
};

describe("BucketList", () => {
  it("renders empty state when there are no buckets", async () => {
    const api = mkApi({
      listBuckets: vi.fn().mockResolvedValue({ buckets: [] }),
    });
    render(
      <MemoryRouter>
        <BucketList api={api} />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /create your first bucket/i })).toBeInTheDocument(),
    );
  });

  it("lists buckets", async () => {
    const api = mkApi({
      listBuckets: vi.fn().mockResolvedValue({
        buckets: [
          { name: "alpha", location: "US", storage_class: "STANDARD", time_created: "t" },
          { name: "beta", location: "EU", storage_class: "STANDARD", time_created: "t" },
        ],
      }),
    });
    render(
      <MemoryRouter>
        <BucketList api={api} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("alpha")).toBeInTheDocument());
    expect(screen.getByText("beta")).toBeInTheDocument();
  });

  it("creates a bucket and refreshes the list", async () => {
    const list = vi
      .fn()
      .mockResolvedValueOnce({ buckets: [] })
      .mockResolvedValueOnce({
        buckets: [{ name: "x", location: "US", storage_class: "STANDARD", time_created: "t" }],
      });
    const create = vi.fn().mockResolvedValue({
      name: "x",
      location: "US",
      storage_class: "STANDARD",
      time_created: "t",
    });
    const api = mkApi({ listBuckets: list, createBucket: create });
    render(
      <MemoryRouter>
        <BucketList api={api} />
      </MemoryRouter>,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: /create your first bucket/i }),
    );
    await userEvent.type(screen.getByLabelText(/name/i), "x");
    await userEvent.click(screen.getByRole("button", { name: /^create$/i }));
    await waitFor(() => expect(create).toHaveBeenCalledWith({ name: "x", location: "US" }));
    await waitFor(() => expect(screen.getByText("x")).toBeInTheDocument());
  });

  it("surfaces API errors on create", async () => {
    const list = vi.fn().mockResolvedValue({ buckets: [] });
    const create = vi.fn().mockRejectedValue(new ApiError("already_exists", 409, "boom"));
    const api = mkApi({ listBuckets: list, createBucket: create });
    render(
      <MemoryRouter>
        <BucketList api={api} />
      </MemoryRouter>,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: /create your first bucket/i }),
    );
    await userEvent.type(screen.getByLabelText(/name/i), "dup");
    await userEvent.click(screen.getByRole("button", { name: /^create$/i }));
    await waitFor(() => expect(screen.getByText(/boom/)).toBeInTheDocument());
  });
});
