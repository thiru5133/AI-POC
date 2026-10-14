import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { session } from "../services/apiClient";
import { McpPage } from "./McpPage";

const secretKey = { name: "X-API-Key", secret: true, value: null, hasValue: true };

const server = (overrides: Record<string, unknown> = {}) => ({
  id: "s1",
  name: "Hotel bookings",
  url: "http://host.docker.internal:8101/mcp",
  enabled: true,
  headers: [secretKey],
  transport: "streamable_http",
  timeoutSeconds: 15,
  createdAt: "2026-10-11T10:00:00",
  ...overrides,
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const bodyOf = (call: unknown[]) => JSON.parse(String((call[1] as RequestInit).body));

describe("McpPage", () => {
  let fetchMock: MockInstance<typeof fetch>;

  beforeEach(() => {
    session.setToken("tok");
    fetchMock = vi.spyOn(globalThis, "fetch");
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists servers with their header names but never a secret value", async () => {
    fetchMock.mockResolvedValueOnce(
      json([server({ headers: [secretKey, { name: "X-Env", secret: false, value: "prod", hasValue: true }] })]),
    );
    render(<McpPage />);
    expect(await screen.findByText("Hotel bookings")).toBeInTheDocument();
    expect(screen.getByText("X-API-Key (secret), X-Env")).toBeInTheDocument();
    expect(screen.getByText("Streamable HTTP · 15s timeout")).toBeInTheDocument();
    expect(screen.getByText("Enabled")).toBeInTheDocument();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/org/mcp-servers");
  });

  it("adds a server with preset and custom headers, transport and timeout", async () => {
    fetchMock
      .mockResolvedValueOnce(json([]))
      .mockResolvedValueOnce(json(server(), 201))
      .mockResolvedValueOnce(json([server()]));
    render(<McpPage />);
    await screen.findByText(/No MCP servers connected yet/);

    await userEvent.type(screen.getByLabelText("Name"), "Hotel bookings");
    await userEvent.type(screen.getByLabelText("Server URL"), "http://host.docker.internal:8101/mcp");
    await userEvent.selectOptions(screen.getByLabelText("Transport"), "sse");
    await userEvent.clear(screen.getByLabelText("Timeout (seconds)"));
    await userEvent.type(screen.getByLabelText("Timeout (seconds)"), "30");

    await userEvent.click(screen.getByRole("button", { name: "+ API key" }));
    await userEvent.click(screen.getByRole("button", { name: "+ Custom header" }));
    const names = screen.getAllByLabelText("Header name");
    const values = screen.getAllByLabelText("Header value");
    expect(names[0]).toHaveValue("X-API-Key");
    expect(values[0]).toHaveAttribute("type", "password"); // presets start as secrets
    await userEvent.type(values[0], "key-123");
    await userEvent.type(names[1], "X-Region");
    await userEvent.type(values[1], "emea");
    expect(values[1]).toHaveAttribute("type", "text"); // custom headers start visible
    await userEvent.click(screen.getByRole("button", { name: "Add server" }));

    expect(await screen.findByText("Hotel bookings", { selector: "strong" })).toBeInTheDocument();
    expect(fetchMock.mock.calls[1][0]).toBe("/api/org/mcp-servers");
    expect(bodyOf(fetchMock.mock.calls[1])).toEqual({
      name: "Hotel bookings",
      url: "http://host.docker.internal:8101/mcp",
      transport: "sse",
      timeoutSeconds: 30,
      headers: [
        { name: "X-API-Key", secret: true, value: "key-123" },
        { name: "X-Region", secret: false, value: "emea" },
      ],
    });
  });

  it("keeps a saved secret when its value is left blank while editing", async () => {
    fetchMock
      .mockResolvedValueOnce(json([server()]))
      .mockResolvedValueOnce(json(server({ name: "Renamed" })))
      .mockResolvedValueOnce(json([server({ name: "Renamed" })]));
    render(<McpPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));

    expect(screen.getByLabelText("Header value")).toHaveAttribute("placeholder", "Saved: leave blank to keep");
    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.type(screen.getByLabelText("Name"), "Renamed");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(fetchMock.mock.calls[1][1]?.method).toBe("PATCH"));
    expect(bodyOf(fetchMock.mock.calls[1]).headers).toEqual([{ name: "X-API-Key", secret: true }]); // no value sent
  });

  it("removes a header from the list when its row is deleted", async () => {
    fetchMock
      .mockResolvedValueOnce(json([server()]))
      .mockResolvedValueOnce(json(server({ headers: [] })))
      .mockResolvedValueOnce(json([server({ headers: [] })]));
    render(<McpPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove header" }));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(fetchMock.mock.calls[1][1]?.method).toBe("PATCH"));
    expect(bodyOf(fetchMock.mock.calls[1]).headers).toEqual([]);
  });

  it("shows the tools the AI will get when testing a connection", async () => {
    fetchMock.mockResolvedValueOnce(json([server()])).mockResolvedValueOnce(
      json({ ok: true, error: null, tools: [{ name: "book_room", description: "Book a room" }] }),
    );
    render(<McpPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Test" }));

    expect(await screen.findByText("book_room")).toBeInTheDocument();
    expect(screen.getByText(/connected, 1 tool available/)).toBeInTheDocument();
    expect(fetchMock.mock.calls[1][0]).toBe("/api/org/mcp-servers/s1/test");
  });

  it("reports a failed connection test", async () => {
    fetchMock
      .mockResolvedValueOnce(json([server()]))
      .mockResolvedValueOnce(json({ ok: false, error: "The server rejected the credentials (401).", tools: [] }));
    render(<McpPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Test" }));
    expect(await screen.findByText("The server rejected the credentials (401).")).toBeInTheDocument();
  });

  it("disables a server and removes one after confirmation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock
      .mockResolvedValueOnce(json([server()]))
      .mockResolvedValueOnce(json(server({ enabled: false })))
      .mockResolvedValueOnce(json([server({ enabled: false })]))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(json([]));
    render(<McpPage />);

    await userEvent.click(await screen.findByRole("button", { name: "Disable" }));
    expect(await screen.findByText("Disabled")).toBeInTheDocument();
    expect(bodyOf(fetchMock.mock.calls[1])).toEqual({ enabled: false });

    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(screen.queryByText("Hotel bookings", { selector: "strong" })).not.toBeInTheDocument());
    expect(fetchMock.mock.calls[3][1]?.method).toBe("DELETE");
  });

  it("shows server-side validation errors", async () => {
    fetchMock
      .mockResolvedValueOnce(json([]))
      .mockResolvedValueOnce(
        json({ error: { code: "invalid_mcp_url", message: "That address is not allowed", requestId: "r" } }, 422),
      );
    render(<McpPage />);
    await screen.findByText(/No MCP servers connected yet/);
    await userEvent.type(screen.getByLabelText("Name"), "X");
    await userEvent.type(screen.getByLabelText("Server URL"), "http://169.254.169.254/");
    await userEvent.click(screen.getByRole("button", { name: "Add server" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That address is not allowed");
  });
});
