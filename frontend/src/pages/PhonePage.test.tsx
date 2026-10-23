import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { session } from "../services/apiClient";
import { PhonePage } from "./PhonePage";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const settings = (over = {}) => ({
  number: null,
  transferNumber: null,
  provider: "twilio",
  webhookUrl: "https://x.app/api/phone/incoming",
  publicUrl: null,
  domainName: null,
  domainNumber: null,
  ready: true,
  ...over,
});

describe("PhonePage", () => {
  let fetchMock: MockInstance<typeof fetch>;
  beforeEach(() => {
    session.setToken("tok");
    fetchMock = vi.spyOn(globalThis, "fetch");
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows the saved numbers and the Twilio webhook URL", async () => {
    fetchMock.mockResolvedValueOnce(json(settings({ number: "+914412345678", transferNumber: "+919876543210" })));
    render(<PhonePage />);
    expect(await screen.findByDisplayValue("+914412345678")).toBeInTheDocument();
    expect(screen.getByDisplayValue("+919876543210")).toBeInTheDocument();
    expect(screen.getByText("https://x.app/api/phone/incoming")).toBeInTheDocument();
  });

  it("shows the Vapi server URL and instructions when the server uses Vapi", async () => {
    fetchMock.mockResolvedValueOnce(json(settings({ provider: "vapi", webhookUrl: "https://x.app/api/vapi/webhook" })));
    render(<PhonePage />);
    expect(await screen.findByText("Connect it in Vapi")).toBeInTheDocument();
    expect(screen.getByText("https://x.app/api/vapi/webhook")).toBeInTheDocument();
    expect(screen.queryByText("Connect it in Twilio")).not.toBeInTheDocument();
  });

  it("tells the business about its domain's shared line", async () => {
    fetchMock.mockResolvedValueOnce(json(settings({ domainName: "Hotels", domainNumber: "+17692630020" })));
    render(<PhonePage />);
    expect(await screen.findByText("+17692630020")).toBeInTheDocument();
    expect(screen.getByText(/compares every Hotels business/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/business phone number \(optional\)/i)).toBeInTheDocument();
  });

  it("saves the numbers, sending an emptied one as null", async () => {
    fetchMock.mockResolvedValueOnce(json(settings())).mockResolvedValueOnce(json(settings({ number: "+914412345678" })));
    render(<PhonePage />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/business phone number/i), "+914412345678");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[1];
    expect(String(url)).toContain("/api/org/phone");
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({ number: "+914412345678", transferNumber: null });
  });

  it("explains when the server cannot take calls yet and shows save errors", async () => {
    fetchMock
      .mockResolvedValueOnce(json(settings({ ready: false, webhookUrl: null })))
      .mockResolvedValueOnce(json({ error: { code: "number_taken", message: "That number is already used by another business" } }, 409));
    render(<PhonePage />);
    expect(await screen.findByText(/not set up for phone calls yet/i)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/business phone number/i), "+914412345678");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("already used by another business"));
  });
});
