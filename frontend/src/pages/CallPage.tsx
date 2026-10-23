import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError } from "../services/apiClient";
import { publicService } from "../services/publicService";
import type { PublicNumber } from "../types";
import { telHref } from "../utils/phone";

function NumberCard({ item }: { item: PublicNumber }) {
  return (
    <div className="card call-card">
      <h2>{item.name}</h2>
      {item.isMarketplace && <p className="muted">One line for every {item.domainName ?? "partner"} we work with</p>}
      <a className="call-number" href={telHref(item.phone)}>
        {item.phone}
      </a>
    </div>
  );
}

/** No login: who to phone. `/call` lists everyone; `/call/:id` is the page of one business, for sharing. */
export function CallPage() {
  const { id } = useParams();
  const [items, setItems] = useState<PublicNumber[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = id ? publicService.getNumber(id).then((one) => [one]) : publicService.listNumbers();
    load
      .then((list) => !cancelled && setItems(list))
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) setItems([]);
        else setError(err instanceof ApiError ? err.message : "Could not load the phone numbers");
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (error)
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  if (!items) return <p className="muted center loading">Loading…</p>;
  if (items.length === 0) return <p className="muted empty">There is no phone number to show here yet.</p>;

  const byDomain = new Map<string, PublicNumber[]>();
  for (const item of [...items].sort((x, y) => Number(y.isMarketplace) - Number(x.isMarketplace))) {
    const key = item.domainName ?? "Other";
    byDomain.set(key, [...(byDomain.get(key) ?? []), item]);
  }
  return (
    <div className="call-page">
      <h1>Call us</h1>
      <p className="muted">Our AI receptionist answers day and night.</p>
      {[...byDomain.entries()]
        .sort(([x], [y]) => x.localeCompare(y))
        .map(([domain, list]) => (
          <section key={domain}>
            {!id && <h3>{domain}</h3>}
            {list.map((item) => (
              <NumberCard key={item.id} item={item} />
            ))}
          </section>
        ))}
    </div>
  );
}
