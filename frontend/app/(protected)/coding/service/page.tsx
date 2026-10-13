"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowLeft, Check, ChevronDown, ExternalLink, Search } from "lucide-react";
import { api } from "@/lib/api";
import { Loading, ErrorState } from "@/components/loading";

function platform(url: string) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host === "leetcode.com" || host.endsWith(".leetcode.com")) return "LeetCode";
    if (host === "geeksforgeeks.org" || host.endsWith(".geeksforgeeks.org")) return "GeeksforGeeks";
  } catch {}
  return "Open problem";
}

export default function ServiceCompanies() {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.codingPractice>> | null>(null);
  const [solvedIds, setSolvedIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "solved" | "unsolved">("all");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  useEffect(() => { let active = true; api.codingPractice().then(v => { if (active) { setData(v); setSolvedIds(new Set(v.solved_problem_ids)); } }).catch(e => { if (active) setError(e.message); }); return () => { active = false; }; }, [reload]);
  if (error && !data) return <ErrorState message={error} retry={() => { setError(""); setReload(v => v + 1); }} />;
  if (!data) return <Loading label="Loading service-company collections…"/>;
  const total = data.sections.reduce((sum, section) => sum + section.problems.length, 0);
  const completed = solvedIds.size;
  const remaining = Math.max(0, total - completed);
  const percent = total ? Math.round(completed / total * 100) : 0;
  const visible = (id: string, title: string) =>
    (filter === "all" || (filter === "solved") === solvedIds.has(id)) &&
    title.toLowerCase().includes(query.trim().toLowerCase());
  async function toggle(id: string) {
    const wasSolved = solvedIds.has(id);
    setSolvedIds(current => { const next = new Set(current); if (wasSolved) next.delete(id); else next.add(id); return next; });
    try { await api.setCodingProblemSolved(id, !wasSolved); }
    catch (e) {
      setSolvedIds(current => { const next = new Set(current); if (wasSolved) next.add(id); else next.delete(id); return next; });
      setError(e instanceof Error ? e.message : "Could not save progress.");
    }
  }
  return <>
    <Link href="/coding" className="mb-5 inline-flex items-center gap-2 text-sm font-medium text-slate-500 hover:text-indigo-600"><ArrowLeft size={16}/> Coding / DSA</Link>
    <div className="mb-6"><p className="text-sm font-medium text-indigo-600">Service-based placement practice</p><h1 className="mt-2 text-3xl font-bold tracking-tight">Service-Based Coding Practice</h1><p className="mt-2 text-slate-500">A shared collection of service-company placement questions, organized by topic.</p></div>
    {error && <div role="alert" className="mb-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-800">{error} <button className="font-semibold underline" onClick={() => setError("")}>Dismiss</button></div>}
    {!data.authenticated && <div className="mb-4 rounded-xl border border-indigo-100 bg-indigo-50 p-3 text-sm text-indigo-800">Sign in to save your solved progress. <Link className="font-semibold underline" href="/login">Log in</Link></div>}
    <section className="card mb-5 p-5"><div className="grid grid-cols-2 gap-4 sm:grid-cols-3"><Metric label="Total questions" value={total}/><Metric label="Solved questions" value={completed}/><Metric label="Remaining questions" value={remaining}/></div><div className="mt-4 flex items-center justify-between text-xs text-slate-500"><span>{completed} / {total} solved</span><span>{percent}%</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-indigo-600 transition-all" style={{width:`${percent}%`}}/></div></section>
    <div className="mb-4 flex flex-col gap-3 sm:flex-row"><label className="relative flex-1"><Search size={17} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search questions…" className="w-full rounded-xl border border-slate-200 bg-white py-3 pl-10 pr-3 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"/></label><div className="flex rounded-xl bg-slate-100 p-1">{(["all","solved","unsolved"] as const).map(v=><button key={v} onClick={()=>setFilter(v)} className={`rounded-lg px-4 py-2 text-sm font-medium capitalize ${filter===v?"bg-white text-indigo-700 shadow-sm":"text-slate-500"}`}>{v}</button>)}</div></div>
    <div className="space-y-4">{data.sections.map(section => { const rows=section.problems.filter(p=>visible(p.id,p.title)); if (!rows.length) return null; const isCollapsed=collapsed.has(section.title); return <section key={section.title} className="card overflow-hidden"><button onClick={()=>setCollapsed(prev=>{const next=new Set(prev); if (isCollapsed) next.delete(section.title); else next.add(section.title); return next;})} aria-expanded={!isCollapsed} className="flex w-full items-center justify-between px-5 py-4 text-left"><span><span className="block font-semibold">{section.title}</span><span className="mt-1 block text-xs text-slate-500">{rows.length} questions</span></span><ChevronDown size={18} className={`text-slate-400 transition ${isCollapsed?"-rotate-90":""}`}/></button>{!isCollapsed&&<ul className="divide-y divide-slate-100">{rows.map(problem=>{const checked=solvedIds.has(problem.id); const source=platform(problem.url); return <li key={problem.id} className={`flex items-center gap-3 px-4 py-3 sm:px-5 ${checked?"bg-emerald-50/40":""}`}><button type="button" role="checkbox" aria-checked={checked} aria-label={`${checked?"Mark unsolved":"Mark solved"}: ${problem.title}`} onClick={()=>void toggle(problem.id)} className={`grid h-6 w-6 shrink-0 place-items-center rounded-md border transition ${checked?"border-emerald-600 bg-emerald-600 text-white":"border-slate-300 bg-white text-transparent hover:border-indigo-500"}`}><Check size={15}/></button><span className="w-8 shrink-0 text-sm tabular-nums text-slate-400">{problem.number}.</span><span className={`min-w-0 flex-1 text-sm leading-6 ${checked?"text-slate-500 line-through":"text-slate-800"}`}>{problem.title}</span><a href={problem.url} target="_blank" rel="noopener noreferrer" aria-label={`Open on ${source}`} title={`Open on ${source}`} className="inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 text-xs font-semibold text-slate-600 hover:border-indigo-200 hover:text-indigo-700"><span className="hidden sm:inline">{source}</span><PlatformMark source={source}/><ExternalLink size={15}/></a></li>;})}</ul>}</section>;})}</div>
    {!data.sections.some(s=>s.problems.some(p=>visible(p.id,p.title)))&&<div className="card p-8 text-center text-sm text-slate-500">No questions match your search and filter.</div>}
  </>;
}
function Metric({label,value}:{label:string;value:string|number}) { return <div><p className="text-xs font-medium text-slate-500">{label}</p><p className="mt-1 text-xl font-bold tabular-nums text-slate-900">{value}</p></div>; }
function PlatformMark({source}:{source:string}) { if (source === "GeeksforGeeks") return <span aria-hidden="true" className="grid h-6 w-6 place-items-center rounded-full bg-emerald-100 text-[9px] font-black tracking-tight text-emerald-700">GFG</span>; if (source === "LeetCode") return <span aria-hidden="true" className="grid h-6 w-6 place-items-center rounded-full bg-amber-100 text-[9px] font-black text-amber-700">LC</span>; return null; }
