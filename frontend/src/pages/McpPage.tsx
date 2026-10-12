import { useCallback, useEffect, useState, type FormEvent } from "react";
import { PageHeader } from "../components/PageHeader";
import { ApiError } from "../services/apiClient";
import { mcpService } from "../services/mcpService";
import type { McpServer, McpTestResult, McpTransport } from "../types";

/** One editable header. `saved` marks a secret whose value is stored on the server (and never shown here). */
interface HeaderRow {
  key: number;
  name: string;
  value: string;
  secret: boolean;
  saved: boolean;
}

interface FormState {
  name: string;
  url: string;
  transport: McpTransport;
  timeoutSeconds: number;
  headers: HeaderRow[];
}

const TRANSPORT_LABEL: Record<McpTransport, string> = {
  streamable_http: "Streamable HTTP",
  sse: "SSE (legacy)",
};

let rowKey = 0;
const newRow = (name = "", secret = true): HeaderRow => ({ key: ++rowKey, name, value: "", secret, saved: false });
const emptyForm = (): FormState => ({ name: "", url: "", transport: "streamable_http", timeoutSeconds: 15, headers: [] });

/** Each admin connects their own organization's MCP servers; the AI on their calls can use only these. */
export function McpPage() {
  const [servers, setServers] = useState<McpServer[] | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [editing, setEditing] = useState<McpServer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [results, setResults] = useState<Record<string, McpTestResult>>({});

  const load = useCallback(async () => {
    try {
      setServers(await mcpService.list());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load your MCP servers");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function startEdit(server: McpServer) {
    setEditing(server);
    setForm({
      name: server.name,
      url: server.url,
      transport: server.transport,
      timeoutSeconds: server.timeoutSeconds,
      headers: server.headers.map((h) => ({
        key: ++rowKey,
        name: h.name,
        value: h.value ?? "",
        secret: h.secret,
        saved: h.secret && h.hasValue,
      })),
    });
    setError(null);
  }

  function resetForm() {
    setEditing(null);
    setForm(emptyForm());
  }

  const patchRow = (key: number, changes: Partial<HeaderRow>) =>
    setForm((f) => ({ ...f, headers: f.headers.map((r) => (r.key === key ? { ...r, ...changes } : r)) }));
  const addRow = (row: HeaderRow) => setForm((f) => ({ ...f, headers: [...f.headers, row] }));
  const removeRow = (key: number) => setForm((f) => ({ ...f, headers: f.headers.filter((r) => r.key !== key) }));

  function forgetResult(id: string) {
    setResults((current) => Object.fromEntries(Object.entries(current).filter(([key]) => key !== id)));
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const payload = {
        name: form.name,
        url: form.url,
        transport: form.transport,
        timeoutSeconds: form.timeoutSeconds,
        headers: form.headers
          .filter((r) => r.name.trim())
          .map((r) => ({ name: r.name.trim(), secret: r.secret, ...(r.value ? { value: r.value } : {}) })),
      };
      if (editing) {
        await mcpService.update(editing.id, payload);
        forgetResult(editing.id); // the connection changed, so the earlier test no longer applies
      } else {
        await mcpService.create(payload);
      }
      resetForm();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the MCP server");
    } finally {
      setSaving(false);
    }
  }

  async function run(server: McpServer, action: () => Promise<void>, failure: string) {
    setBusyId(server.id);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : failure);
    } finally {
      setBusyId(null);
    }
  }

  const test = (server: McpServer) =>
    run(
      server,
      async () => {
        const result = await mcpService.test(server.id);
        setResults((current) => ({ ...current, [server.id]: result }));
      },
      "Test failed",
    );

  const toggle = (server: McpServer) =>
    run(
      server,
      async () => {
        await mcpService.update(server.id, { enabled: !server.enabled });
        await load();
      },
      "Could not update the server",
    );

  const remove = (server: McpServer) => {
    if (!window.confirm(`Remove "${server.name}"? The AI will no longer be able to use it.`)) return Promise.resolve();
    return run(
      server,
      async () => {
        await mcpService.remove(server.id);
        if (editing?.id === server.id) resetForm();
        forgetResult(server.id);
        await load();
      },
      "Could not remove the server",
    );
  };

  return (
    <>
      <PageHeader
        title="MCP integration"
        subtitle="Connect your own systems so the AI can look up details and take actions during your calls"
        actions={servers ? <span className="badge">{servers.filter((s) => s.enabled).length} active</span> : undefined}
      />

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <div className="card table-card">
        {servers === null && !error && <p className="muted">Loading…</p>}
        {servers?.length === 0 && <p className="muted empty">No MCP servers connected yet. Add one below.</p>}
        {servers && servers.length > 0 && (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Connection</th>
                  <th>Status</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {servers.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <strong>{s.name}</strong>
                      <div className="muted">
                        {s.headers.length === 0
                          ? "No headers"
                          : s.headers.map((h) => (h.secret ? `${h.name} (secret)` : h.name)).join(", ")}
                      </div>
                    </td>
                    <td>
                      <div className="mono">{s.url}</div>
                      <div className="muted">
                        {TRANSPORT_LABEL[s.transport]} · {s.timeoutSeconds}s timeout
                      </div>
                    </td>
                    <td>
                      <span className={`status-badge ${s.enabled ? "active" : "disabled"}`}>
                        {s.enabled ? "Enabled" : "Disabled"}
                      </span>
                    </td>
                    <td className="actions">
                      <button type="button" className="secondary small" disabled={busyId === s.id} onClick={() => void test(s)}>
                        Test
                      </button>
                      <button type="button" className="secondary small" disabled={busyId === s.id} onClick={() => void toggle(s)}>
                        {s.enabled ? "Disable" : "Enable"}
                      </button>
                      <button type="button" className="secondary small" disabled={busyId === s.id} onClick={() => startEdit(s)}>
                        Edit
                      </button>
                      <button type="button" className="danger small" disabled={busyId === s.id} onClick={() => void remove(s)}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {servers?.map((s) => {
          const result = results[s.id];
          if (!result) return null;
          return (
            <div key={s.id} className="mcp-result" role="status">
              <strong>{s.name}</strong>:{" "}
              {result.ok ? (
                <>
                  connected, {result.tools.length} tool{result.tools.length === 1 ? "" : "s"} available to the AI
                  <ul>
                    {result.tools.map((t) => (
                      <li key={t.name}>
                        <code>{t.name}</code> <span className="muted">{t.description}</span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <span className="error">{result.error}</span>
              )}
            </div>
          );
        })}
      </div>

      <form className="card form mcp-form" onSubmit={onSubmit}>
        <h2>{editing ? `Edit ${editing.name}` : "Add an MCP server"}</h2>
        <p className="muted">
          These connections belong to your organization: other organizations cannot see them, and the AI on their calls
          cannot use them.
        </p>
        <label>
          Name
          <input
            required
            maxLength={100}
            placeholder="e.g. Hotel bookings"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </label>
        <label>
          Server URL
          <input
            required
            type="url"
            maxLength={500}
            placeholder="https://example.com/mcp"
            value={form.url}
            onChange={(e) => setForm({ ...form, url: e.target.value })}
          />
        </label>
        <div className="row">
          <label>
            Transport
            <select value={form.transport} onChange={(e) => setForm({ ...form, transport: e.target.value as McpTransport })}>
              <option value="streamable_http">Streamable HTTP</option>
              <option value="sse">SSE (legacy)</option>
            </select>
          </label>
          <label>
            Timeout (seconds)
            <input
              type="number"
              min={1}
              max={60}
              required
              value={form.timeoutSeconds}
              onChange={(e) => setForm({ ...form, timeoutSeconds: Number(e.target.value) })}
            />
          </label>
        </div>

        <fieldset className="mcp-headers">
          <legend>Request headers</legend>
          <p className="muted">
            Sent with every request to this server, for example an API key or a bearer token. Secret values are
            encrypted and never shown again.
          </p>
          {form.headers.map((row) => (
            <div className="mcp-header-row" key={row.key}>
              <input
                aria-label="Header name"
                placeholder="Header name"
                maxLength={60}
                value={row.name}
                onChange={(e) => patchRow(row.key, { name: e.target.value })}
              />
              <input
                aria-label="Header value"
                type={row.secret ? "password" : "text"}
                autoComplete="off"
                maxLength={2000}
                placeholder={row.saved ? "Saved: leave blank to keep" : "Value"}
                value={row.value}
                onChange={(e) => patchRow(row.key, { value: e.target.value })}
              />
              <label className="inline">
                <input
                  type="checkbox"
                  checked={row.secret}
                  onChange={(e) => patchRow(row.key, { secret: e.target.checked })}
                />
                Secret
              </label>
              <button type="button" className="secondary small" aria-label="Remove header" onClick={() => removeRow(row.key)}>
                ×
              </button>
            </div>
          ))}
          <div className="row">
            <button type="button" className="secondary small" onClick={() => addRow(newRow("X-API-Key"))}>
              + API key
            </button>
            <button type="button" className="secondary small" onClick={() => addRow(newRow("Authorization"))}>
              + Bearer / Authorization
            </button>
            <button type="button" className="secondary small" onClick={() => addRow(newRow("", false))}>
              + Custom header
            </button>
          </div>
        </fieldset>

        <p className="muted">
          Running locally in Docker? Use <code>host.docker.internal</code> instead of <code>localhost</code> in the URL.
          For a bearer token, enter the whole value, e.g. <code>Bearer your-token</code>.
        </p>
        <div className="row">
          <button type="submit" className="primary" disabled={saving}>
            {saving ? "Saving…" : editing ? "Save changes" : "Add server"}
          </button>
          {editing && (
            <button type="button" className="secondary" onClick={resetForm}>
              Cancel
            </button>
          )}
        </div>
      </form>
    </>
  );
}
