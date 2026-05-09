import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { ApiError, UiApi } from "../../api/client";
import { DatasetList } from "./DatasetList";

const mkApi = (overrides: Partial<UiApi> = {}): UiApi => {
  const api = new UiApi();
  Object.assign(api, overrides);
  return api;
};

function renderAt(path: string, api: UiApi) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/bigquery/projects/:project" element={<DatasetList api={api} />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("DatasetList", () => {
  it("shows empty state and create button", async () => {
    const api = mkApi({ listBqDatasets: vi.fn().mockResolvedValue({ datasets: [] }) });
    renderAt("/bigquery/projects/p", api);
    await waitFor(() => expect(screen.getByText(/no datasets yet/i)).toBeInTheDocument());
    expect(screen.getAllByRole("button", { name: /^create dataset$/i }).length).toBeGreaterThan(0);
  });

  it("lists datasets returned by the API", async () => {
    const api = mkApi({
      listBqDatasets: vi.fn().mockResolvedValue({
        datasets: [
          {
            project: "p",
            dataset_id: "alpha",
            location: "US",
            create_time: "t",
            last_modified_time: "t",
          },
          {
            project: "p",
            dataset_id: "beta",
            location: "EU",
            create_time: "t",
            last_modified_time: "t",
          },
        ],
      }),
    });
    renderAt("/bigquery/projects/p", api);
    await waitFor(() => expect(screen.getByText("alpha")).toBeInTheDocument());
    expect(screen.getByText("beta")).toBeInTheDocument();
  });

  it("creates a dataset and refreshes the list", async () => {
    const list = vi
      .fn()
      .mockResolvedValueOnce({ datasets: [] })
      .mockResolvedValueOnce({
        datasets: [
          {
            project: "p",
            dataset_id: "x",
            location: "US",
            create_time: "t",
            last_modified_time: "t",
          },
        ],
      });
    const create = vi.fn().mockResolvedValue({
      project: "p",
      dataset_id: "x",
      location: "US",
      create_time: "t",
      last_modified_time: "t",
    });
    const api = mkApi({ listBqDatasets: list, createBqDataset: create });
    renderAt("/bigquery/projects/p", api);
    const createBtns = await screen.findAllByRole("button", { name: /^create dataset$/i });
    await userEvent.click(createBtns[0]);
    await userEvent.type(screen.getByLabelText(/dataset id/i), "x");
    await userEvent.click(screen.getByRole("button", { name: /^create$/i }));
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith("p", { dataset_id: "x", location: "US" }),
    );
    await waitFor(() => expect(screen.getByText("x")).toBeInTheDocument());
  });

  it("surfaces API errors on create", async () => {
    const list = vi.fn().mockResolvedValue({ datasets: [] });
    const create = vi.fn().mockRejectedValue(new ApiError("already_exists", 409, "duplicate"));
    const api = mkApi({ listBqDatasets: list, createBqDataset: create });
    renderAt("/bigquery/projects/p", api);
    const createBtns = await screen.findAllByRole("button", { name: /^create dataset$/i });
    await userEvent.click(createBtns[0]);
    await userEvent.type(screen.getByLabelText(/dataset id/i), "dup");
    await userEvent.click(screen.getByRole("button", { name: /^create$/i }));
    await waitFor(() => expect(screen.getByText(/duplicate/)).toBeInTheDocument());
  });
});
