"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Attempt } from "@/lib/types";
import { Button } from "@/components/shell";
import { Loading, ErrorState } from "@/components/loading";
import { isTcsFullLength, MathText, TcsQuestionPrompt } from "@/components/tcs-question-content";
import { usePlaco } from "@/components/providers";
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  FastForward,
  MessageCircle,
  Send,
  AlertTriangle,
} from "lucide-react";

export default function AttemptPage() {
  const { id: mockId, attemptId } = useParams<{ id: string; attemptId: string }>();
  const router = useRouter();
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<Record<number, string>>({});
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [timeLeft, setTimeLeft] = useState<number | null>(null);
  const { openPanel } = usePlaco();

  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    api.attempt(Number(attemptId))
      .then((data) => {
        if (!active) return;
        setAttempt(data);
        const answers: Record<number, string> = {};
        for (const q of data.questions || []) {
          if (q.selected_option_key) {
            answers[q.question_id] = q.selected_option_key;
          } else if (q.answer_text) {
            answers[q.question_id] = q.answer_text;
          }
        }
        setSelected(answers);

        // If attempt is already submitted or expired, navigate to results
        if (data.status === "SUBMITTED" || data.status === "EXPIRED") {
          router.replace(`/mocks/${mockId}/result?attempt=${attemptId}`);
          return;
        }

        // Initialize timer from expires_at if present
        if (data.expires_at) {
          const expireTime = new Date(data.expires_at).getTime();
          const remainingSeconds = Math.max(0, Math.floor((expireTime - Date.now()) / 1000));
          setTimeLeft(remainingSeconds);
        } else if (data.mock_test?.duration_seconds) {
          setTimeLeft(data.mock_test.duration_seconds);
        }
      })
      .catch((e: Error) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [attemptId, mockId, reloadKey, router]);

  // Submit attempt handler
  const submit = useCallback(async (autoExpired = false) => {
    if (!attempt || submitting) return;
    if (!autoExpired && !confirm("Are you sure you want to submit this assessment? You cannot resume it afterward.")) {
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const result = await api.submitAttempt(attempt.attempt_id);
      router.push(`/mocks/${mockId}/result?attempt=${result.attempt_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to submit assessment.");
      setSubmitting(false);
    }
  }, [attempt, submitting, mockId, router]);

  // Countdown timer tick
  useEffect(() => {
    if (timeLeft === null || timeLeft <= 0) return;

    const timer = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev === null || prev <= 1) {
          clearInterval(timer);
          // Auto submit on expiry
          void submit(true);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [timeLeft, submit]);

  const retry = () => {
    setLoading(true);
    setError("");
    setReloadKey((k) => k + 1);
  };

  const questions = attempt?.questions || [];
  const question = questions[index];
  const totalQuestions = questions.length;

  const choose = async (key: string) => {
    if (!attempt || !question) return;
    setSelected((prev) => ({ ...prev, [question.question_id]: key }));
    setSaving(true);
    setError("");
    try {
      await api.saveAnswer(attempt.attempt_id, {
        question_id: question.question_id,
        selected_option_key: key,
        time_spent_seconds: 0,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Answer could not be saved.");
    } finally {
      setSaving(false);
    }
  };

  const chooseText = async (textVal: string) => {
    if (!attempt || !question) return;
    setSelected((prev) => ({ ...prev, [question.question_id]: textVal }));
    setSaving(true);
    setError("");
    try {
      await api.saveAnswer(attempt.attempt_id, {
        question_id: question.question_id,
        answer_text: textVal,
        time_spent_seconds: 0,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Answer could not be saved.");
    } finally {
      setSaving(false);
    }
  };

  // Skip question: move to next without setting an answer
  const handleSkip = () => {
    if (index < totalQuestions - 1) {
      setIndex((i) => i + 1);
    }
  };

  const formatTimer = (seconds: number) => {
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    if (hrs > 0) {
      return `${hrs}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
    }
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  if (error && !attempt) return <ErrorState message={error} retry={retry} />;
  if (loading || !attempt || !question) return <Loading label="Preparing your assessment…" />;

  const isLowTime = timeLeft !== null && timeLeft <= 300; // Under 5 mins

  return (
    <div className="mx-auto max-w-6xl pb-12">
      {/* Assessment Header */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            {attempt.mock_test?.title || "Active Mock Test"}
          </p>
          <h2 className="mt-1 text-xl font-bold text-slate-900">
            Question {index + 1} <span className="text-sm font-normal text-slate-500">of {totalQuestions}</span>
          </h2>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Server-authoritative Timer */}
          {timeLeft !== null && (
            <div
              className={`flex items-center gap-2 rounded-xl px-4 py-2 font-mono text-sm font-bold shadow-sm transition ${
                isLowTime
                  ? "bg-red-50 text-red-700 ring-1 ring-red-200 animate-pulse"
                  : "bg-slate-900 text-white"
              }`}
            >
              <Clock size={16} className={isLowTime ? "text-red-600" : "text-slate-300"} />
              <span>{formatTimer(timeLeft)}</span>
            </div>
          )}

          <Button
            variant="secondary"
            onClick={() =>
              openPanel({
                questionId: question.question_id,
                attemptId: attempt.attempt_id,
                mode: "ACTIVE_ASSESSMENT",
              })
            }
          >
            <MessageCircle size={16} className="mr-2 inline text-indigo-600" />
            Ask Placo
          </Button>

          <Button
            variant="primary"
            onClick={() => submit(false)}
            disabled={submitting}
            className="bg-emerald-600 hover:bg-emerald-700"
          >
            <Send size={15} className="mr-2 inline" />
            {submitting ? "Submitting…" : "Submit"}
          </Button>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_280px]">
        {/* Main Question Card */}
        <main className="card p-6 md:p-10 flex flex-col justify-between">
          <div>
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-4">
              <div className="flex flex-wrap items-center gap-2">
                {question.section && (
                  <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-bold text-slate-700">
                    {question.section}
                  </span>
                )}
                <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-700">
                  {question.difficulty || "Question"} · {question.points ?? 1} pt
                </span>
              </div>
              <span className="text-xs font-medium text-slate-400">
                {saving ? "Saving answer…" : "Answers save automatically"}
              </span>
            </div>

            {/* Reading Comprehension Passage */}
            {question.passage && (
              <div className="mt-6 rounded-2xl border border-indigo-100 bg-indigo-50/50 p-6 shadow-sm">
                <div className="mb-3 flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full bg-indigo-600" />
                  <h3 className="text-xs font-bold uppercase tracking-wider text-indigo-800">
                    Reading Comprehension Passage
                  </h3>
                </div>
                <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800 font-normal">
                  {isTcsFullLength(question.title) ? <MathText text={question.passage} /> : question.passage}
                </div>
              </div>
            )}

            {/* Question Text */}
            {isTcsFullLength(question.title) ? (
              <TcsQuestionPrompt number={index + 1} text={question.question_text || question.problem_statement || ""} className="mt-6" />
            ) : (
              <div className="mt-6 text-base font-semibold leading-relaxed text-slate-900 sm:text-lg whitespace-pre-wrap">
                {question.question_text || question.problem_statement}
              </div>
            )}

            {/* MCQ Options */}
            {question.options && question.options.length > 0 ? (
              <div className="mt-8 space-y-3">
                {question.options.map((option) => {
                  const isSelected = selected[question.question_id] === option.option_key;
                  return (
                    <button
                      key={option.option_key}
                      onClick={() => choose(option.option_key)}
                      className={`focus-ring flex w-full items-start gap-4 rounded-xl border p-4 text-left transition ${
                        isSelected
                          ? "border-indigo-600 bg-indigo-50/70 shadow-sm ring-1 ring-indigo-600/20"
                          : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50/60"
                      }`}
                    >
                      <span
                        className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg text-sm font-bold transition ${
                          isSelected
                            ? "bg-indigo-600 text-white"
                            : "bg-slate-100 text-slate-700"
                        }`}
                      >
                        {option.label}
                      </span>
                      <span className={`min-w-0 flex-1 whitespace-pre-wrap break-words text-sm leading-6 ${isSelected ? "font-semibold text-indigo-950" : "text-slate-800"}`}>
                        {isTcsFullLength(question.title) ? <MathText text={option.text} /> : option.text}
                      </span>
                      {isSelected && (
                        <CheckCircle2 className="ml-auto text-indigo-600 shrink-0" size={18} />
                      )}
                    </button>
                  );
                })}
              </div>
            ) : question.question_type === "CODING" ? (
              <div className="mt-8 space-y-6">
                {question.constraints_text && (
                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500">Constraints</h4>
                    <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700 font-mono">{question.constraints_text}</p>
                  </div>
                )}
                {(question.input_format || question.output_format) && (
                  <div className="grid gap-4 sm:grid-cols-2">
                    {question.input_format && (
                      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                        <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500">Input Format</h4>
                        <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{question.input_format}</p>
                      </div>
                    )}
                    {question.output_format && (
                      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                        <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500">Output Format</h4>
                        <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{question.output_format}</p>
                      </div>
                    )}
                  </div>
                )}
                {question.examples && question.examples.length > 0 && (
                  <div className="space-y-3">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500">Examples</h4>
                    {question.examples.map((ex, i: number) => (
                      <div key={i} className="rounded-xl border border-slate-200 bg-slate-900 p-4 text-xs font-mono text-slate-200">
                        <div className="font-bold text-indigo-300 mb-2">Example {ex.example_number || i + 1}</div>
                        {ex.input_data && <div><span className="text-slate-400">Input:</span> {ex.input_data}</div>}
                        {ex.output_data && <div><span className="text-slate-400">Output:</span> {ex.output_data}</div>}
                        {ex.explanation && <div className="mt-1 text-slate-400">Explanation: {ex.explanation}</div>}
                      </div>
                    ))}
                  </div>
                )}
                {question.starter_code && (
                  <div className="rounded-xl border border-slate-200 bg-slate-950 p-4 text-xs font-mono text-slate-100">
                    <div className="mb-2 font-bold text-slate-400 uppercase tracking-wider">Solution / Reference Code</div>
                    <pre className="overflow-x-auto whitespace-pre-wrap leading-5">{question.starter_code}</pre>
                  </div>
                )}
              </div>
            ) : (
              <div className="mt-8 rounded-xl border border-slate-200 bg-slate-50/70 p-5">
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-600">
                  Type your answer (Numerical / Text Answer)
                </label>
                <div className="mt-3 flex gap-3">
                  <input
                    type="text"
                    value={selected[question.question_id] || ""}
                    onChange={(e) => {
                      const val = e.target.value;
                      setSelected((prev) => ({ ...prev, [question.question_id]: val }));
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        void chooseText(selected[question.question_id] || "");
                      }
                    }}
                    placeholder="Enter your numerical or text answer here..."
                    className="flex-1 rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-900 shadow-sm focus:border-indigo-600 focus:outline-none focus:ring-1 focus:ring-indigo-600"
                  />
                  <Button
                    variant="primary"
                    onClick={() => void chooseText(selected[question.question_id] || "")}
                  >
                    Save Answer
                  </Button>
                </div>
              </div>
            )}
          </div>

          {/* Navigation Controls: Previous, Skip, Next */}
          <div className="mt-10 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-6">
            <Button
              variant="secondary"
              disabled={index === 0}
              onClick={() => setIndex((i) => i - 1)}
            >
              <ChevronLeft size={16} className="mr-1 inline" />
              Previous
            </Button>

            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                onClick={handleSkip}
                disabled={index === totalQuestions - 1}
                title="Skip to next question"
              >
                <FastForward size={15} className="mr-1.5 inline text-slate-500" />
                Skip
              </Button>

              {index < totalQuestions - 1 ? (
                <Button onClick={() => setIndex((i) => i + 1)}>
                  Next
                  <ChevronRight size={16} className="ml-1 inline" />
                </Button>
              ) : (
                <Button onClick={() => submit(false)} disabled={submitting}>
                  <Send size={15} className="mr-1.5 inline" />
                  {submitting ? "Submitting…" : "Finish & Submit"}
                </Button>
              )}
            </div>
          </div>
        </main>

        {/* Question Navigator Sidebar */}
        <aside className="space-y-4">
          <div className="card p-5">
            <h3 className="text-sm font-bold text-slate-900">Question Navigator</h3>
            <p className="mt-1 text-xs text-slate-500">
              Jump between questions anytime.
            </p>

            <div className="mt-4 grid grid-cols-5 gap-2">
              {questions.map((q, i) => {
                const isCurrent = i === index;
                const isAnswered = Boolean(selected[q.question_id]);
                return (
                  <button
                    key={q.question_id}
                    onClick={() => setIndex(i)}
                    className={`h-9 rounded-lg text-xs font-bold transition ${
                      isCurrent
                        ? "bg-indigo-600 text-white shadow-sm ring-2 ring-indigo-300"
                        : isAnswered
                        ? "bg-emerald-100 text-emerald-800 hover:bg-emerald-200"
                        : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                    }`}
                  >
                    {i + 1}
                  </button>
                );
              })}
            </div>

            <div className="mt-5 space-y-2 border-t border-slate-100 pt-4 text-xs text-slate-500">
              <div className="flex items-center gap-2">
                <span className="h-3 w-3 rounded bg-emerald-100 border border-emerald-300" />
                <span>Answered ({Object.keys(selected).length})</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="h-3 w-3 rounded bg-slate-100 border border-slate-300" />
                <span>Unanswered ({totalQuestions - Object.keys(selected).length})</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="h-3 w-3 rounded bg-indigo-600" />
                <span>Current Question</span>
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs leading-5 text-slate-500">
            Timer and scoring are managed strictly server-side. Refreshing preserves your saved answers.
          </div>
        </aside>
      </div>

      {error && (
        <div className="mt-5 flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          <AlertTriangle size={18} className="shrink-0" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}
