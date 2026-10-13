import Link from "next/link";
import { ArrowUpRight, BriefcaseBusiness, Building2, Code2 } from "lucide-react";

const categories = [
  { title: "Service-Based Companies", href: "/coding/service", description: "Practice the 150-question placement collection shared across service-company preparation.", icon: BriefcaseBusiness, tone: "bg-indigo-50 text-indigo-600" },
  { title: "Product-Based Companies", href: "/coding/product", description: "Explore coding collections for product-company technical interviews and assessments.", icon: Code2, tone: "bg-emerald-50 text-emerald-600" },
];

export default function Coding() {
  return <>
    <div className="mb-8"><p className="text-sm font-medium text-indigo-600">Coding / DSA</p><h1 className="mt-2 text-3xl font-bold tracking-tight">Choose your practice track</h1><p className="mt-2 max-w-2xl text-slate-500">Build problem-solving confidence with curated collections organized around your placement goals.</p></div>
    <div className="grid gap-5 md:grid-cols-2">{categories.map(({ title, href, description, icon: Icon, tone }) => <Link href={href} key={title} className="card group p-6 transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md"><div className="flex items-start justify-between"><span className={`grid h-12 w-12 place-items-center rounded-2xl ${tone}`}><Icon size={23}/></span><ArrowUpRight className="text-slate-400 transition group-hover:text-indigo-600" size={19}/></div><h2 className="mt-6 text-xl font-semibold">{title}</h2><p className="mt-2 leading-6 text-slate-500">{description}</p><span className="mt-6 inline-flex items-center gap-2 text-sm font-semibold text-indigo-600"><Building2 size={16}/> Explore collections</span></Link>)}</div>
  </>;
}
