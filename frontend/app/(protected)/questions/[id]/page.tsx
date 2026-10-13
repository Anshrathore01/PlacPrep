"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import type { Question } from "@/lib/types";
import { Loading, ErrorState } from "@/components/loading";
import { Badge, Button } from "@/components/shell";
import { usePlaco } from "@/components/providers";
import { isTcsFullLength, MathText, TcsQuestionPrompt } from "@/components/tcs-question-content";

export default function QuestionPage() {
  const { id } = useParams<{ id: string }>();
  const [question, setQuestion] = useState<Question | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { openPanel } = usePlaco();

  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    api.question(Number(id))
      .then((data) => {
        if (active) setQuestion(data);
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
  }, [id, reloadKey]);

  const retry = () => {
    setLoading(true);
    setError("");
    setReloadKey((k) => k + 1);
  };

  if (error) return <ErrorState message={error} retry={retry} />;
  if (loading || !question) return <Loading label="Loading question…" />;

  return (
    <article className="mx-auto max-w-4xl">
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge>{question.question_type}</Badge>
          {question.section && <Badge tone="indigo">{question.section}</Badge>}
          <Badge tone="amber">{question.difficulty || "Unrated"}</Badge>
        </div>
        <Button
          variant="secondary"
          onClick={() => openPanel({ questionId: question.question_id, mode: "PRACTICE" })}
        >
          Ask Placo
        </Button>
      </div>

      <div className="card p-6 md:p-10">
        {!isTcsFullLength(question.title) && (
          <h2 className="text-2xl font-bold leading-9">{question.title}</h2>
        )}
        {question.passage && (
          <div className="mt-6 rounded-2xl border border-sky-200 bg-sky-50/60 p-6 text-sm text-slate-800 shadow-sm">
            <div className="mb-3 inline-flex items-center gap-2 rounded-md bg-sky-100 px-2.5 py-1 text-xs font-bold uppercase tracking-wider text-sky-800">
              Reading Comprehension Passage
            </div>
            <div className="whitespace-pre-wrap font-serif text-sm leading-relaxed text-slate-800">
              {isTcsFullLength(question.title) ? <MathText text={question.passage} /> : question.passage}
            </div>
          </div>
        )}
        {isTcsFullLength(question.title) ? (
          <TcsQuestionPrompt
            number={question.title?.match(/– Q(\d+)$/)?.[1] || 1}
            text={question.question_text || question.problem_statement || ""}
            className="mt-8"
          />
        ) : (
          <div className="prose prose-slate mt-8 max-w-none whitespace-pre-wrap leading-8">
            {question.question_text || question.problem_statement}
          </div>
        )}
        {question.options && (
          <div className="mt-8 space-y-3">
            {question.options.map((option) => (
              <button
                key={option.option_key}
                className="focus-ring flex w-full items-start gap-4 rounded-xl border border-slate-200 p-4 text-left hover:border-indigo-300 hover:bg-indigo-50"
              >
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-slate-100 text-sm font-bold">
                  {option.label}
                </span>
                <span className="min-w-0 flex-1 whitespace-pre-wrap break-words text-sm leading-6">
                  {isTcsFullLength(question.title) ? <MathText text={option.text} /> : option.text}
                </span>
              </button>
            ))}
          </div>
        )}
        {question.examples && (
          <div className="mt-8">
            <h3 className="font-semibold">Examples</h3>
            <pre className="mt-3 overflow-auto rounded-xl bg-slate-950 p-4 text-sm text-slate-200">
              {JSON.stringify(question.examples, null, 2)}
            </pre>
          </div>
        )}
      </div>
      <p className="mt-4 text-xs text-slate-400">
        Answers and explanations are server-authoritative and are shown only where the backend permits.
      </p>
    </article>
  );
}
