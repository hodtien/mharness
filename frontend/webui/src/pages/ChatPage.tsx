import Transcript from "../components/Transcript";
import InputBar from "../components/InputBar";
import ChatEmptyState from "../components/ChatEmptyState";
import { useSession } from "../store/session";

interface Props {
  onSend: (text: string) => void;
}

export default function ChatPage({ onSend }: Props) {
  const connectionStatus = useSession((s) => s.connectionStatus);
  const transcript = useSession((s) => s.transcript);

  const isDisconnected = connectionStatus === "closed";
  const hasConversation = transcript.some((item) => item.role === "user" || item.role === "assistant");
  const showEmptyState = connectionStatus === "open" && !hasConversation;

  return (
    <>
      {isDisconnected && (
        <div className="flex items-center gap-2 border-b border-rose-500/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-200">
          <svg
            className="h-4 w-4 animate-spin"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
            />
          </svg>
          <span>Disconnected — attempting to reconnect...</span>
        </div>
      )}
      {showEmptyState ? <ChatEmptyState onSend={onSend} /> : <Transcript />}
      <InputBar onSend={onSend} />
    </>
  );
}
