import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { session } from "../../services/apiClient";
import { RequestsPage } from "./RequestsPage";

const pending = (id: string, email: string) => ({
  id,
  name: `Name ${id}`,
  email,
  status: "pending",
  rejectionReason: null,
  createdAt: "2026-10-10T10:00:00",
  reviewedAt: null,
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("RequestsPage", () => {
  let fetchMock: MockInstance<typeof fetch>;

  beforeEach(() => {
    session.setToken("tok");
    fetchMock = vi.spyOn(globalThis, "fetch");
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists pending requests and removes one after approving", async () => {
    fetchMock
      .mockResolvedValueOnce(json([pending("1", "one@x.com"), pending("2", "two@x.com")]))
      .mockResolvedValueOnce(json({ ...pending("1", "one@x.com"), status: "active" }));

    render(<RequestsPage />);
    expect(await screen.findByText("one@x.com")).toBeInTheDocument();
    expect(screen.getByText("two@x.com")).toBeInTheDocument();

    await userEvent.click(screen.getAllByRole("button", { name: "Approve" })[0]);

    await waitFor(() => expect(screen.queryByText("one@x.com")).not.toBeInTheDocument());
    expect(screen.getByText("two@x.com")).toBeInTheDocument();
    expect(fetchMock.mock.calls[1][0]).toBe("/api/admin/onboarding-requests/1/approve");
  });

  it("sends the reason when rejecting", async () => {
    vi.spyOn(window, "prompt").mockReturnValue("Not a customer");
    fetchMock
      .mockResolvedValueOnce(json([pending("1", "one@x.com")]))
      .mockResolvedValueOnce(json({ ...pending("1", "one@x.com"), status: "rejected" }));

    render(<RequestsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Reject" }));

    await waitFor(() => expect(screen.getByText("No pending requests.")).toBeInTheDocument());
    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toBe("/api/admin/onboarding-requests/1/reject");
    expect(JSON.parse(init?.body as string)).toEqual({ reason: "Not a customer" });
  });

  it("shows an empty state", async () => {
    fetchMock.mockResolvedValueOnce(json([]));
    render(<RequestsPage />);
    expect(await screen.findByText("No pending requests.")).toBeInTheDocument();
  });
});
