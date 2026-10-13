"use client";

import { useState } from "react";

export const MIN_DURATION_MINUTES = 1;
export const MAX_DURATION_MINUTES = 480;
const PRESETS = [15, 30, 45, 60, 90, 120];

export function DurationSelector({ value, onChange }: { value: number; onChange: (minutes: number) => void }) {
  const [custom, setCustom] = useState(false);
  const [customValue, setCustomValue] = useState("");
  const choose = (minutes: number) => { setCustom(false); onChange(minutes); };
  const updateCustom = (raw: string) => {
    setCustomValue(raw);
    const parsed = Number(raw);
    onChange(Number.isInteger(parsed) && parsed >= MIN_DURATION_MINUTES && parsed <= MAX_DURATION_MINUTES ? parsed : 0);
  };
  return <fieldset className="mt-6">
    <legend className="text-sm font-semibold">Choose Your Test Duration</legend>
    <div className="mt-3 flex flex-wrap gap-2">
      {PRESETS.map((minutes) => <button key={minutes} type="button" aria-pressed={!custom && value === minutes} onClick={() => choose(minutes)} className={`rounded-lg border px-3 py-2 text-sm ${!custom && value === minutes ? "border-indigo-600 bg-indigo-600 text-white" : "border-slate-200 bg-white text-slate-700"}`}>{minutes} minutes</button>)}
      <button type="button" aria-pressed={custom} onClick={() => setCustom(true)} className={`rounded-lg border px-3 py-2 text-sm ${custom ? "border-indigo-600 bg-indigo-600 text-white" : "border-slate-200 bg-white text-slate-700"}`}>Custom duration</button>
    </div>
    {custom && <label className="mt-3 block text-sm">Custom duration in minutes
      <input type="number" min={MIN_DURATION_MINUTES} max={MAX_DURATION_MINUTES} step={1} value={customValue} onChange={(e) => updateCustom(e.target.value)} className="mt-1 w-full max-w-xs rounded-lg border border-slate-200 px-3 py-2" aria-describedby="duration-limits" />
    </label>}
    <p id="duration-limits" className="mt-2 text-xs text-slate-500">Choose {MIN_DURATION_MINUTES}–{MAX_DURATION_MINUTES} minutes. Selected: <strong>{value > 0 ? `${value} minutes` : "Enter a valid duration"}</strong>.</p>
  </fieldset>;
}
