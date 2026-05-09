import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { UiApi } from "../../api/client";
import { TableDetail } from "./TableDetail";

const mkApi = (overrides: Partial<UiApi> = {}): UiApi => {
  const api = new UiApi();
  Object.assign(api, overrides);
  return api;
};

function renderAt(api: UiApi) {
  return render(
    <MemoryRouter initialEntries={["/bigquery/projects/p/datasets/d/tables/t"]}>
      <Routes>
        <Route
          path="/bigquery/projects/:project/datasets/:dataset/tables/:table"
          element={<TableDetail api={api} />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("TableDetail", () => {
  it("renders schema and preview rows", async () => {
    const meta = vi.fn().mockResolvedValue({
      project: "p",
      dataset_id: "d",
      table_id: "t",
      table_schema: [
        { name: "id", type: "INT64", mode: "NULLABLE", fields: null },
        { name: "name", type: "STRING", mode: "NULLABLE", fields: null },
      ],
      create_time: "t",
      last_modified_time: "t",
      description: null,
      num_rows: 2,
    });
    const preview = vi.fn().mockResolvedValue({
      table_schema: [
        { name: "id", type: "INT64", mode: "NULLABLE", fields: null },
        { name: "name", type: "STRING", mode: "NULLABLE", fields: null },
      ],
      rows: [
        [1, "a"],
        [2, "b"],
      ],
      total_rows: 2,
      next_offset: null,
    });
    const api = mkApi({ getBqTable: meta, previewBqTable: preview });
    renderAt(api);
    await waitFor(() => expect(screen.getAllByText("id").length).toBeGreaterThan(0));
    expect(screen.getByText("a")).toBeInTheDocument();
    expect(screen.getByText("b")).toBeInTheDocument();
    expect(screen.getByText(/page 1 of 1 — rows 1–2 of 2/i)).toBeInTheDocument();
  });
});
