import { useAuth } from "../auth/AuthContext";
import { BusinessPicker } from "../components/BusinessPicker";
import { PageHeader } from "../components/PageHeader";
import { VoiceConsole } from "../features/conversation/VoiceConsole";

/** Chat or talk to a business's AI assistant: customers pick a business, admins test their own. */
export function ChatPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  return (
    <>
      <PageHeader
        title={isAdmin ? "Try your assistant" : "Chat with a business"}
        subtitle={
          isAdmin
            ? "Chat or talk to your AI assistant the way your customers do; it can use the MCP servers you connected"
            : "Ask questions or make a booking, by typing or by voice"
        }
      />
      {isAdmin ? <VoiceConsole /> : <BusinessPicker>{(businessId) => <VoiceConsole key={businessId} />}</BusinessPicker>}
    </>
  );
}
