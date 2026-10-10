import { PageHeader } from "../components/PageHeader";
import { VoiceConsole } from "../features/conversation/VoiceConsole";

export function CallPage() {
  return (
    <>
      <PageHeader title="Live call" subtitle="Demo Hotel · talk to the AI receptionist from your browser" />
      <VoiceConsole />
    </>
  );
}
