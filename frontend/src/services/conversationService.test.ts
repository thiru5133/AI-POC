import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./apiClient";
import { conversationService } from "./conversationService";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

afterEach(() => vi.restoreAllMocks());

describe("conversationService", () => {
  it("creates a conversation", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ id: "c1", greeting: "Hi" }));
    await expect(conversationService.create()).resolves.toEqual({ id: "c1", greeting: "Hi" });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/conversations");
  });

  it("sends a message", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ reply: "2 PM" }));
    await expect(conversationService.sendMessage("c1", "check-in?")).resolves.toEqual({ reply: "2 PM" });
    expect(JSON.parse(fetchMock.mock.calls[0][1]!.body as string)).toEqual({ text: "check-in?" });
  });

  it("maps the backend error envelope to ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json({ error: { code: "not_found", message: "Conversation not found", requestId: "r" } }, 404),
    );
    await expect(conversationService.sendMessage("x", "hi")).rejects.toMatchObject({
      code: "not_found",
      status: 404,
      message: "Conversation not found",
    });
  });

  it("reports network failures", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("failed"));
    await expect(conversationService.create()).rejects.toBeInstanceOf(ApiError);
  });
});
