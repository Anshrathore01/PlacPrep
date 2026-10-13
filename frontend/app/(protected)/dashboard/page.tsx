"use client";
import { useEffect, useState } from "react";
import { Activity, Award, BrainCircuit, CheckCircle2, ChevronRight, Sparkles, Target } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { AnalyticsSummary } from "@/lib/types";
import { useAuth } from "@/components/providers";
import { MetricCard } from "@/components/metric-card";
import { Loading, ErrorState } from "@/components/loading";

export default function Dashboard() {
  const { user } = useAuth();
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    api.summary()
      .then((res) => {
        if (active) setData(res);
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

  return (
    <>
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-indigo-600">Your preparation hub</p>
          <h2 className="mt-2 text-3xl font-bold tracking-tight">
            Welcome back, {user?.display_name?.split(" ")[0] || "there"}.
          </h2>
          <p className="mt-2 text-slate-500">Small, consistent practice compounds into confidence.</p>
        </div>
        <Link
          href="/ai-mock"
          className="flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white hover:bg-indigo-700"
        >
          <Sparkles size={17} /> Build an AI mock
        </Link>
      </div>

      {error ? (
        <ErrorState message={error} retry={retry} />
      ) : loading || !data ? (
        <Loading label="Loading your dashboard…" />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="Average accuracy"
              value={`${Math.round(data.average_accuracy || 0)}%`}
              detail={`${data.questions_correct} correct answers`}
              icon={Target}
            />
            <MetricCard
              label="Questions solved"
              value={data.questions_attempted}
              detail={`${data.questions_skipped} skipped in submitted attempts`}
              icon={BrainCircuit}
              accent="green"
            />
            <MetricCard
              label="Completed mocks"
              value={data.completed_attempts}
              detail={`${data.total_attempts} attempts total`}
              icon={Award}
              accent="amber"
            />
            <MetricCard
              label="Coding progress"
              value={`${data.coding_problems_solved}/${data.coding_problems_attempted}`}
              detail={`${Math.round(data.coding_success_rate || 0)}% success rate`}
              icon={Activity}
            />
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-[1.35fr_.65fr]">
            <section className="card p-6">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="font-semibold">Topic performance</h3>
                  <p className="mt-1 text-sm text-slate-500">Where your recent practice is landing.</p>
                </div>
                <Link href="/analytics" className="text-sm font-semibold text-indigo-600">
                  View analytics
                </Link>
              </div>
              <div className="mt-6 space-y-5">
                {data.topics.slice(0, 5).map((topic) => (
                  <div key={topic.topic_id}>
                    <div className="mb-2 flex justify-between text-sm">
                      <span className="font-medium">{topic.topic_name}</span>
                      <span className="text-slate-500">{Math.round(topic.accuracy)}%</span>
                    </div>
                    <div className="h-2 rounded-full bg-slate-100">
                      <div
                        className="h-2 rounded-full bg-indigo-600"
                        style={{ width: `${Math.min(100, Math.max(0, topic.accuracy))}%` }}
                      />
                    </div>
                  </div>
                ))}
                {!data.topics.length && (
                  <p className="py-8 text-center text-sm text-slate-500">
                    Complete a few questions to see topic insights.
                  </p>
                )}
              </div>
            </section>

            <section className="card bg-indigo-600 p-6 text-white">
              <div className="flex h-full flex-col">
                <div className="grid h-11 w-11 place-items-center rounded-xl bg-white/15">
                  <CheckCircle2 />
                </div>
                <h3 className="mt-6 text-xl font-semibold">Your next best step</h3>
                <p className="mt-3 flex-1 text-sm leading-6 text-indigo-100">
                  Take a short mock to turn your current knowledge into a measurable baseline.
                </p>
                <Link
                  href="/mocks"
                  className="mt-6 flex items-center justify-between rounded-xl bg-white px-4 py-3 text-sm font-semibold text-indigo-700"
                >
                  Explore mocks <ChevronRight size={17} />
                </Link>
              </div>
            </section>
          </div>
        </>
      )}
    </>
  );
}
