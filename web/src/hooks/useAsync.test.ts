import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

import { useAsync } from "./useAsync";

describe("useAsync", () => {
  it("resolves and exposes data", async () => {
    const { result } = renderHook(() => useAsync(() => Promise.resolve(42), []));
    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(result.current.data).toBe(42);
  });

  it("captures errors and supports refresh", async () => {
    let calls = 0;
    const fn = vi.fn(() =>
      calls++ === 0 ? Promise.reject(new Error("nope")) : Promise.resolve(7),
    );
    const { result } = renderHook(() => useAsync(fn, []));
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.message).toBe("nope");
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.data).toBe(7);
  });
});
