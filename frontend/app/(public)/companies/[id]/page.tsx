"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Badge, Button } from "@/components/shell";
import { ErrorState, Loading } from "@/components/loading";
import { ApiError, api } from "@/lib/api";
import type { Company } from "@/lib/types";
import { Building2, Play } from "lucide-react";
import { DurationSelector } from "@/components/duration-selector";

export default function CompanyPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [company, setCompany] = useState<Company>();
  const [error, setError] = useState("");
  const [busyBlueprintId, setBusyBlueprintId] = useState<number | null>(null);
  const [startingMockId, setStartingMockId] = useState<number | null>(null);
  const [selectedBlueprintId, setSelectedBlueprintId] = useState<number | null>(null);
  const [durations, setDurations] = useState<Record<number, number>>({});

  useEffect(() => {
    let active = true;
    api.company(Number(id))
      .then((data) => {
        if (active) setCompany(data);
      })
      .catch((cause: Error) => {
        if (active) setError(cause.message);
      });
    return () => {
      active = false;
    };
  }, [id]);

  const createMock = async (blueprintId: number, title: string) => {
    setBusyBlueprintId(blueprintId);
    setError("");
    try {
      const mock = await api.createMock({
        title,
        blueprint_id: blueprintId,
        mode: "MOCK",
      });
      router.push(`/mocks/${mock.mock_test_id}`);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        const next = `${window.location.pathname}${window.location.search}`;
        router.push(`/login?next=${encodeURIComponent(next)}`);
      } else {
        setError(cause instanceof ApiError ? cause.message : "Unable to create this mock right now.");
      }
    } finally {
      setBusyBlueprintId(null);
    }
  };

  const startFullLengthMock = async (mockTestId: number) => {
    const selectedDuration = durations[mockTestId] || 60;
    if (selectedDuration < 1 || selectedDuration > 480) { setError("Choose a duration from 1 to 480 minutes."); return; }
    setStartingMockId(mockTestId);
    setError("");
    try {
      const attempt = await api.startAttempt(mockTestId, selectedDuration * 60);
      router.push(`/mocks/${mockTestId}/attempt/${attempt.attempt_id}`);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        const next = `${window.location.pathname}${window.location.search}`;
        router.push(`/login?next=${encodeURIComponent(next)}`);
      } else {
        setError(cause instanceof ApiError ? cause.message : "Unable to start this mock right now.");
      }
    } finally {
      setStartingMockId(null);
    }
  };

  if (error && !company) return <ErrorState message={error} retry={() => window.location.reload()} />;
  if (!company) return <Loading label="Loading company patterns…" />;

  return (
    <div className="mx-auto max-w-5xl">
      <div className="card bg-slate-950 p-8 text-white">
        <div className="grid h-12 w-12 place-items-center rounded-xl bg-white/10">
          <Building2 />
        </div>
        <h2 className="mt-6 text-3xl font-bold">{company.company_name}</h2>
        <p className="mt-3 max-w-2xl text-slate-300">
          {company.description || "Company preparation patterns from the platform."}
        </p>
      </div>

      {company.full_length_mocks && company.full_length_mocks.length > 0 && (
        <section className="mt-6">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-600">FULL LENGTH MOCK</p>
              <h3 className="mt-1 text-2xl font-bold">{company.full_length_mocks.length} TCS NQT Full Length Papers</h3>
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {company.full_length_mocks.map((mock) => {
              const paperName = mock.title.includes("Paper ") ? mock.title.replace("TCS NQT Full Length ", "") : mock.title;
              const sectionSummary = mock.sections.length ? mock.sections.join(" · ") : "MCQ";
              return (
                <div key={mock.mock_test_id} className="card p-5">
                  <div className="flex items-center justify-between gap-3">
                    <span className="rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700">{paperName}</span>
                    <span className="text-xs text-slate-500">{mock.total_questions} Qs</span>
                  </div>
                  <h4 className="mt-4 text-lg font-semibold">{paperName}</h4>
                  <div className="mt-3 space-y-2 text-sm text-slate-600">
                    <p>Sections: {sectionSummary}</p>
                    <p>Coding: {mock.coding_question_count > 0 ? `${mock.coding_question_count} questions` : "Not present"}</p>
                  </div>
                  <DurationSelector value={durations[mock.mock_test_id] || 60} onChange={(minutes) => setDurations((current) => ({ ...current, [mock.mock_test_id]: minutes }))} />
                  <Button
                    onClick={() => startFullLengthMock(mock.mock_test_id)}
                    className="mt-5 w-full"
                    disabled={startingMockId === mock.mock_test_id}
                  >
                    <Play size={16} className="mr-2 inline" />
                    {startingMockId === mock.mock_test_id ? "Starting…" : `Start Mock · ${durations[mock.mock_test_id] || 60} minutes`}
                  </Button>
                </div>
              );
            })}
          </div>
        </section>
      )}

      <section className="mt-6">
        <h3 className="text-lg font-semibold">Available blueprints</h3>
        <p className="mt-1 text-sm text-slate-500">Browse preparation patterns without signing in.</p>
        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          {(company.blueprints || []).map((blueprint) => {
            const title = blueprint.blueprint_name || blueprint.program_name || "Preparation blueprint";
            return (
              <div key={blueprint.blueprint_id} className="card p-6">
                <div className="flex justify-between gap-3">
                  <h4 className="font-semibold">{title}</h4>
                  <Badge tone={blueprint.ready_for_mock ? "green" : "slate"}>
                    {blueprint.status || "Available"}
                  </Badge>
                </div>
                <p className="mt-2 text-sm text-slate-500">
                  {blueprint.program_name || "General preparation"}
                  {blueprint.pattern_version && ` · ${blueprint.pattern_version}`}
                </p>
                <div className="mt-5 space-y-2">
                  {(blueprint.rules || []).slice(0, 4).map((rule, index) => (
                    <div
                      key={`${rule.section_name || rule.question_type}-${index}`}
                      className="flex justify-between rounded-lg bg-slate-50 px-3 py-2 text-xs"
                    >
                      <span>{rule.section_name || rule.question_type}</span>
                      <span>{rule.question_count} · {rule.difficulty || "mixed"}</span>
                    </div>
                  ))}
                </div>
                <Button
                  variant={selectedBlueprintId === blueprint.blueprint_id ? "primary" : "secondary"}
                  onClick={() => setSelectedBlueprintId(blueprint.blueprint_id)}
                  className="mt-5 w-full"
                >
                  {selectedBlueprintId === blueprint.blueprint_id ? "Pattern selected" : "Select pattern"}
                </Button>
                {blueprint.ready_for_mock && (
                  <Button
                    disabled={busyBlueprintId !== null}
                    onClick={() => createMock(blueprint.blueprint_id, title)}
                    className="mt-3 w-full"
                  >
                    {busyBlueprintId === blueprint.blueprint_id ? "Preparing…" : "Create Mock"}
                  </Button>
                )}
                {!blueprint.ready_for_mock && selectedBlueprintId === blueprint.blueprint_id && (
                  <p className="mt-3 text-xs text-slate-500">
                    This pattern is not currently eligible for mock creation.
                  </p>
                )}
              </div>
            );
          })}
          {!company.blueprints?.length && (
            <div className="card p-8 text-sm text-slate-500">
              No active mock blueprint is available for this company yet.
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
