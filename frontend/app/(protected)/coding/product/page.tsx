"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, ExternalLink, RotateCcw, Search } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { ProductDsaQuestion } from "@/lib/types";
import { completedQuestionCount, filterProductDsaQuestions } from "@/lib/product-dsa";
import { ErrorState, Loading } from "@/components/loading";

const EMPTY_FILTERS = { query: "", topic: "", difficulty: "", platform: "" };

export default function ProductCompanies() {
  const [questions, setQuestions] = useState<ProductDsaQuestion[] | null>(null);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true;
    api.productDsaQuestions()
      .then((data) => {
        if (active) {
          setQuestions(data.questions);
          setError("");
        }
      })
      .catch((cause) => {
        if (active) setError(cause instanceof ApiError ? cause.message : "Could not load the DSA question list.");
      });
    return () => { active = false; };
  }, [reload]);

  const topics = useMemo(
    () => [...new Set((questions ?? []).map((question) => question.topic))].sort((a, b) => a.localeCompare(b)),
    [questions],
  );
  const visibleQuestions = useMemo(
    () => filterProductDsaQuestions(questions ?? [], filters),
    [filters, questions],
  );
  const completed = completedQuestionCount(questions ?? []);
  const total = questions?.length ?? 200;
  const percentage = total ? Math.round((completed / total) * 100) : 0;

  const toggle = useCallback(async (question: ProductDsaQuestion) => {
    if (pendingIds.has(question.id)) return;
    const nextValue = !question.is_completed;
    setSaveError("");
    setPendingIds((current) => new Set(current).add(question.id));
    setQuestions((current) => current?.map((item) => item.id === question.id ? { ...item, is_completed: nextValue } : item) ?? null);
    try {
      await api.setCodingProblemSolved(question.id, nextValue);
    } catch (cause) {
      setQuestions((current) => current?.map((item) => item.id === question.id ? { ...item, is_completed: !nextValue } : item) ?? null);
      const reason = cause instanceof ApiError ? cause.message : "Could not save this completion.";
      setSaveError(`${reason} Your previous progress was restored.`);
    } finally {
      setPendingIds((current) => {
        const next = new Set(current);
        next.delete(question.id);
        return next;
      });
    }
  }, [pendingIds]);

  if (error && !questions) {
    return <ErrorState message={error} retry={() => { setError(""); setReload((value) => value + 1); }} />;
  }
  if (!questions) return <Loading label="Loading DSA questions…" />;

  return <>
    <Link href="/coding" className="mb-5 inline-flex items-center gap-2 text-sm font-medium text-slate-500 hover:text-indigo-600">
      <ArrowLeft size={16} /> Coding / DSA
    </Link>

    <div className="mb-6">
      <p className="text-sm font-medium text-indigo-600">Product-based placement practice</p>
      <h1 className="mt-2 text-3xl font-bold tracking-tight">Top 200 DSA Questions</h1>
      <p className="mt-2 text-slate-500">Practice the most important DSA problems for product-based company interviews.</p>
    </div>

    {saveError && <div role="alert" className="mb-4 flex items-start justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
      <span>{saveError}</span>
      <button type="button" onClick={() => setSaveError("")} className="shrink-0 font-semibold underline">Dismiss</button>
    </div>}

    <section aria-label="DSA progress" className="card mb-5 p-5">
      <div className="flex items-center justify-between gap-4">
        <div><p className="text-sm font-semibold text-slate-800">Your progress</p><p className="mt-1 text-sm text-slate-500">{completed} / {total} Completed</p></div>
        <span className="text-sm font-semibold tabular-nums text-indigo-700">{percentage}%</span>
      </div>
      <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-label="Questions completed" aria-valuemin={0} aria-valuemax={total} aria-valuenow={completed}>
        <div className="h-full rounded-full bg-indigo-600 transition-[width]" style={{ width: `${percentage}%` }} />
      </div>
    </section>

    <section aria-label="Search and filter DSA questions" className="card mb-5 p-4 sm:p-5">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-[minmax(220px,1.5fr)_repeat(3,minmax(150px,1fr))_auto]">
        <label className="relative block sm:col-span-2 xl:col-span-1">
          <span className="sr-only">Search by question name</span>
          <Search size={17} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input value={filters.query} onChange={(event) => setFilters((value) => ({ ...value, query: event.target.value }))} placeholder="Search questions…" className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-10 pr-3 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100" />
        </label>
        <FilterSelect label="Topic" value={filters.topic} options={topics} onChange={(topic) => setFilters((value) => ({ ...value, topic }))} />
        <FilterSelect label="Difficulty" value={filters.difficulty} options={["Easy", "Medium", "Hard"]} onChange={(difficulty) => setFilters((value) => ({ ...value, difficulty }))} />
        <FilterSelect label="Platform" value={filters.platform} options={["LeetCode", "GeeksforGeeks"]} onChange={(platform) => setFilters((value) => ({ ...value, platform }))} />
        <button type="button" onClick={() => setFilters(EMPTY_FILTERS)} disabled={!filters.query && !filters.topic && !filters.difficulty && !filters.platform} className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-45">
          <RotateCcw size={15} /> Reset
        </button>
      </div>
      <p className="mt-3 text-xs text-slate-500" aria-live="polite">Showing {visibleQuestions.length} of {total} questions</p>
    </section>

    <section className="card overflow-hidden" aria-label="Top 200 DSA question list">
      <div className="hidden grid-cols-[42px_1fr_190px_105px_155px] gap-4 border-b border-slate-100 bg-slate-50 px-5 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500 sm:grid">
        <span>Done</span><span>Question</span><span>Topic</span><span>Level</span><span>Platform</span>
      </div>
      {visibleQuestions.length ? <ol className="list-none divide-y divide-slate-100" aria-label="DSA questions">
        {visibleQuestions.map((question) => {
          const saving = pendingIds.has(question.id);
          return <li key={question.id} className={`grid grid-cols-[28px_1fr] items-center gap-x-3 gap-y-2 px-4 py-3.5 transition-colors sm:grid-cols-[42px_1fr_190px_105px_155px] sm:gap-4 sm:px-5 ${question.is_completed ? "bg-emerald-50/40" : "hover:bg-slate-50/70"}`}>
            <label className="flex h-8 items-center justify-center" title={question.is_completed ? "Mark as not completed" : "Mark as completed"}>
              <input type="checkbox" checked={question.is_completed} disabled={saving} onChange={() => void toggle(question)} aria-label={`${question.is_completed ? "Mark not completed" : "Mark completed"}: ${question.title}`} className="h-4 w-4 cursor-pointer rounded border-slate-300 accent-emerald-600 disabled:cursor-wait" />
            </label>
            <div className="min-w-0">
              <div className="flex min-w-0 items-baseline gap-2">
                <span className="shrink-0 text-xs tabular-nums text-slate-400">{question.question_number}.</span>
                <a href={question.url} target="_blank" rel="noopener noreferrer" className={`truncate text-sm font-medium hover:text-indigo-700 hover:underline ${question.is_completed ? "text-slate-500 line-through" : "text-slate-800"}`}>{question.title}</a>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 sm:hidden">
                <TopicLabel topic={question.topic} />
                <DifficultyBadge difficulty={question.difficulty} />
                <PlatformLink question={question} compact />
              </div>
            </div>
            <div className="hidden sm:block"><TopicLabel topic={question.topic} /></div>
            <div className="hidden sm:block"><DifficultyBadge difficulty={question.difficulty} /></div>
            <div className="hidden sm:block"><PlatformLink question={question} /></div>
          </li>;
        })}
      </ol> : <div className="px-5 py-12 text-center">
        <p className="font-medium text-slate-700">No questions match those filters.</p>
        <button type="button" onClick={() => setFilters(EMPTY_FILTERS)} className="mt-2 text-sm font-semibold text-indigo-600 hover:text-indigo-700">Clear filters</button>
      </div>}
    </section>
  </>;
}

