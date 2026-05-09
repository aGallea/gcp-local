import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { UiApi } from "../../api/client";
import { QueryConsole } from "./QueryConsole";

const mkApi = (overrides: Partial<UiApi> = {}): UiApi => {
  const api = new UiApi();
  Object.assign(api, overrides);
  return api;
};

function renderAt(api: UiApi) {
  return render(
    <MemoryRouter initialEntries={["/bigquery/projects/p/query"]}>
      <Routes>
        <Route
          path="/bigquery/projects/:project/query"
          element={<QueryConsole api={api} />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("QueryConsole", () => {
  it("runs a SELECT and renders rows", async () => {
    const run = vi.fn().mockResolvedValue({
      job_id: "j1",
      statement_type: "SELECT",
      table_schema: [
        { name: "a", type: "INT64", mode: "NULLABLE", fields: null },
        { name: "b", type: "STRING", mode: "NULLABLE", fields: null },
      ],
      rows: [[1, "hello"]],
      total_rows: 1,
      error: null,
    });
    const api = mkApi({ runBqQuery: run });
    renderAt(api);
    const box = screen.getByRole("textbox");
    await userEvent.clear(box);
    await userEvent.type(box, "SELECT 1");
    await userEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() =>
      expect(run).toHaveBeenCalledWith({
        project: "p",
        sql: "SELECT 1",
        max_results: 200,
      }),
    );
    await waitFor(() => expect(screen.getByText("hello")).toBeInTheDocument());
  });

  it("shows the error message when the API returns one", async () => {
    const run = vi.fn().mockResolvedValue({
      job_id: "j1",
      statement_type: "SELECT",
      table_schema: [],
      rows: [],
      total_rows: 0,
      error: "table not found",
    });
    const api = mkApi({ runBqQuery: run });
    renderAt(api);
    await userEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() => expect(screen.getByText(/table not found/i)).toBeInTheDocument());
  });
});
