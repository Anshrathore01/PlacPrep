import type { ProductDsaQuestion } from "./types";

export type ProductDsaFilters = {
  query: string;
  topic: string;
  difficulty: string;
  platform: string;
};

export function filterProductDsaQuestions(
  questions: ProductDsaQuestion[],
  filters: ProductDsaFilters,
): ProductDsaQuestion[] {
  const query = filters.query.trim().toLocaleLowerCase();
  return questions.filter((question) =>
    (!query || question.title.toLocaleLowerCase().includes(query)) &&
    (!filters.topic || question.topic === filters.topic) &&
    (!filters.difficulty || question.difficulty === filters.difficulty) &&
    (!filters.platform || question.platform === filters.platform),
  );
}

export function completedQuestionCount(questions: ProductDsaQuestion[]): number {
  return questions.reduce((count, question) => count + Number(question.is_completed), 0);
}