function FilterSelect({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return <label className="block text-xs font-medium text-slate-500">
    {label}
    <select value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 block w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-700 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100">
        <option value="">{label === "Difficulty" ? "All difficulties" : `All ${label.toLowerCase()}s`}</option>
      {options.map((option) => <option value={option} key={option}>{option}</option>)}
    </select>
  </label>;
}

function TopicLabel({ topic }: { topic: string }) {
  return <span className="inline-flex max-w-full rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600">{topic}</span>;
}

function DifficultyBadge({ difficulty }: { difficulty: ProductDsaQuestion["difficulty"] }) {
  const styles = {
    Easy: "bg-emerald-50 text-emerald-700",
    Medium: "bg-amber-50 text-amber-700",
    Hard: "bg-rose-50 text-rose-700",
  };
  return <span className={`inline-flex rounded-md px-2 py-1 text-xs font-medium ${styles[difficulty]}`}>{difficulty}</span>;
}

function PlatformLink({ question, compact = false }: { question: ProductDsaQuestion; compact?: boolean }) {
  const leetcode = question.platform === "LeetCode";
  return <a href={question.url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${question.title} on ${question.platform}`} className="inline-flex min-h-7 items-center gap-1.5 text-xs font-medium text-slate-600 hover:text-indigo-700">
    <span aria-hidden="true" className={`grid h-5 w-5 place-items-center rounded-full text-[8px] font-black ${leetcode ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800"}`}>{leetcode ? "LC" : "GFG"}</span>
    {!compact && <span>{question.platform}</span>}
    <ExternalLink size={13} />
  </a>;
}
