"use client";

import { useEffect, useState, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Attempt } from "@/lib/types";
import { Badge, Button } from "@/components/shell";
import { Loading, ErrorState } from "@/components/loading";
import { isTcsFullLength, MathText, TcsQuestionPrompt } from "@/components/tcs-question-content";
import { usePlaco } from "@/components/providers";
import { answerOptionReviewState } from "@/lib/result-review";
import {
  Award,
  CheckCircle2,
  Clock,
  HelpCircle,
  MessageCircle,
  RotateCcw,
  Target,
  XCircle,
} from "lucide-react";

export default function ResultPage() {
  const searchParams = useSearchParams();
  const attemptParam = searchParams.get("attempt");
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const { openPanel } = usePlaco();

  useEffect(() => {
    let active = true;
    if (!attemptParam) {
      return () => {
        active = false;
      };
    }

    api.attempt(Number(attemptParam))
      .then((data) => {
        if (active) setAttempt(data);
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
  }, [attemptParam, reloadKey]);

  const retry = () => {
    setLoading(true);
    setError("");
    setReloadKey((k) => k + 1);
  };

  const questions = useMemo(() => attempt?.questions || [], [attempt]);

  const stats = useMemo(() => {
    let correct = 0;
    let incorrect = 0;
    let skipped = 0;
    let unavailable = 0;

    for (const q of questions) {
      if (!q.selected_option_key && !q.answer_text) {
        skipped++;
      } else if (!q.answer_key_available) {
        unavailable++;
      } else if (q.is_correct === true) {
        correct++;
      } else if (q.is_correct === false) {
        incorrect++;
      } else {
        // Fallback if is_correct is not defined
        skipped++;
      }
    }

    return { correct, incorrect, skipped, unavailable };
  }, [questions]);

  // Breakdown by difficulty
  const difficultyBreakdown = useMemo(() => {
    const map = new Map<string, { total: number; correct: number }>();
    for (const q of questions) {
      const diff = q.difficulty || "Standard";
      const current = map.get(diff) || { total: 0, correct: 0 };
      current.total++;
      if (q.is_correct) current.correct++;
      map.set(diff, current);
    }
    return Array.from(map.entries()).map(([diff, data]) => ({
      difficulty: diff,
      total: data.total,
      correct: data.correct,
      pct: data.total ? Math.round((data.correct / data.total) * 100) : 0,
    }));
  }, [questions]);

  if (!attemptParam) {
    return <ErrorState message="No attempt ID was provided in the URL." />;
  }

  if (error && !attempt) return <ErrorState message={error} retry={retry} />;
  if (loading || !attempt) return <Loading label="Loading results…" />;

  const pct = attempt.max_score
    ? Math.round(((attempt.score || 0) / attempt.max_score) * 100)
    : 0;

  const timeMinutes = attempt.time_spent_seconds
    ? Math.floor(attempt.time_spent_seconds / 60)
    : 0;
  const timeSeconds = attempt.time_spent_seconds
    ? attempt.time_spent_seconds % 60
    : 0;

  return (
    <div className="mx-auto max-w-5xl space-y-8 pb-12">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-slate-200 pb-6">
        <div>
          <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-700">
            Assessment Completed
          </span>
          <h1 className="mt-3 text-3xl font-bold tracking-tight text-slate-900">
            {attempt.mock_test?.title || "Mock Assessment"} Results
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Completed on {attempt.submitted_at ? new Date(attempt.submitted_at).toLocaleDateString() : "Today"}
          </p>
        </div>

        <div className="flex gap-3">
          <Link
            href="/mocks"
            className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 shadow-sm"
          >
            <RotateCcw size={16} /> Take another mock
          </Link>
          <Link
            href="/analytics"
            className="flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 shadow-sm"
          >
            View analytics
          </Link>
        </div>
      </div>

      {/* Primary Metrics Grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* Score & Percentage */}
        <div className="card bg-gradient-to-br from-indigo-600 to-indigo-700 p-6 text-white shadow-md">
          <div className="flex items-center justify-between text-indigo-100">
            <span className="text-sm font-medium">Final Score</span>
            <Award size={20} />
          </div>
          <p className="mt-3 text-4xl font-extrabold tracking-tight">{pct}%</p>
          <p className="mt-1 text-xs text-indigo-100">
            {attempt.score ?? 0} out of {attempt.max_score ?? 0} points
          </p>
        </div>

        {/* Accuracy */}
        <div className="card p-6">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-sm font-medium text-slate-500">Accuracy</span>
            <Target size={20} className="text-indigo-600" />
          </div>
          <p className="mt-3 text-3xl font-bold text-slate-900">
            {attempt.accuracy != null ? `${Math.round(attempt.accuracy * 100)}%` : `${pct}%`}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {stats.correct} correct of {questions.length} questions
          </p>
        </div>

        {/* Question Performance Breakdown */}
        <div className="card p-6">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-sm font-medium text-slate-500">Answers</span>
            <CheckCircle2 size={20} className="text-emerald-500" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-emerald-600">{stats.correct}</span>
            <span className="text-xs text-slate-400">correct</span>
            <span className="text-2xl font-bold text-red-500 ml-1">{stats.incorrect}</span>
            <span className="text-xs text-slate-400">incorrect</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {stats.skipped} not answered · {stats.unavailable} answer keys unavailable
          </p>
        </div>

        {/* Time Spent */}
        <div className="card p-6">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-sm font-medium text-slate-500">Time Spent</span>
            <Clock size={20} className="text-slate-600" />
          </div>
          <p className="mt-3 text-3xl font-bold text-slate-900">
            {timeMinutes}m {timeSeconds}s
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Server recorded time
          </p>
        </div>
      </div>

      {/* Difficulty Breakdown (if available) */}
      {difficultyBreakdown.length > 0 && (
        <section className="card p-6">
          <h2 className="text-base font-bold text-slate-900">Performance by Difficulty</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            {difficultyBreakdown.map((item) => (
              <div key={item.difficulty} className="rounded-xl border border-slate-100 bg-slate-50/60 p-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-slate-900">{item.difficulty}</span>
                  <span className="text-sm font-bold text-indigo-600">{item.pct}%</span>
                </div>
                <div className="mt-3 h-2 rounded-full bg-slate-200">
                  <div
                    className="h-2 rounded-full bg-indigo-600 transition-all"
                    style={{ width: `${item.pct}%` }}
                  />
                </div>
                <p className="mt-2 text-xs text-slate-500">
                  {item.correct} / {item.total} correct
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Question-by-Question Review */}
      <section className="card p-6 md:p-8">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-4">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Question Review</h2>
            <p className="mt-1 text-xs text-slate-500">
              Review your answers and ask Placo for deep concept explanations.
            </p>
          </div>
          <Badge tone="slate">{questions.length} questions</Badge>
        </div>

        <div className="mt-6 space-y-6 divide-y divide-slate-100">
          {questions.map((q, idx) => {
            const isCorrect = q.is_correct === true;
            const hasResponse = Boolean(q.selected_option_key || q.answer_text);
            const isIncorrect = q.is_correct === false && hasResponse && q.answer_key_available === true;

            return (
              <div key={q.question_id} className={idx > 0 ? "pt-6" : ""}>
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <span className="grid h-7 w-7 place-items-center rounded-lg bg-slate-100 text-xs font-bold text-slate-700">
                      {idx + 1}
                    </span>
                    {isCorrect ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                        <CheckCircle2 size={14} /> Correct (+{q.points} pt)
                      </span>
                    ) : isIncorrect ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2.5 py-1 text-xs font-semibold text-red-700">
                        <XCircle size={14} /> Incorrect (0 pt)
                      </span>
                    ) : q.selected_option_key || q.answer_text ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800">
                        <HelpCircle size={14} /> Answer key unavailable
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
                        <HelpCircle size={14} /> Not answered
                      </span>
                    )}
                    {q.section && (
                      <Badge tone="indigo" className="text-[10px]">
                        {q.section}
                      </Badge>
                    )}
                    <span className="text-xs font-medium text-slate-400">
                      {q.difficulty || "Standard"}
                    </span>
                  </div>

                  <Button
                    variant="ghost"
                    onClick={() =>
                      openPanel({
                        questionId: q.question_id,
                        attemptId: attempt.attempt_id,
                        mode: "RESULT",
                        request: "Explain why the correct answer is correct for this question. Explain why my answer is wrong if applicable. If the trusted answer key is unavailable, say so rather than guessing.",
                      })
                    }
                    className="text-xs py-1.5 px-3 text-indigo-700 hover:bg-indigo-50"
                  >
                    <MessageCircle size={14} className="mr-1.5 inline" /> Explain with Placo
                  </Button>
                </div>

                {/* Reading Comprehension Passage */}
                {q.passage && (
                  <div className="mt-4 rounded-xl border border-sky-200 bg-sky-50/50 p-4 text-xs leading-relaxed text-slate-800">
                    <div className="mb-2 inline-flex items-center gap-1.5 rounded-md bg-sky-100 px-2 py-0.5 font-bold uppercase tracking-wider text-sky-800 text-[10px]">
                      Reading Comprehension Passage
                    </div>
                    <div className="whitespace-pre-wrap font-serif text-slate-800 leading-relaxed">
                      {isTcsFullLength(q.title) ? <MathText text={q.passage} /> : q.passage}
                    </div>
                  </div>
                )}

                {isTcsFullLength(q.title) ? (
                  <TcsQuestionPrompt number={idx + 1} text={q.question_text || q.problem_statement || ""} className="mt-4" />
                ) : (
                  <div className="mt-4 whitespace-pre-wrap break-words text-sm font-semibold leading-relaxed text-slate-900">
                    {q.question_text || q.problem_statement}
                  </div>
                )}

                {/* Display MCQ Options and Student Choice */}
                {q.options && q.options.length > 0 && (
                  <div className="mt-4 grid gap-2 sm:grid-cols-2">
                    {q.options.map((opt) => {
                      const wasSelected = q.selected_option_key === opt.option_key;
                      const hasAnswerKey = q.answer_key_available === true;
                      const optionState = answerOptionReviewState(opt.option_key, q.selected_option_key, q.correct_option_key, hasAnswerKey);
                      return (
                        <div
                          key={opt.option_key}
                          className={`flex items-start gap-3 rounded-xl border p-3 text-xs ${
                            optionState === "correct"
                              ? "border-emerald-500 bg-emerald-50/70 text-emerald-950 font-semibold"
                              : optionState === "incorrect"
                                ? "border-red-400 bg-red-50/70 text-red-950 font-semibold"
                                : "border-slate-100 bg-slate-50/50 text-slate-700"
                          }`}
                        >
                          <span
                            className={`grid h-6 w-6 shrink-0 place-items-center rounded font-bold ${
                              optionState === "correct"
                                ? "bg-emerald-600 text-white"
                                : optionState === "incorrect"
                                  ? "bg-red-600 text-white"
                                  : "bg-slate-200 text-slate-700"
                            }`}
                          >
                            {opt.label}
                          </span>
                          <span className="min-w-0 flex-1 whitespace-pre-wrap break-words leading-5">
                            {isTcsFullLength(q.title) ? <MathText text={opt.text} /> : opt.text}
                          </span>
                          <span className="flex flex-col items-end text-right text-[10px] font-bold uppercase tracking-wider">
                            {wasSelected && <span>{hasAnswerKey ? "Your answer" : "Your answer · key unavailable"}</span>}
                            {optionState === "correct" && <span className="text-emerald-800">Correct answer</span>}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
                {q.question_type === "MCQ" && !q.options?.length && (
                  <div className="mt-3 space-y-1 text-sm">
                    {q.answer_text ? <p className="text-slate-600">Your answer: <strong>{q.answer_text}</strong></p> : <p className="text-slate-600">Not answered</p>}
                    {q.answer_key_available && q.correct_option_key ? <p className="font-semibold text-emerald-800">Correct answer: {q.correct_option_key}</p> : <p className="text-amber-800">Correct answer unavailable in the source data.</p>}
                  </div>
                )}
                {q.question_type === "MCQ" && Boolean(q.options?.length) && !q.answer_key_available && (
                  <p className="mt-2 text-xs font-medium text-amber-800">The correct answer is unavailable in the source data.</p>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
