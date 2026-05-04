import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, UiApi } from "./client";

const json = (status: number, body: unknown) =>
  Promise.resolve(
    new Response(typeof body === "string" ? body : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );

describe("UiApi", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("listBuckets parses the response", async () => {
    fetchMock.mockReturnValueOnce(
      json(200, { buckets: [{ name: "x", location: "US", storage_class: "STANDARD", time_created: "t" }] }),
    );
    const api = new UiApi();
    const out = await api.listBuckets();
    expect(out.buckets[0].name).toBe("x");
  });

  it("throws ApiError with code+message on envelope errors", async () => {
    fetchMock.mockReturnValueOnce(
      json(409, { error: { code: "already_exists", message: "bucket 'x' already exists" } }),
    );
    const api = new UiApi();
    await expect(api.createBucket({ name: "x" })).rejects.toMatchObject({
      code: "already_exists",
      message: "bucket 'x' already exists",
      status: 409,
    });
    fetchMock.mockReturnValueOnce(
      json(409, { error: { code: "already_exists", message: "bucket 'x' already exists" } }),
    );
    await expect(api.createBucket({ name: "x" })).rejects.toBeInstanceOf(ApiError);
  });

  it("throws on network failure with code='network'", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const api = new UiApi();
    await expect(api.listBuckets()).rejects.toMatchObject({ code: "network" });
  });
});
