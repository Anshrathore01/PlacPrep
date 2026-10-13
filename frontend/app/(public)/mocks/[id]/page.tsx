"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { MockTest } from "@/lib/types";
import { Badge, Button } from "@/components/shell";
import { Loading, ErrorState } from "@/components/loading";
import { Clock3, FileCheck2 } from "lucide-react";
import { DurationSelector } from "@/components/duration-selector";

export default function MockDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [mock, setMock] = useState<MockTest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [duration, setDuration] = useState(30);

  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    api.mocks(Number(id))
      .then((data) => {
        if (active) { setMock(data); setDuration(Math.max(1, Math.min(480, Math.round((data.duration_seconds || 1800) / 60)))); }
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

  if (error && !mock) return <ErrorState message={error} retry={retry} />;
  if (loading || !mock) return <Loading label="Loading assessment details…" />;

  const start = async () => {
    if (duration < 1 || duration > 480) { setError("Choose a duration from 1 to 480 minutes."); return; }
    setBusy(true);
    setError("");
    try {
      const attempt = await api.startAttempt(Number(id), duration * 60);
      router.push(`/mocks/${id}/attempt/${attempt.attempt_id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        const next = `/mocks/${id}`;
        router.push(`/login?next=${encodeURIComponent(next)}`);
      } else {
        setError(e instanceof Error ? e.message : "Unable to start attempt.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl">
      <div className="card overflow-hidden">
        <div className="bg-indigo-600 p-8 text-white">
          <Badge tone="indigo">
            {mock.selection_mode === "AI_GENERATED" ? "AI Generated" : "Mock test"}
          </Badge>
          <h2 className="mt-5 text-3xl font-bold">{mock.title}</h2>
          <p className="mt-2 text-indigo-100">Questions from the existing placement question bank.</p>
        </div>
        <div className="p-8">
          <div className="grid gap-4 sm:grid-cols-3">
            {[
              [FileCheck2, `${mock.total_questions} questions`],
              [Clock3, mock.duration_seconds ? `${Math.round(mock.duration_seconds / 60)} minutes` : "Untimed"],
              [FileCheck2, mock.mode],
            ].map(([Icon, label]) => {
              const I = Icon as typeof FileCheck2;
              return (
                <div key={label as string} className="rounded-xl bg-slate-50 p-4">
                  <I size={18} className="text-indigo-600" />
                  <p className="mt-3 text-sm font-semibold">{label as string}</p>
                </div>
              );
            })}
          </div>
          <p className="mt-8 text-sm leading-6 text-slate-500">
            The server controls timing, answer validation, scoring, and assessment state. You can resume an in-progress attempt after a refresh.
          </p>
          <DurationSelector value={duration} onChange={setDuration} />
          {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
          <Button disabled={busy || duration < 1} onClick={start} className="mt-7 w-full">
            {busy ? "Starting…" : `Start assessment · ${duration} minutes`}
          </Button>
        </div>
      </div>
    </div>
  );
}
