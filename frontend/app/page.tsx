import Link from "next/link";
import {
  ArrowRight,
  BarChart3,
  BrainCircuit,
  Building2,
  Code2,
  LayoutDashboard,
  PlayCircle,
  Sparkles,
  Wand2,
} from "lucide-react";

const linkCards = [
  {
    href: "/mocks",
    label: "Mock Test",
    description: "Simulate a complete placement assessment and track your readiness.",
    icon: PlayCircle,
    accent: "bg-indigo-50 text-indigo-600",
  },
  {
    href: "/questions",
    label: "Practice",
    description: "Sharpen your aptitude and problem-solving with targeted practice.",
    icon: BrainCircuit,
    accent: "bg-emerald-50 text-emerald-600",
  },
  {
    href: "/dashboard",
    label: "Dashboard",
    description: "Review progress, trends, and your next-best preparation moves.",
    icon: LayoutDashboard,
    accent: "bg-violet-50 text-violet-600",
  },
  {
    href: "/analytics",
    label: "Analytics",
    description: "See how your scores and topic accuracy are trending over time.",
    icon: BarChart3,
    accent: "bg-sky-50 text-sky-600",
  },
  {
    href: "/ai-mock",
    label: "AI Mock Generator",
    description: "Build a custom mock with AI tailored around your weak spots.",
    icon: Wand2,
    accent: "bg-fuchsia-50 text-fuchsia-600",
  },
  {
    href: "/companies",
    label: "Companies",
    description: "Prepare against company-specific patterns and blueprints.",
    icon: Building2,
    accent: "bg-amber-50 text-amber-600",
  },
  {
    href: "/coding",
    label: "Coding / DSA",
    description: "Practice coding challenges and keep your algorithmic momentum going.",
    icon: Code2,
    accent: "bg-sky-50 text-sky-600",
  },
] as const;

export default function Home() {
  return (
    <main className="min-h-screen bg-white">
      <nav className="mx-auto flex max-w-7xl items-center justify-between px-6 py-6">
        <Link href="/" className="flex items-center gap-2 text-lg font-bold">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-indigo-600 text-white">
            <Sparkles size={18} />
          </span>
          prepwise
        </Link>

        <div className="flex gap-3">
          <Link href="/login" className="rounded-xl px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50">
            Log in
          </Link>
          <Link href="/register" className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700">
            Start preparing
          </Link>
        </div>
      </nav>

      <section className="mx-auto max-w-7xl px-6 pb-18 pt-16 lg:pt-24">
        <div className="max-w-3xl">
          <p className="mb-5 inline-flex items-center gap-2 rounded-full bg-indigo-50 px-3 py-1.5 text-sm font-semibold text-indigo-700">
            <Sparkles size={15} /> Built for placement readiness
          </p>
          <h1 className="text-5xl font-bold leading-[1.08] tracking-tight text-slate-950 md:text-7xl">
            Prepare smarter.
            <br />
            <span className="text-indigo-600">Get placement ready.</span>
          </h1>
          <p className="mt-7 max-w-xl text-lg leading-8 text-slate-500">
            One focused workspace for aptitude, technical MCQs, DSA, and company preparation.
          </p>
          <div className="mt-9 flex flex-wrap gap-3">
            <Link href="/register" className="flex items-center gap-2 rounded-xl bg-indigo-600 px-5 py-3.5 text-sm font-semibold text-white hover:bg-indigo-700">
              Start preparing <ArrowRight size={17} />
            </Link>
            <Link href="/login" className="rounded-xl border border-slate-200 px-5 py-3.5 text-sm font-semibold text-slate-700 hover:bg-slate-50">
              Explore workspace
            </Link>
          </div>
        </div>

        <div className="mt-12 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {linkCards.map(({ href, label, description, icon: Icon, accent }) => (
            <Link
              key={href}
              href={href}
              className="card group relative z-10 block p-6 text-left transition pointer-events-auto hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md"
            >
              <div className={`flex h-12 w-12 items-center justify-center rounded-xl ${accent}`}>
                <Icon size={22} />
              </div>
              <h2 className="mt-6 text-2xl font-semibold text-slate-900">{label}</h2>
              <p className="mt-3 text-sm leading-6 text-slate-500">{description}</p>
              <span className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-indigo-700">
                Open {label.toLowerCase()} <ArrowRight size={15} />
              </span>
            </Link>
          ))}
        </div>
      </section>
    </main>
  );
}
