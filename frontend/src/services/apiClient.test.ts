import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { apiFetch, refreshSession, session } from "./apiClient";
import { authService } from "./authService";

const user = { id: "u1", name: "Asha", email: "a@x.com", role: "admin", status: "active", tenantId: "t1" };

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("apiClient auth handling", () => {
  let fetchMock: MockInstance<typeof fetch>;

  beforeEach(() => {
    fetchMock = vi.spyOn(globalThis, "fetch");
    session.setToken(null);
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sends the bearer token and includes cookies after login", async () => {
    fetchMock.mockResolvedValueOnce(json({ accessToken: "tok-1", user }));
    await authService.login("a@x.com", "secret-pass");

    fetchMock.mockResolvedValueOnce(json({ ok: true }));
    await apiFetch("/api/anything");

    const [, init] = fetchMock.mock.calls[1];
    expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer tok-1");
    expect(init?.credentials).toBe("include");
  });

  it("refreshes once on 401 and retries the request", async () => {
    session.setToken("expired");
    fetchMock
      .mockResolvedValueOnce(json({ error: { code: "unauthorized", message: "x", requestId: "r" } }, 401))
      .mockResolvedValueOnce(json({ accessToken: "fresh", user }))
      .mockResolvedValueOnce(json({ value: 42 }));

    await expect(apiFetch<{ value: number }>("/api/data")).resolves.toEqual({ value: 42 });

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(["/api/data", "/api/auth/refresh", "/api/data"]);
    const retryHeaders = fetchMock.mock.calls[2][1]?.headers as Record<string, string>;
    expect(retryHeaders.Authorization).toBe("Bearer fresh");
  });

  it("notifies the session listener and surfaces the 401 when refresh fails", async () => {
    const listener = vi.fn();
    const off = session.onChange(listener);
    session.setToken("expired");
    fetchMock
      .mockResolvedValueOnce(json({ error: { code: "unauthorized", message: "nope", requestId: "r" } }, 401))
      .mockResolvedValueOnce(json({ error: { code: "unauthorized", message: "gone", requestId: "r" } }, 401));

    await expect(apiFetch("/api/data")).rejects.toMatchObject({ status: 401 });
    expect(listener).toHaveBeenCalledWith(null);
    off();
  });

  it("shares one in-flight refresh between concurrent callers", async () => {
    fetchMock.mockResolvedValue(json({ accessToken: "fresh", user }));
    const [a, b] = await Promise.all([refreshSession(), refreshSession()]);
    expect(a).toBe(b);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("handles 204 responses without parsing a body", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(apiFetch<void>("/api/auth/logout", { method: "POST" })).resolves.toBeUndefined();
  });

  it("does not try to refresh for /api/auth/ calls", async () => {
    session.setToken("tok");
    fetchMock.mockResolvedValueOnce(
      json({ error: { code: "unauthorized", message: "Invalid email or password", requestId: "r" } }, 401),
    );
    await expect(authService.login("a@x.com", "bad")).rejects.toMatchObject({ message: "Invalid email or password" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
