import type { ServerEvent } from "../types";
import { AudioQueuePlayer } from "./audioPlayer";
import { MicrophoneError, type VoiceClient, type VoiceClientHandlers } from "./VoiceClient";

const CHUNK_MS = 250;

/** Captures the mic with MediaRecorder and streams it over our WebSocket (backend relays to Deepgram). */
export class BrowserDeepgramClient implements VoiceClient {
  private socket: WebSocket | null = null;
  private recorder: MediaRecorder | null = null;
  private stream: MediaStream | null = null;
  private player: AudioQueuePlayer | null = null;

  constructor(private readonly audioMimeType = "audio/mpeg") {}

  async start(session: { wsUrl: string }, handlers: VoiceClientHandlers): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      throw new MicrophoneError("This browser does not support microphone capture.", "unsupported");
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (err) {
      const denied = err instanceof DOMException && (err.name === "NotAllowedError" || err.name === "SecurityError");
      throw new MicrophoneError(
        denied ? "Microphone permission was denied." : "No microphone is available.",
        denied ? "denied" : "unavailable",
      );
    }

    this.player = new AudioQueuePlayer(this.audioMimeType, handlers.onPlaybackIdle);
    const socket = new WebSocket(session.wsUrl);
    socket.binaryType = "arraybuffer";
    this.socket = socket;

    socket.onmessage = (msg: MessageEvent) => {
      if (msg.data instanceof ArrayBuffer) {
        this.player?.enqueue(msg.data);
        return;
      }
      const event = JSON.parse(msg.data as string) as ServerEvent;
      if (event.type === "assistant.interrupt") this.player?.stop();
      if (event.type === "transcript.partial" && this.player?.isPlaying) {
        // caller is talking over the assistant: stop playback and tell the server
        this.player.stop();
        socket.send(JSON.stringify({ type: "interrupt" }));
      }
      handlers.onEvent(event);
    };
    socket.onerror = () => handlers.onError("Voice connection error.");
    socket.onclose = () => handlers.onClose();

    await new Promise<void>((resolve, reject) => {
      socket.onopen = () => resolve();
      const prevError = socket.onerror;
      socket.onerror = (e) => {
        prevError?.call(socket, e);
        reject(new Error("Could not open the voice connection."));
      };
    });
    socket.onerror = () => handlers.onError("Voice connection error.");

    const recorder = new MediaRecorder(this.stream);
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0 && socket.readyState === WebSocket.OPEN) {
        void e.data.arrayBuffer().then((buf) => socket.send(buf));
      }
    };
    recorder.start(CHUNK_MS);
    this.recorder = recorder;
  }

  stop(): void {
    this.player?.stop();
    if (this.recorder && this.recorder.state !== "inactive") this.recorder.stop();
    this.stream?.getTracks().forEach((t) => t.stop());
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) this.socket.close();
    this.recorder = this.stream = this.socket = this.player = null;
  }
}
