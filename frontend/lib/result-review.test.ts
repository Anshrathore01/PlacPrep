import { describe, expect, it } from "vitest";
import { answerOptionReviewState } from "./result-review";

describe("result answer review states", () => {
  it("marks a selected right answer as correct", () => {
    expect(answerOptionReviewState("A", "A", "A", true)).toBe("correct");
  });
  it("marks both a selected wrong answer and the trusted correct answer", () => {
    expect(answerOptionReviewState("B", "B", "A", true)).toBe("incorrect");
    expect(answerOptionReviewState("A", "B", "A", true)).toBe("correct");
  });
  it("keeps selections neutral when the key is unavailable", () => {
    expect(answerOptionReviewState("B", "B", null, false)).toBe("unverified");
    expect(answerOptionReviewState("A", null, null, false)).toBe("neutral");
  });
});
