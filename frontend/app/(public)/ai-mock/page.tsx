"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ShieldCheck, Sparkles } from "lucide-react";
import { Button } from "@/components/shell";
import { ApiError, api } from "@/lib/api";
import type { AIRequest } from "@/lib/types";
import { DurationSelector } from "@/components/duration-selector";

export default function AIMock() {
  const router = useRouter();
  const [mode, setMode] = useState<AIRequest["difficulty_mode"]>("EASY");
  const [count, setCount] = useState(10);
  const [type, setType] = useState<"MCQ" | "CODING">("MCQ");
  const [duration, setDuration] = useState(30);
  const [distribution, setDistribution] = useState({ EASY: 6, MEDIUM: 3, TOUGH: 1 });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const updateDist = (key: keyof typeof distribution, value: number) => {
    const next = { ...distribution, [key]: Math.max(0, value) };
    setDistribution(next);
    setCount(Object.values(next).reduce((sum, item) => sum + item, 0));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    if (!Number.isInteger(duration) || duration < 1 || duration > 480) { setError("Choose a duration from 1 to 480 minutes."); return; }
    setBusy(true);

    const body: AIRequest = {
      title: `AI ${mode.toLowerCase()} practice`,
      question_type: type,
      difficulty_mode: mode,
      total_questions: count,
      duration_seconds: duration * 60,
      exclude_recent_questions: true,
    };
    if (mode === "MIXED") body.difficulty_distribution = distribution;

    try {
      const result = await api.generateAI(body);
      router.push(`/mocks/${result.mock_test_id}`);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        const next = `${window.location.pathname}${window.location.search}`;
        router.push(`/login?next=${encodeURIComponent(next)}`);
      } else {
        setError(cause instanceof ApiError ? cause.message : "Mock generation failed. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-8">
        <div className="flex items-center gap-2 text-sm font-semibold text-indigo-600">
          <Sparkles size={17} /> AI-powered mock curation
        </div>
        <h2 className="mt-2 text-3xl font-bold">AI Mock Generator</h2>
        <p className="mt-2 max-w-2xl text-slate-500">
          Curate a balanced mock assessment using backend AI intelligence from the existing question bank.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <form onSubmit={submit} className="card p-6 md:p-8">
          <div className="grid gap-5 sm:grid-cols-2">
            <label className="text-sm font-semibold">
              Question type
              <select
                value={type}
                onChange={(event) => setType(event.target.value as "MCQ" | "CODING")}
                className="mt-2 w-full rounded-xl border border-slate-200 px-3 py-3 font-normal outline-none"
              >
                <option value="MCQ">Multiple choice</option>
                <option value="CODING">Coding</option>
              </select>
            </label>

            <label className="text-sm font-semibold">
              Difficulty
              <select
                value={mode}
                onChange={(event) => setMode(event.target.value as AIRequest["difficulty_mode"])}
                className="mt-2 w-full rounded-xl border border-slate-200 px-3 py-3 font-normal outline-none"
              >
                <option value="EASY">Easy</option>
                <option value="MEDIUM">Medium</option>
                <option value="TOUGH">Hard</option>
                <option value="MIXED">Mixed</option>
              </select>
            </label>

            <label className="text-sm font-semibold">
              Question count
              <input
                type="number"
                min={1}
                max={100}
                value={count}
                disabled={mode === "MIXED"}
                onChange={(event) => setCount(Number(event.target.value))}
                className="mt-2 w-full rounded-xl border border-slate-200 px-3 py-3 font-normal outline-none"
              />
            </label>

          </div>

          <DurationSelector value={duration} onChange={setDuration} />

          {mode === "MIXED" && (
            <div className="mt-6 rounded-xl bg-slate-50 p-4">
              <p className="text-sm font-semibold">
                Mixed distribution <span className="font-normal text-slate-500">({count} total)</span>
              </p>
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                {(["EASY", "MEDIUM", "TOUGH"] as const).map((key) => (
                  <label key={key} className="text-xs font-semibold text-slate-600">
                    {key}
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={distribution[key]}
                      onChange={(event) => updateDist(key, Number(event.target.value))}
                      className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
                    />
                  </label>
                ))}
              </div>
            </div>
          )}

          <div className="mt-7 flex items-start gap-3 rounded-xl border border-indigo-100 bg-indigo-50 p-4 text-sm text-indigo-800">
            <ShieldCheck className="mt-0.5 shrink-0" size={18} />
            <p>Questions are selected and validated by the backend from its existing question bank.</p>
          </div>

          {error && <p className="mt-5 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
          <Button disabled={busy} className="mt-7 w-full">
            {busy ? "Selecting questions from the bank…" : "Build my mock"}
          </Button>
        </form>

        <aside className="card h-fit bg-slate-950 p-6 text-white">
          <Sparkles className="text-indigo-300" />
          <h3 className="mt-5 text-xl font-semibold">Curator, Not Generator</h3>
          <p className="mt-3 text-sm leading-6 text-slate-300">
            The AI engine selects real, verified questions from our database based on balance, difficulty, and your recent history. It never invents fake questions.
          </p>
        </aside>
      </div>
    </div>
  );
}
