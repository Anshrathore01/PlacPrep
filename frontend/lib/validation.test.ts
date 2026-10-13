import { describe, expect, it } from "vitest";
import { activePlacoNotice, mixedDistributionIsValid } from "./validation";

describe("AI mock validation", () => {
  it("accepts a distribution that matches the requested total", () => {
    expect(mixedDistributionIsValid({ EASY: 6, MEDIUM: 10, TOUGH: 4 }, 20)).toBe(true);
  });
  it("rejects mismatched or negative distributions", () => {
    expect(mixedDistributionIsValid({ EASY: 6, MEDIUM: 10, TOUGH: 3 }, 20)).toBe(false);
    expect(mixedDistributionIsValid({ EASY: -1, MEDIUM: 10, TOUGH: 11 }, 20)).toBe(false);
  });
});

describe("Placo assessment safety copy", () => {
  it("shows the conceptual-only notice during an active assessment", () => {
    expect(activePlacoNotice("ACTIVE_ASSESSMENT")).toMatch(/cannot reveal the answer/);
    expect(activePlacoNotice("PRACTICE")).toBeNull();
  });
});
