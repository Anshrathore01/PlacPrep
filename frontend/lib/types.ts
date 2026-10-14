export type User = { user_id: number; email: string; display_name?: string | null; role: string; is_active: boolean; created_at?: string | null };
export type ProductDsaQuestion = {
  id: string;
  question_number: number;
  title: string;
  topic: string;
  difficulty: "Easy" | "Medium" | "Hard";
  platform: "LeetCode" | "GeeksforGeeks";
  url: string;
  is_completed: boolean;
};
export type QuestionListItem = { question_id: number; title?: string | null; question_type: string; difficulty?: string | null };
/** Canonical option payload. `option_key` remains the stable scoring key. */
export type Option = {
  id: number;
  label: string;
  text: string;
  order: number;
  option_key: string;
  option_text: string;
  display_order: number;
};
export type QuestionExample = {
  example_number?: number | string | null;
  input_data?: string | null;
  output_data?: string | null;
  explanation?: string | null;
  [key: string]: unknown;
};
export type Question = QuestionListItem & { status?: string | null; section?: string | null; passage?: string | null; question_text?: string | null; is_multiple_correct?: boolean | null; options?: Option[] | null; problem_statement?: string | null; constraints_text?: string | null; input_format?: string | null; output_format?: string | null; starter_code?: string | null; solution_pseudocode?: string | null; solution_explanation?: string | null; examples?: QuestionExample[] | null };
export type MockTest = { mock_test_id: number; blueprint_id?: number | null; company_id?: number | null; company_name?: string | null; program_name?: string | null; pattern_version?: string | null; verification_status?: string | null; title: string; mode: string; selection_mode: string; duration_seconds?: number | null; total_questions: number; status: string };
export type FullLengthMock = { mock_test_id: number; title: string; total_questions: number; duration_seconds?: number | null; sections: string[]; coding_question_count: number; paper_number: number; };
export type Attempt = { attempt_id: number; user_id: number; mock_test_id: number; started_at: string; submitted_at?: string | null; status: string; score?: number | null; max_score?: number | null; accuracy?: number | null; time_spent_seconds?: number | null; expires_at?: string | null; mock_test?: { mock_test_id: number; title: string; duration_seconds?: number | null; total_questions: number; status: string }; questions?: (Question & { sequence_no: number; points: number; selected_option_key?: string | null; answer_text?: string | null; time_spent_seconds?: number; is_correct?: boolean | null; points_awarded?: number | null; correct_option_key?: string | null; answer_key_available?: boolean })[] };
export type AnalyticsSummary = { total_attempts: number; completed_attempts: number; expired_attempts: number; abandoned_attempts: number; questions_assigned: number; questions_attempted: number; questions_correct: number; questions_skipped: number; mcq_questions_attempted: number; mcq_questions_correct: number; average_accuracy: number; average_score_percentage: number; highest_score_percentage?: number | null; lowest_score_percentage?: number | null; coding_submissions: number; coding_problems_attempted: number; coding_problems_solved: number; coding_success_rate: number; topics: TopicMetric[] };
export type TopicMetric = { topic_id: number; topic_name: string; questions_attempted: number; questions_correct: number; accuracy: number; average_time_seconds?: number | null };
export type Company = { company_id: number; company_name: string; slug?: string; description?: string | null; blueprints?: Blueprint[]; full_length_mocks?: FullLengthMock[] };
export type Blueprint = { blueprint_id: number; company_id?: number | null; company_name?: string | null; blueprint_name?: string; program_name?: string; pattern_version?: string; status?: string; ready_for_mock?: boolean; rules?: { section_name?: string; question_count: number; question_type: string; difficulty?: string }[] };
export type AIRequest = { title: string; question_type: "MCQ" | "CODING"; track_id?: number; topic_id?: number; subtopic_id?: number; difficulty_mode: "EASY" | "MEDIUM" | "TOUGH" | "MIXED"; total_questions: number; duration_seconds?: number; difficulty_distribution?: { EASY: number; MEDIUM: number; TOUGH: number }; blueprint_id?: number; exclude_recent_questions: boolean };
export type AIResponse = MockTest & { selected_question_ids: number[] };
export type SubjectSubtopic = { subtopic_id: number; subtopic_name: string };
export type SubjectTopic = { topic_id: number; topic_name: string; subtopics: SubjectSubtopic[] };
export type SubjectTrack = { track_id: number; track_name: string; topics: SubjectTopic[] };
export type PlacoResponse = { conversation_id: number; message: string; mode: string; referenced_question_id?: number | null };
export type Metric = { accuracy?: number; questions_attempted?: number; questions_correct?: number; [key: string]: unknown };
