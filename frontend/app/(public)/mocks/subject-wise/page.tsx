"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, BookOpen } from "lucide-react";
import { ErrorState, Loading } from "@/components/loading";
import { api } from "@/lib/api";
import type { SubjectTrack } from "@/lib/types";

function describeSubject(topicName: string) {
  const normalized = topicName.toLowerCase();

  if (normalized.includes("quant")) return "Practice numerical aptitude questions.";
  if (normalized.includes("verbal")) return "Practice vocabulary, grammar and verbal reasoning.";
  if (normalized.includes("logical") || normalized.includes("reasoning")) return "Practice pattern recognition and logic-based questions.";
  if (normalized.includes("data") && normalized.includes("interpret")) return "Practice tables, charts and analytical interpretation.";
  if (normalized.includes("puzzle") || normalized.includes("brain")) return "Practice logic puzzles and brain-teaser style questions.";
  if (normalized.includes("oops") || normalized.includes("oop")) return "Practice object-oriented programming concepts.";
  if (normalized.includes("dbms") || normalized.includes("database management")) return "Practice database and SQL concepts.";
  if (normalized.includes("operating")) return "Practice operating-system concepts.";
  if (normalized.includes("network")) return "Practice networking fundamentals and protocols.";
  if (normalized.includes("ai") || normalized.includes("ml")) return "Practice AI, ML and data-driven problem solving.";
  if (normalized.includes("programming")) return "Practice core programming concepts and coding fundamentals.";

  return "Practice focused questions from this subject area.";
}

function displaySubjectName(topicName: string) {
  return topicName.toLowerCase() === "database management" ? "DBMS" : topicName;
}

export default function SubjectWisePage() {
  const [tracks, setTracks] = useState<SubjectTrack[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;

    api
      .taxonomy()
      .then((data) => {
        if (active) setTracks(data);
      })
      .catch((e: Error) => {
        if (active) setError(e.message || "Unable to load subject taxonomy.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const topics = useMemo(
    () =>
      tracks.flatMap((track) =>
        track.topics.map((topic) => ({
          ...topic,
          track_id: track.track_id,
          track_name: track.track_name,
        })),
      ),
    [tracks],
  );

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error} retry={() => window.location.reload()} />;

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-8">
        <p className="text-sm font-medium text-indigo-600">Subject selection</p>
        <h2 className="mt-2 text-3xl font-bold">Subject-wise Mock Tests</h2>
        <p className="mt-2 text-slate-500">Choose a subject and create a focused mock test.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {topics.map((topic) => (
          <Link
            key={`${topic.track_id}-${topic.topic_id}`}
            href={`/mocks/subject-wise/${topic.topic_id}?trackId=${topic.track_id}`}
            className="group block rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="grid h-11 w-11 place-items-center rounded-xl bg-indigo-50 text-indigo-600">
                <BookOpen size={18} />
              </div>
              <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                {topic.track_name}
              </span>
            </div>

            <h3 className="mt-5 text-xl font-semibold text-slate-900">{displaySubjectName(topic.topic_name)}</h3>
            <p className="mt-3 text-sm leading-6 text-slate-500">{describeSubject(topic.topic_name)}</p>

            <div className="mt-5 flex items-center justify-between">
              <span className="text-xs text-slate-500">
                {topic.subtopics.length ? `${topic.subtopics.length} subtopics` : "Broad topic"}
              </span>
              <span className="inline-flex items-center gap-2 text-sm font-semibold text-indigo-700">
                Create Mock <ArrowRight size={15} />
              </span>
            </div>
          </Link>
        ))}
      </div>
      {!topics.length && (
        <div className="card mt-4 p-8 text-sm text-slate-500">
          No placement subjects are currently available.
        </div>
      )}
    </div>
  );
}
