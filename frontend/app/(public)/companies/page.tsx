"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, Building2 } from "lucide-react";
import { ErrorState, Loading } from "@/components/loading";
import { api } from "@/lib/api";
import type { Company } from "@/lib/types";

export default function Companies() {
  const [items, setItems] = useState<Company[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    api.companies()
      .then((data) => {
        if (active) setItems(data);
      })
      .catch((cause: Error) => {
        if (active) setError(cause.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <>
      <div className="mb-8">
        <p className="text-sm font-medium text-indigo-600">Targeted preparation</p>
        <h2 className="mt-2 text-3xl font-bold">Companies</h2>
        <p className="mt-2 text-slate-500">
          Explore available preparation blueprints and practice with intent.
        </p>
      </div>
      {error ? (
        <ErrorState message={error} retry={() => window.location.reload()} />
      ) : loading ? (
        <Loading label="Loading company patterns…" />
      ) : items.length ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {items.map((company) => (
            <Link
              href={`/companies/${company.company_id}`}
              key={company.company_id}
              className="card group p-6 hover:border-indigo-200 hover:shadow-md"
            >
              <div className="flex items-start justify-between">
                <div className="grid h-12 w-12 place-items-center rounded-xl bg-indigo-50 text-indigo-600">
                  <Building2 />
                </div>
                <ArrowRight className="text-slate-300 transition group-hover:text-indigo-600" />
              </div>
              <h3 className="mt-6 text-lg font-semibold group-hover:text-indigo-700">
                {company.company_name}
              </h3>
              <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-500">
                {company.description || "Explore the latest available preparation pattern."}
              </p>
            </Link>
          ))}
        </div>
      ) : (
        <div className="card p-8 text-sm text-slate-500">
          No company patterns are currently available.
        </div>
      )}
    </>
  );
}
