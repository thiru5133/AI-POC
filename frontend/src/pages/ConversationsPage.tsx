import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";
import { ApiError } from "../services/apiClient";
import { conversationService } from "../services/conversationService";
import type { ConversationDetail, ConversationSummary } from "../types";
import { formatDateTime } from "../utils/date";

const PAGE_SIZE = 30;

/** Every call and chat of the organization is saved; this page is where an admin reads them back. */
export function ConversationsPage() {
  const { id } = useParams();
  const [items, setItems] = useState<ConversationSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const loadFirstPage = useCallback(async () => {
    try {
      const page = await conversationService.list(0, PAGE_SIZE);
      setItems(page.items);
      setTotal(page.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load your conversations");
    }
  }, []);

  useEffect(() => {
    void loadFirstPage();
  }, [loadFirstPage]);

  useEffect(() => {
    setDetail(null);
    setDetailError(null);
    if (!id) return;
    let active = true;
    conversationService
      .get(id)
      .then((d) => active && setDetail(d))
      .catch((err) => active && setDetailError(err instanceof ApiError ? err.message : "Could not load that conversation"));
    return () => {
      active = false;
    };
  }, [id]);

  async function loadMore() {
    if (!items) return;
    setLoadingMore(true);
    try {
      const page = await conversationService.list(items.length, PAGE_SIZE);
      setItems((current) => [...(current ?? []), ...page.items]);
      setTotal(page.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load more conversations");
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Conversations"
        subtitle="Every call and chat with your receptionist is saved here"
        actions={items ? <span className="badge">{total} saved</span> : undefined}
      />
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="history">
        <nav className="card history-list" aria-label="Saved conversations">
          {items === null && !error && <p className="muted">Loading…</p>}
          {items?.length === 0 && (
            <p className="muted empty">
              No conversations yet. Start one from <Link to="/chat">Chat</Link>.
            </p>
          )}
          {items?.map((c) => (
            <Link key={c.id} to={`/conversations/${c.id}`} className={`history-item${c.id === id ? " active" : ""}`}>
              <span className="when">{formatDateTime(c.startedAt)}</span>
              <span className="preview">{c.preview || "(no message)"}</span>
              <span className="meta">
                {c.messageCount} message{c.messageCount === 1 ? "" : "s"}
              </span>
            </Link>
          ))}
          {items && items.length < total && (
            <button type="button" className="secondary" disabled={loadingMore} onClick={() => void loadMore()}>
              {loadingMore ? "Loading…" : "Load more"}
            </button>
          )}
        </nav>

        <div className="card history-detail">
          {!id && <p className="muted empty">Select a conversation to read it.</p>}
          {id && !detail && !detailError && <p className="muted">Loading…</p>}
          {detailError && (
            <p className="error" role="alert">
              {detailError}
            </p>
          )}
          {detail && (
            <>
              <h2>Conversation</h2>
              <p className="muted">Started {formatDateTime(detail.startedAt)}</p>
              <ul className="transcript" aria-label="Conversation transcript">
                {detail.messages.map((m, i) => (
                  <li key={`${m.createdAt}-${i}`} className={`bubble ${m.role}`}>
                    <span className="who">{m.role === "user" ? "Caller" : "Receptionist"}</span>
                    <span>{m.text}</span>
                    <span className="time">{formatDateTime(m.createdAt)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
    </>
  );
}
