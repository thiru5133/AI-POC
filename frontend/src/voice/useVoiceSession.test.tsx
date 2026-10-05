import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VoiceConsole } from "../features/conversation/VoiceConsole";
import { conversationService } from "../services/conversationService";
import { MicrophoneError, type VoiceClient, type VoiceClientHandlers } from "./VoiceClient";

afterEach(() => vi.restoreAllMocks());

function mockBackend() {
  vi.spyOn(conversationService, "create").mockResolvedValue({ id: "c1", greeting: "Welcome" });
  vi.spyOn(conversationService, "createVoiceSession").mockResolvedValue({
    conversationId: "c1",
    transport: "websocket",
    wsPath: "/ws/voice/c1",
    audio: { mimeType: "audio/mpeg" },
  });
}

class FakeClient implements VoiceClient {
  handlers!: VoiceClientHandlers;
  stopped = false;
  constructor(private readonly failWith?: Error) {}
  async start(_s: { wsUrl: string }, handlers: VoiceClientHandlers) {
    if (this.failWith) throw this.failWith;
    this.handlers = handlers;
  }
  stop() {
    this.stopped = true;
  }
}

describe("VoiceConsole / useVoiceSession", () => {
  it("starts a call and renders streamed transcript events", async () => {
    mockBackend();
    const client = new FakeClient();
    render(<VoiceConsole createClient={() => client} toWsUrl={(p) => `ws://test${p}`} />);

    await userEvent.click(screen.getByRole("button", { name: "Start call" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Listening"));

    act(() => {
      client.handlers.onEvent({ type: "assistant.text", text: "Welcome to Demo Hotel." });
      client.handlers.onEvent({ type: "transcript.partial", text: "what time" });
    });
    expect(screen.getByText("what time")).toBeInTheDocument();

    act(() => {
      client.handlers.onEvent({ type: "transcript.final", text: "what time is check-in" });
      client.handlers.onEvent({ type: "assistant.text", text: "Check-in starts at 2 PM." });
    });
    expect(screen.getByText("what time is check-in")).toBeInTheDocument();
    expect(screen.getByText("Check-in starts at 2 PM.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Speaking");

    await userEvent.click(screen.getByRole("button", { name: "End call" }));
    expect(client.stopped).toBe(true);
    expect(screen.getByRole("status")).toHaveTextContent("Ready");
  });

  it("shows an error when microphone permission is denied", async () => {
    mockBackend();
    const client = new FakeClient(new MicrophoneError("Microphone permission was denied.", "denied"));
    render(<VoiceConsole createClient={() => client} />);
    await userEvent.click(screen.getByRole("button", { name: "Start call" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone permission was denied.");
    expect(screen.getByRole("status")).toHaveTextContent("Error");
    expect(screen.getByRole("button", { name: "Start call" })).toBeEnabled(); // can retry
  });

  it("shows an error when the backend is unreachable", async () => {
    vi.spyOn(conversationService, "create").mockRejectedValue(new Error("Cannot reach the server"));
    render(<VoiceConsole createClient={() => new FakeClient()} />);
    await userEvent.click(screen.getByRole("button", { name: "Start call" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the server");
  });

  it("shows a connecting state while starting", async () => {
    vi.spyOn(conversationService, "create").mockReturnValue(new Promise(() => {}));
    render(<VoiceConsole createClient={() => new FakeClient()} />);
    await userEvent.click(screen.getByRole("button", { name: "Start call" }));
    expect(screen.getByRole("status")).toHaveTextContent("Connecting");
    expect(screen.getByRole("button", { name: "Connecting…" })).toBeDisabled();
  });

  it("supports the text fallback with loading state", async () => {
    vi.spyOn(conversationService, "create").mockResolvedValue({ id: "c1", greeting: "Welcome" });
    vi.spyOn(conversationService, "sendMessage").mockResolvedValue({ reply: "Check-in starts at 2 PM." });
    render(<VoiceConsole />);
    await userEvent.type(screen.getByLabelText("Type a message"), "check-in time?");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Check-in starts at 2 PM.")).toBeInTheDocument();
    expect(screen.getByText("Welcome")).toBeInTheDocument();
    expect(screen.getByText("check-in time?")).toBeInTheDocument();
  });
});
