export type AnswerOptionReviewState = "correct" | "incorrect" | "unverified" | "neutral";

export function answerOptionReviewState(
  optionKey: string,
  selectedKey: string | null | undefined,
  correctKey: string | null | undefined,
  answerKeyAvailable: boolean,
): AnswerOptionReviewState {
  if (answerKeyAvailable && correctKey === optionKey) return "correct";
  if (selectedKey !== optionKey) return "neutral";
  return answerKeyAvailable ? "incorrect" : "unverified";
}
