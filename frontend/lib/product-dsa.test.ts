import { describe, expect, it } from "vitest";
import type { ProductDsaQuestion } from "./types";
import { completedQuestionCount, filterProductDsaQuestions } from "./product-dsa";

const questions: ProductDsaQuestion[] = [
  { id: "a", question_number: 1, title: "Two Sum", topic: "Arrays & Hashing", difficulty: "Easy", platform: "LeetCode", url: "https://leetcode.com/problems/two-sum/", is_completed: true },
  { id: "b", question_number: 2, title: "Number of Islands", topic: "Graphs", difficulty: "Medium", platform: "LeetCode", url: "https://leetcode.com/problems/number-of-islands/", is_completed: false },
  { id: "c", question_number: 3, title: "Alien Dictionary", topic: "Graphs", difficulty: "Hard", platform: "GeeksforGeeks", url: "https://www.geeksforgeeks.org/problems/alien-dictionary/1", is_completed: false },
];

describe("product DSA question filtering", () => {
  it("filters by title, topic, difficulty, and platform together", () => {
    expect(filterProductDsaQuestions(questions, { query: "  alien ", topic: "Graphs", difficulty: "Hard", platform: "GeeksforGeeks" }).map((q) => q.id)).toEqual(["c"]);
  });

  it("keeps filters independent when one is cleared", () => {
    expect(filterProductDsaQuestions(questions, { query: "", topic: "Graphs", difficulty: "", platform: "" }).map((q) => q.id)).toEqual(["b", "c"]);
  });

  it("counts completed questions from the full bank, independent of visible filters", () => {
    expect(completedQuestionCount(questions)).toBe(1);
    expect(filterProductDsaQuestions(questions, { query: "islands", topic: "", difficulty: "", platform: "" })).toHaveLength(1);
    expect(completedQuestionCount(questions)).toBe(1);
  });
});
