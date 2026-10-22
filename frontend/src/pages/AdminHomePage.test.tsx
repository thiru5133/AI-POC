import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { session } from "../services/apiClient";
import { AdminHomePage } from "./AdminHomePage";

vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { name: "Grand kumar" } }) }));

const usage = { periodDays: 30, conversations: 12, messages: 48, voiceMinutes: 7.5, toolCalls: 20, bookings: 5, confirmations: 4 };

describe("AdminHomePage", () => {
  let fetchSpy: MockInstance;
  beforeEach(() => {
    session.setToken("t");
    fetchSpy = vi.spyOn(globalThis, "fetch");
  });
  afterEach(() => {
    fetchSpy.mockRestore();
    session.setToken(null);
  });

  it("shows the business's usage for the last 30 days", async () => {
    fetchSpy.mockResolvedValue(new Response(JSON.stringify(usage), { status: 200, headers: { "Content-Type": "application/json" } }));
    render(<MemoryRouter><AdminHomePage /></MemoryRouter>);
    expect(await screen.findByText("48")).toBeInTheDocument();
    expect(screen.getByText("7.5")).toBeInTheDocument();
    expect(screen.getByText("Bookings (estimated)")).toBeInTheDocument();
    expect(String(fetchSpy.mock.calls[0][0])).toContain("/api/org/usage?days=30");
  });

  it("shows an error when usage cannot be loaded", async () => {
    fetchSpy.mockResolvedValue(new Response(JSON.stringify({ error: { message: "Boom" } }), { status: 500, headers: { "Content-Type": "application/json" } }));
    render(<MemoryRouter><AdminHomePage /></MemoryRouter>);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
