"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Check, Gauge } from "lucide-react";
import { Button } from "@/components/shell";
import { Loading } from "@/components/loading";
import { api, ApiError } from "@/lib/api";
import type { SubjectTrack } from "@/lib/types";

const difficulties = [
  { id: "EASY", label: "Easy", desc: "Build momentum and review foundational concepts." },
  { id: "MEDIUM", label: "Medium", desc: "Standard placement assessment challenge level." },
  { id: "HARD", label: "Hard", desc: "Advanced difficulty questions to test deep readiness." },
] as const;

const quickCounts = [5, 10, 15, 20];
const quickDurations = [15, 30, 45, 60];

export default function DifficultyWiseMockPage() {
  const router = useRouter();
  const [difficulty, setDifficulty] = useState<"EASY" | "MEDIUM" | "HARD">("MEDIUM");
  const [count, setCount] = useState(10);
  const [duration, setDuration] = useState(30);
  const [questionType, setQuestionType] = useState<"MCQ" | "CODING">("MCQ");

  const [tracks, setTracks] = useState<SubjectTrack[]>([]);
  const [selectedTrackId, setSelectedTrackId] = useState<string>("all");
  const [selectedTopicId, setSelectedTopicId] = useState<string>("all");
  const [selectedSubtopicId, setSelectedSubtopicId] = useState<string>("all");

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api.taxonomy()
      .then((data) => {
        if (active) setTracks(data);
      })
      .catch(() => {})
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const activeTrack = tracks.find((t) => String(t.track_id) === selectedTrackId);
  const availableTopics = activeTrack ? activeTrack.topics : tracks.flatMap((t) => t.topics);
  const activeTopic = availableTopics.find((t) => String(t.topic_id) === selectedTopicId);
  const availableSubtopics = activeTopic ? activeTopic.subtopics : [];

  const handleCreate = async () => {
    setBusy(true);
    setError("");

    const diffName = difficulty === "HARD" ? "Hard" : difficulty === "EASY" ? "Easy" : "Medium";
    const body: Record<string, unknown> = {
      title: `${diffName} Mock Test`,
      difficulty,
      total_questions: count,
      duration_seconds: duration * 60,
      question_type: questionType,
      mode: "MOCK",
    };

    if (selectedTrackId !== "all") {
      body.track_id = Number(selectedTrackId);
    }
    if (selectedTopicId !== "all") {
      body.topic_id = Number(selectedTopicId);
    }
    if (selectedSubtopicId !== "all" && selectedTopicId !== "all") {
      body.subtopic_id = Number(selectedSubtopicId);
    }

    try {
      const mock = await api.createMock(body);
      router.push(`/mocks/${mock.mock_test_id}`);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        const next = `${window.location.pathname}${window.location.search}`;
        router.push(`/login?next=${encodeURIComponent(next)}`);
      } else if (cause instanceof ApiError && cause.status === 409) {
        setError(`Not enough eligible ${diffName} questions are currently available for this mock.`);
      } else {
        setError(cause instanceof Error ? cause.message : "Unable to create this mock right now.");
      }
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <Loading label="Loading configuration…" />;

  return (
    <div className="mx-auto max-w-4xl">
      <Link
        href="/mocks"
        className="inline-flex items-center gap-2 text-sm font-medium text-slate-500 hover:text-slate-900"
      >
        <ArrowLeft size={16} /> Back to Mock Tests
      </Link>

      <div className="mt-4 mb-8">
        <div className="flex items-center gap-2 text-sm font-semibold text-indigo-600">
          <Gauge size={18} /> Difficulty-wise preparation
        </div>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900">
          Difficulty-wise Mock
        </h1>
        <p className="mt-2 text-slate-500">
          Practice according to question difficulty with server-selected questions.
        </p>
      </div>

      <div className="space-y-6">
        {/* Difficulty Selection */}
        <div className="card p-6">
          <label className="text-sm font-semibold text-slate-900">Select Difficulty</label>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {difficulties.map((item) => {
              const active = difficulty === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setDifficulty(item.id)}
                  className={`flex flex-col justify-between rounded-xl border p-4 text-left transition ${
                    active
                      ? "border-indigo-600 bg-indigo-50/60 ring-1 ring-indigo-600"
                      : "border-slate-200 bg-white hover:border-slate-300"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className={`text-base font-semibold ${active ? "text-indigo-900" : "text-slate-900"}`}>
                      {item.label}
                    </span>
                    {active && <Check size={16} className="text-indigo-600" />}
                  </div>
                  <p className="mt-2 text-xs leading-5 text-slate-500">{item.desc}</p>
                </button>
              );
            })}
          </div>
        </div>

        {/* Configuration */}
        <div className="card p-6 space-y-6">
          <h2 className="text-base font-semibold text-slate-900">Configure Mock Parameters</h2>

          {/* Question Type */}
          <div>
            <label className="text-sm font-medium text-slate-700">Question Type</label>
            <div className="mt-2 flex gap-3">
              {(["MCQ", "CODING"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setQuestionType(t)}
                  className={`rounded-xl px-4 py-2.5 text-sm font-semibold transition ${
                    questionType === t
                      ? "bg-slate-900 text-white"
                      : "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  {t === "MCQ" ? "Multiple Choice (MCQ)" : "Coding / DSA"}
                </button>
              ))}
            </div>
          </div>

          {/* Question Count */}
          <div>
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium text-slate-700">Question Count</label>
              <span className="text-sm font-bold text-indigo-600">{count} questions</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {quickCounts.map((val) => (
                <button
                  key={val}
                  type="button"
                  onClick={() => setCount(val)}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${
                    count === val
                      ? "bg-indigo-600 text-white"
                      : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  {val} Qs
                </button>
              ))}
              <input
                type="number"
                min={1}
                max={100}
                value={count}
                onChange={(e) => setCount(Math.max(1, Math.min(100, Number(e.target.value) || 1)))}
                className="w-20 rounded-lg border border-slate-200 px-2 py-1 text-xs outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          {/* Duration */}
          <div>
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium text-slate-700">Duration</label>
              <span className="text-sm font-bold text-indigo-600">{duration} minutes</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {quickDurations.map((val) => (
                <button
                  key={val}
                  type="button"
                  onClick={() => setDuration(val)}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${
                    duration === val
                      ? "bg-indigo-600 text-white"
                      : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  {val} mins
                </button>
              ))}
              <input
                type="number"
                min={1}
                max={180}
                value={duration}
                onChange={(e) => setDuration(Math.max(1, Math.min(180, Number(e.target.value) || 1)))}
                className="w-24 rounded-lg border border-slate-200 px-2 py-1 text-xs outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          {/* Optional Topic / Subtopic Filter */}
          <div className="border-t border-slate-100 pt-5">
            <label className="text-sm font-semibold text-slate-900">
              Subject & Topic Filter <span className="text-xs font-normal text-slate-500">(Optional)</span>
            </label>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <div>
                <label className="text-xs text-slate-500">Track</label>
                <select
                  value={selectedTrackId}
                  onChange={(e) => {
                    setSelectedTrackId(e.target.value);
                    setSelectedTopicId("all");
                    setSelectedSubtopicId("all");
                  }}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500"
                >
                  <option value="all">All Tracks</option>
                  {tracks.map((t) => (
                    <option key={t.track_id} value={String(t.track_id)}>
                      {t.track_name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs text-slate-500">Topic</label>
                <select
                  value={selectedTopicId}
                  onChange={(e) => {
                    setSelectedTopicId(e.target.value);
                    setSelectedSubtopicId("all");
                  }}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500"
                >
                  <option value="all">All Topics</option>
                  {availableTopics.map((t) => (
                    <option key={t.topic_id} value={String(t.topic_id)}>
                      {t.topic_name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {availableSubtopics.length > 0 && selectedTopicId !== "all" && (
              <div className="mt-3">
                <label className="text-xs text-slate-500">Subtopic</label>
                <select
                  value={selectedSubtopicId}
                  onChange={(e) => setSelectedSubtopicId(e.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500"
                >
                  <option value="all">All Subtopics</option>
                  {availableSubtopics.map((st) => (
                    <option key={st.subtopic_id} value={String(st.subtopic_id)}>
                      {st.subtopic_name}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-medium text-red-700">
            {error}
          </div>
        )}

        <Button
          disabled={busy}
          onClick={handleCreate}
          className="w-full py-3 text-base"
        >
          {busy ? "Creating mock test…" : "Create Mock"}
        </Button>
      </div>
    </div>
  );
}
