"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { MetricCard } from "@/components/metric-card";
import { Loading, ErrorState } from "@/components/loading";
import { Activity, BarChart3, BrainCircuit, Target } from "lucide-react";
import type { AnalyticsSummary } from "@/lib/types";

export default function Analytics() {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [topics, setTopics] = useState<Record<string, unknown>[]>([]);
  const [difficulty, setDifficulty] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    Promise.all([api.summary(), api.topics(), api.difficulty()])
      .then(([a, b, c]) => {
        if (active) {
          setSummary(a);
          setTopics(b);
          setDifficulty(c);
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
  }, [reloadKey]);

  const retry = () => {
    setLoading(true);
    setError("");
    setReloadKey((k) => k + 1);
  };

  if (error) return <ErrorState message={error} retry={retry} />;
  if (loading || !summary) return <Loading label="Loading analytics…" />;

  return (
    <>
      <div className="mb-8">
        <p className="text-sm font-medium text-indigo-600">Progress intelligence</p>
        <h2 className="mt-2 text-3xl font-bold">Analytics</h2>
        <p className="mt-2 text-slate-500">Understand your patterns and make the next session count.</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Score average"
          value={`${Math.round(summary.average_score_percentage || 0)}%`}
          detail={`${summary.completed_attempts} completed attempts`}
          icon={BarChart3}
        />
        <MetricCard
          label="Accuracy"
          value={`${Math.round(summary.average_accuracy || 0)}%`}
          detail={`${summary.questions_attempted} questions attempted`}
          icon={Target}
          accent="green"
        />
        <MetricCard
          label="Questions correct"
          value={summary.questions_correct}
          detail={`${summary.questions_skipped} skipped`}
          icon={BrainCircuit}
          accent="amber"
        />
        <MetricCard
          label="Coding success"
          value={`${Math.round(summary.coding_success_rate || 0)}%`}
          detail={`${summary.coding_problems_solved} solved`}
          icon={Activity}
        />
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <section className="card p-6">
          <h3 className="font-semibold">Topic accuracy</h3>
          <div className="mt-6 space-y-5">
            {topics.map((item, i) => {
              const accuracy = Number(item.accuracy || 0);
              return (
                <div key={String(item.topic_id || i)}>
                  <div className="mb-2 flex justify-between text-sm">
                    <span>{String(item.topic_name || "Topic")}</span>
                    <span className="font-semibold">{Math.round(accuracy)}%</span>
                  </div>
                  <div className="h-2 rounded-full bg-slate-100">
                    <div
                      className="h-2 rounded-full bg-indigo-600"
                      style={{ width: `${Math.min(100, accuracy)}%` }}
                    />
                  </div>
                </div>
              );
            })}
            {!topics.length && <p className="text-sm text-slate-500">No topic data is available yet.</p>}
          </div>
        </section>
        <section className="card p-6">
          <h3 className="font-semibold">Difficulty comparison</h3>
          <div className="mt-6 space-y-4">
            {difficulty.map((item, i) => (
              <div
                key={String(item.difficulty || i)}
                className="flex items-center justify-between rounded-xl bg-slate-50 p-4"
              >
                <div>
                  <p className="font-semibold">{String(item.difficulty || "Unrated")}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {String(item.questions_attempted || 0)} attempted
                  </p>
                </div>
                <p className="text-xl font-bold text-indigo-600">
                  {Math.round(Number(item.accuracy || 0))}%
                </p>
              </div>
            ))}
            {!difficulty.length && (
              <p className="text-sm text-slate-500">
                Complete questions across difficulties to compare performance.
              </p>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
