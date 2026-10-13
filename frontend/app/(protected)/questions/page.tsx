"use client";
import { useEffect, useState } from "react";
import { Search, SlidersHorizontal, ArrowRight, BookOpen } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { QuestionListItem } from "@/lib/types";
import { Badge } from "@/components/shell";
import { Loading, ErrorState } from "@/components/loading";

export default function Questions() {
  const [items, setItems] = useState<QuestionListItem[]>([]);
  const [type, setType] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    api.questions(`?limit=100${type ? `&question_type=${type}` : ""}`)
      .then((data) => {
        if (active) setItems(data);
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
  }, [type, reloadKey]);

  const retry = () => {
    setLoading(true);
    setError("");
    setReloadKey((k) => k + 1);
  };

  const filtered = items.filter((q) =>
    (q.title || "").toLowerCase().includes(query.toLowerCase())
  );

  return (
    <>
      <div className="mb-8">
        <p className="text-sm font-medium text-indigo-600">Practice library</p>
        <h2 className="mt-2 text-3xl font-bold">Sharpen the fundamentals</h2>
        <p className="mt-2 text-slate-500">Work through real questions and build reliable patterns.</p>
      </div>

      <div className="card mb-5 flex flex-wrap gap-3 p-4">
        <div className="relative min-w-[220px] flex-1">
          <Search className="absolute left-3 top-3 text-slate-400" size={17} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search questions…"
            className="w-full rounded-xl border border-slate-200 py-2.5 pl-10 pr-3 text-sm outline-none focus:border-indigo-500"
          />
        </div>
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <SlidersHorizontal size={16} />
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="rounded-xl border border-slate-200 px-3 py-2.5 outline-none"
          >
            <option value="">All types</option>
            <option value="MCQ">MCQ</option>
            <option value="CODING">Coding</option>
          </select>
        </div>
      </div>

      {error ? (
        <ErrorState message={error} retry={retry} />
      ) : loading ? (
        <Loading label="Loading practice questions…" />
      ) : filtered.length ? (
        <div className="grid gap-4 md:grid-cols-2">
          {filtered.map((q) => (
            <Link
              href={`/questions/${q.question_id}`}
              key={q.question_id}
              className="card group p-5 transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-indigo-50 text-indigo-600">
                  <BookOpen size={18} />
                </div>
                <Badge tone={q.difficulty === "HARD" ? "amber" : "indigo"}>
                  {q.difficulty || "Unrated"}
                </Badge>
              </div>
              <h3 className="mt-5 line-clamp-2 font-semibold leading-6 group-hover:text-indigo-700">
                {q.title || "Untitled question"}
              </h3>
              <div className="mt-5 flex items-center justify-between text-xs text-slate-500">
                <span>{q.question_type}</span>
                <span className="flex items-center gap-1 font-semibold text-indigo-600">
                  Open <ArrowRight size={14} />
                </span>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="card col-span-full p-12 text-center text-sm text-slate-500">
          No eligible questions match these filters.
        </div>
      )}
    </>
  );
}
