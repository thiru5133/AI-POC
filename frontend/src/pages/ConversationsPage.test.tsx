import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { session } from "../services/apiClient";
import { ConversationsPage } from "./ConversationsPage";

const summary = (id: string, preview: string, messageCount = 3) => ({
  id,
  startedAt: "2026-10-11T10:00:00",
  status: "active",
  messageCount,
  lastMessageAt: "2026-10-11T10:02:00",
  preview,
});

const detail = (id: string) => ({
  id,
  status: "active",
  startedAt: "2026-10-11T10:00:00",
  messages: [
    { role: "assistant", text: "Welcome to Acme Hotel.", intent: null, createdAt: "2026-10-11T10:00:00" },
    { role: "user", text: "Do you have suites free?", intent: null, createdAt: "2026-10-11T10:00:30" },
    { role: "assistant", text: "Yes, three suites.", intent: null, createdAt: "2026-10-11T10:00:35" },
  ],
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function mountAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/conversations/:id?" element={<ConversationsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ConversationsPage", () => {
  let fetchMock: MockInstance<typeof fetch>;

  beforeEach(() => {
    session.setToken("tok");
    fetchMock = vi.spyOn(globalThis, "fetch");
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists saved conversations and reads one back", async () => {
    fetchMock
      .mockResolvedValueOnce(json({ items: [summary("c1", "Do you have suites free?"), summary("c2", "Where is parking?", 5)], total: 2, limit: 30, offset: 0 }))
      .mockResolvedValueOnce(json(detail("c1")));
    mountAt("/conversations");

    expect(await screen.findByText("Do you have suites free?")).toBeInTheDocument();
    expect(screen.getByText("5 messages")).toBeInTheDocument();
    expect(screen.getByText("2 saved")).toBeInTheDocument();
    expect(screen.getByText("Select a conversation to read it.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("link", { name: /Do you have suites free\?/ }));

    const transcript = await screen.findByRole("list", { name: "Conversation transcript" });
    expect(transcript).toHaveTextContent("Welcome to Acme Hotel.");
    expect(transcript).toHaveTextContent("Yes, three suites.");
    expect(transcript).toHaveTextContent("Caller");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/conversations?limit=30&offset=0");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/conversations/c1");
  });

  it("opens a conversation straight from its link", async () => {
    fetchMock
      .mockResolvedValueOnce(json({ items: [summary("c1", "Do you have suites free?")], total: 1, limit: 30, offset: 0 }))
      .mockResolvedValueOnce(json(detail("c1")));
    mountAt("/conversations/c1");
    expect(await screen.findByText("Yes, three suites.")).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    fetchMock.mockResolvedValueOnce(json({ items: [], total: 0, limit: 30, offset: 0 }));
    mountAt("/conversations");
    expect(await screen.findByText(/No conversations yet/)).toBeInTheDocument();
  });

  it("loads more when there are further pages", async () => {
    fetchMock
      .mockResolvedValueOnce(json({ items: [summary("c1", "First question")], total: 2, limit: 30, offset: 0 }))
      .mockResolvedValueOnce(json({ items: [summary("c2", "Second question")], total: 2, limit: 30, offset: 1 }));
    mountAt("/conversations");
    await userEvent.click(await screen.findByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Second question")).toBeInTheDocument();
    expect(fetchMock.mock.calls[1][0]).toBe("/api/conversations?limit=30&offset=1");
    await waitFor(() => expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument());
  });

  it("reports a conversation that cannot be found", async () => {
    fetchMock
      .mockResolvedValueOnce(json({ items: [], total: 0, limit: 30, offset: 0 }))
      .mockResolvedValueOnce(json({ error: { code: "not_found", message: "Conversation not found", requestId: "r" } }, 404));
    mountAt("/conversations/nope");
    expect(await screen.findByText("Conversation not found")).toBeInTheDocument();
  });
});
