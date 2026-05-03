import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { ErrorBanner } from "./ErrorBanner";

describe("ErrorBanner", () => {
  it("shows error message and supports retry", async () => {
    const onRetry = vi.fn();
    render(<ErrorBanner error={new ApiError("network", 0, "boom")} onRetry={onRetry} />);
    expect(screen.getByText(/boom/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("hides retry button when no onRetry is provided", () => {
    render(<ErrorBanner error={new Error("kaboom")} />);
    expect(screen.getByText(/kaboom/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();
  });

  it("renders with role=alert", () => {
    render(<ErrorBanner error={new Error("nope")} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
