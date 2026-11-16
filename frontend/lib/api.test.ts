import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

describe("API GET request lifecycle", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reuses identical in-flight GET requests", async () => {
    let resolveFetch!: (response: Response) => void;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      new Promise((resolve) => { resolveFetch = resolve; }),
    );

    const first = api.questions("?limit=100");
    const second = api.questions("?limit=100");
    await Promise.resolve();
    await Promise.resolve();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolveFetch(new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } }));
    await expect(Promise.all([first, second])).resolves.toEqual([[], []]);
  });

  it("removes failed GETs so a later call can retry", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce(new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } }));
    await expect(api.questions("?limit=97")).rejects.toThrow("temporary failure");
    await expect(api.questions("?limit=97")).resolves.toEqual([]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not deduplicate mutations", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    await Promise.all([api.createMock({ title: "same" }), api.createMock({ title: "same" })]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
