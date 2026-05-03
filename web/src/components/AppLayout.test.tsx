import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AppLayout } from "./AppLayout";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppLayout
        services={[
          { name: "gcs", ports: [{ number: 4443, protocol: "rest" }], ui_supported: true },
          { name: "bigquery", ports: [{ number: 9050, protocol: "rest" }], ui_supported: false },
        ]}
        host="localhost:4510"
      >
        <div>page content</div>
      </AppLayout>
    </MemoryRouter>,
  );
}

describe("AppLayout", () => {
  it("shows the host string", () => {
    renderAt("/gcs");
    expect(screen.getByText("localhost:4510")).toBeInTheDocument();
  });

  it("renders nav links for ui-supported services and disables others", () => {
    renderAt("/gcs");
    const gcs = screen.getByRole("link", { name: /gcs/i });
    expect(gcs).toHaveAttribute("href", "/gcs");
    const bq = screen.getByText(/bigquery/i);
    expect(bq.closest("a")).toBeNull();
  });

  it("renders children", () => {
    renderAt("/gcs");
    expect(screen.getByText("page content")).toBeInTheDocument();
  });
});
