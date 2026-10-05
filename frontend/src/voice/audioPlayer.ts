/** Plays MP3 chunks (one per sentence) strictly in order; stop() flushes the queue (barge-in). */
export class AudioQueuePlayer {
  private queue: Blob[] = [];
  private current: HTMLAudioElement | null = null;
  private playing = false;

  constructor(
    private readonly mimeType: string,
    private readonly onIdle: () => void,
  ) {}

  get isPlaying(): boolean {
    return this.playing;
  }

  enqueue(data: ArrayBuffer): void {
    this.queue.push(new Blob([data], { type: this.mimeType }));
    if (!this.playing) void this.playNext();
  }

  stop(): void {
    this.queue = [];
    if (this.current) {
      this.current.pause();
      this.current.src = "";
      this.current = null;
    }
    const wasPlaying = this.playing;
    this.playing = false;
    if (wasPlaying) this.onIdle();
  }

  private async playNext(): Promise<void> {
    const blob = this.queue.shift();
    if (!blob) {
      this.playing = false;
      this.onIdle();
      return;
    }
    this.playing = true;
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    this.current = audio;
    const done = () => {
      URL.revokeObjectURL(url);
      if (this.current === audio) void this.playNext();
    };
    audio.onended = done;
    audio.onerror = done;
    try {
      await audio.play();
    } catch {
      done();
    }
  }
}
