"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { SubjectTrack } from "@/lib/types";
import { Button } from "@/components/shell";
import { ErrorState, Loading } from "@/components/loading";

const quickCounts = [5, 10, 15, 20];
const quickDurations = [15, 30, 45, 60];

function displaySubjectName(topicName: string) {
  return topicName.toLowerCase() === "database management" ? "DBMS" : topicName;
}

export default function SubjectMockConfigPage() {
  const router = useRouter();
  const params = useParams<{ topicId: string }>();
  const searchParams = useSearchParams();

  const [tracks, setTracks] = useState<SubjectTrack[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [difficulty, setDifficulty] = useState<"EASY" | "MEDIUM" | "HARD" | "MIXED">("MEDIUM");
  const [count, setCount] = useState(10);
  const [durationMinutes, setDurationMinutes] = useState(30);
  const [subtopicId, setSubtopicId] = useState<number | "all">("all");
  const [distribution, setDistribution] = useState({ EASY: 5, MEDIUM: 3, TOUGH: 2 });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;

    api
      .taxonomy()
      .then((data) => {
        if (active) setTracks(data);
      })
      .catch((e: Error) => {
        if (active) setError(e.message || "Unable to load subject details.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const trackIdFromQuery = Number(searchParams.get("trackId") ?? "");

  const topicId = Number(params.topicId);
  let topic: (SubjectTrack["topics"][number] & { track_id: number; track_name: string }) | null = null;
  for (const track of tracks) {
    const match = track.topics.find((item) => item.topic_id === topicId);
    if (match) {
      topic = { ...match, track_id: track.track_id, track_name: track.track_name };
      break;
    }
  }

  const range = topic?.subtopics ?? [];

  const updateDistribution = (key: keyof typeof distribution, value: number) => {
    const next = { ...distribution, [key]: Math.max(0, value) };
    setDistribution(next);
    setCount(Object.values(next).reduce((sum, item) => sum + item, 0));
  };

  const submit = async () => {
    if (!topic) return;

    setBusy(true);
    setError("");

    try {
      const mappedDifficulty =
        difficulty === "MIXED"
          ? undefined
          : difficulty;

      const body = {
        title: `${displaySubjectName(topic.topic_name)} Mock`,
        question_type: "MCQ",
        track_id: trackIdFromQuery || topic.track_id,
        topic_id: topic.topic_id,
        subtopic_id: subtopicId === "all" ? undefined : subtopicId,
        difficulty: mappedDifficulty,
        total_questions: count,
        duration_seconds: durationMinutes * 60,
        mode: "MOCK",
      };

      const result = await api.createMock(body);
      router.push(`/mocks/${result.mock_test_id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        const next = `${window.location.pathname}${window.location.search}`;
        router.push(`/login?next=${encodeURIComponent(next)}`);
      } else if (e instanceof ApiError && e.status === 409) {
        if (difficulty === "HARD") {
          setError("Not enough eligible Hard questions are currently available for this mock.");
        } else {
          setError("Not enough eligible questions are currently available for this mock configuration.");
        }
      } else {
        setError(e instanceof ApiError ? e.message : "Unable to create this mock right now.");
      }
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <Loading label="Loading mock configuration…" />;
  if (error && !topic) return <ErrorState message={error} retry={() => window.location.reload()} />;

  if (!topic) {
    return (
      <div className="mx-auto max-w-xl">
        <ErrorState message="This subject could not be found in the current taxonomy." retry={() => router.push("/mocks/subject-wise")} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-6">
        <Link href="/mocks/subject-wise" className="inline-flex items-center gap-2 text-sm font-medium text-slate-600 hover:text-indigo-700">
          <ArrowLeft size={16} /> Back to subjects
        </Link>
      </div>

      <div className="mb-8">
        <p className="text-sm font-medium text-indigo-600">{topic.track_name}</p>
        <h2 className="mt-2 text-3xl font-bold">{displaySubjectName(topic.topic_name)} Mock</h2>
        <p className="mt-2 text-slate-500">Configure your mock.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="card p-6 md:p-8">
          <div className="grid gap-5 sm:grid-cols-2">
            <label className="text-sm font-semibold text-slate-700">
              Difficulty
              <select
                value={difficulty}
                onChange={(e) => setDifficulty(e.target.value as typeof difficulty)}
                className="mt-2 w-full rounded-xl border border-slate-200 px-3 py-3 text-sm font-normal outline-none"
              >
                <option value="EASY">Easy</option>
                <option value="MEDIUM">Medium</option>
                <option value="HARD">Hard</option>
                <option value="MIXED">Mixed</option>
              </select>
            </label>

            <label className="text-sm font-semibold text-slate-700">
              Number of questions
              <input
                type="number"
                min={1}
                max={100}
                value={count}
                onChange={(e) => setCount(Math.max(1, Number(e.target.value) || 1))}
                className="mt-2 w-full rounded-xl border border-slate-200 px-3 py-3 text-sm font-normal outline-none"
              />
            </label>
          </div>

          <div className="mt-6">
            <p className="text-sm font-semibold text-slate-700">Quick picks</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {quickCounts.map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setCount(value)}
                  className={`rounded-xl px-3 py-2 text-sm font-medium ${count === value ? "bg-indigo-600 text-white" : "border border-slate-200 bg-white text-slate-700"}`}
                >
                  {value}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-6">
            <label className="text-sm font-semibold text-slate-700">
              Duration (minutes)
              <select
                value={durationMinutes}
                onChange={(e) => setDurationMinutes(Number(e.target.value))}
                className="mt-2 w-full rounded-xl border border-slate-200 px-3 py-3 text-sm font-normal outline-none"
              >
                {quickDurations.map((value) => (
                  <option key={value} value={value}>
                    {value} minutes
                  </option>
                ))}
                <option value={90}>90 minutes</option>
              </select>
            </label>
          </div>

          {range.length > 0 && (
            <div className="mt-6">
              <label className="text-sm font-semibold text-slate-700">
                Topic / Subtopic
                <select
                  value={subtopicId}
                  onChange={(e) => setSubtopicId(e.target.value === "all" ? "all" : Number(e.target.value))}
                  className="mt-2 w-full rounded-xl border border-slate-200 px-3 py-3 text-sm font-normal outline-none"
                >
                  <option value="all">All {topic.topic_name} subtopics</option>
                  {range.map((subtopic) => (
                    <option key={subtopic.subtopic_id} value={subtopic.subtopic_id}>
                      {subtopic.subtopic_name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}

          {difficulty === "MIXED" && (
            <div className="mt-6 rounded-xl bg-slate-50 p-4">
              <p className="text-sm font-semibold text-slate-700">Mixed distribution</p>
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                {(["EASY", "MEDIUM", "TOUGH"] as const).map((key) => (
                  <label key={key} className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {key}
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={distribution[key]}
                      onChange={(e) => updateDistribution(key, Number(e.target.value) || 0)}
                      className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
                    />
                  </label>
                ))}
              </div>
            </div>
          )}

          {error && <p className="mt-5 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}

          <Button disabled={busy} className="mt-7 w-full" onClick={submit}>
            {busy ? "Creating mock…" : "Create mock"}
          </Button>
        </div>

        <aside className="card h-fit bg-slate-950 p-6 text-white">
          <Sparkles className="text-indigo-300" size={20} />
          <h3 className="mt-5 text-xl font-semibold">Focused practice</h3>
          <p className="mt-3 text-sm leading-6 text-slate-300">
            This mock targets the selected subject and keeps the structure close to the real placement assessment flow.
          </p>
          <div className="mt-8 space-y-4 text-sm text-slate-300">
            <p>• Server-backed question filtering</p>
            <p>• Duration-aware assessment timers</p>
            <p>• Subject and subtopic narrowing</p>
          </div>
        </aside>
      </div>
    </div>
  );
}
