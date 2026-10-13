import Link from "next/link";
import { ArrowRight, Building2, Gauge, Layers3 } from "lucide-react";

const preparations = [
  {
    title: "Difficulty-wise",
    description: "Practice according to question difficulty.",
    href: "/mocks/difficulty-wise",
    icon: Gauge,
  },
  {
    title: "Subject-wise",
    description: "Focus your mock on a specific placement subject.",
    href: "/mocks/subject-wise",
    icon: Layers3,
  },
  {
    title: "Company-wise",
    description: "Practice according to a company's preparation pattern.",
    href: "/companies",
    icon: Building2,
  },
] as const;

export default function MocksPage() {
  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-8">
        <p className="text-sm font-medium text-indigo-600">Assessment center</p>
        <h2 className="mt-2 text-3xl font-bold">Mock Tests</h2>
        <p className="mt-2 text-slate-500">Choose how you want to prepare.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {preparations.map(({ title, description, href, icon: Icon }) => (
          <Link
            key={title}
            href={href}
            className="group block rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md"
          >
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
              <Icon size={20} />
            </div>
            <h3 className="mt-5 text-xl font-semibold text-slate-900">{title}</h3>
            <p className="mt-3 text-sm leading-6 text-slate-500">{description}</p>
            <span className="mt-6 inline-flex items-center gap-2 text-sm font-semibold text-indigo-700">
              Explore <ArrowRight size={16} />
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
