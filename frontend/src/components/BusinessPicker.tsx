import { useEffect, useState, type ReactNode } from "react";
import { ApiError, session } from "../services/apiClient";
import { businessService } from "../services/businessService";
import type { BusinessPublic } from "../types";

/** Lets a customer choose which business they are talking to; renders `children` once one is selected. */
export function BusinessPicker({ children }: { children: (businessId: string) => ReactNode }) {
  const [businesses, setBusinesses] = useState<BusinessPublic[] | null>(null);
  const [selected, setSelected] = useState<string>(session.getBusiness() ?? "");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    businessService
      .listActive()
      .then((list) => {
        if (cancelled) return;
        setBusinesses(list);
        // Keep the remembered choice if it still exists, otherwise fall back to the first business.
        setSelected((current) => (list.some((b) => b.id === current) ? current : (list[0]?.id ?? "")));
      })
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : "Could not load businesses"));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    session.setBusiness(selected || null);
  }, [selected]);

  if (error)
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  if (!businesses) return <p className="muted">Loading…</p>;
  if (businesses.length === 0) return <p className="muted empty">No businesses are available yet. Please check back soon.</p>;

  // Grouped by domain; each domain's compare-all assistant comes first in its group.
  const byDomain = new Map<string, BusinessPublic[]>();
  for (const b of [...businesses].sort((x, y) => Number(y.isMarketplace) - Number(x.isMarketplace))) {
    const key = b.domainName ?? "Other";
    byDomain.set(key, [...(byDomain.get(key) ?? []), b]);
  }
  const groups = [...byDomain.entries()].sort(([x], [y]) => x.localeCompare(y));

  return (
    <>
      <label className="business-picker">
        Business
        <select value={selected} onChange={(e) => setSelected(e.target.value)} aria-label="Business">
          {groups.map(([domain, items]) => (
            <optgroup key={domain} label={domain}>
              {items.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      {selected && children(selected)}
    </>
  );
}
