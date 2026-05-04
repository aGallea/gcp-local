import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("calls onConfirm and onCancel", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const { rerender } = render(
      <ConfirmDialog
        open
        title="Delete bucket"
        message="This cannot be undone."
        confirmLabel="Delete"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /delete/i }));
    expect(onConfirm).toHaveBeenCalled();
    rerender(<ConfirmDialog open={false} title="" onConfirm={onConfirm} onCancel={onCancel} />);
    expect(screen.queryByText("Delete bucket")).not.toBeInTheDocument();
  });

  it("does not render when open is false", () => {
    render(
      <ConfirmDialog
        open={false}
        title="Hidden"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.queryByText("Hidden")).toBeNull();
  });
});
