import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("renders title, description, and action", async () => {
    const onClick = vi.fn();
    render(
      <EmptyState
        title="No buckets yet"
        description="Create one to get started."
        actionLabel="Create bucket"
        onAction={onClick}
      />,
    );
    expect(screen.getByRole("heading", { name: "No buckets yet" })).toBeInTheDocument();
    expect(screen.getByText("Create one to get started.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create bucket" }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("omits the action button when actionLabel is missing", () => {
    render(<EmptyState title="Empty" />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
