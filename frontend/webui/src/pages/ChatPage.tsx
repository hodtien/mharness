import Transcript from "../components/Transcript";
import InputBar from "../components/InputBar";
import { useSession } from "../store/session";

interface Props {
  onSend: (text: string) => void;
}

export default function ChatPage({ onSend }: Props) {
  const connectionStatus = useSession((s) => s.connectionStatus);
  const sessionId = useSession((s) => s.sessionId);
  const appState = useSession((s) => s.appState);
  const transcript = useSession((s) => s.transcript);

  const isDisconnected = connectionStatus === "closed";
  const showWelcome = connectionStatus === "open" && transcript.length === 0;

  const truncatedSessionId = sessionId ? `${sessionId.slice(0, 8)}...` : "—";
  const model = appState?.model || "—";

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
      <Transcript hideWelcome={!showWelcome} />
      {showWelcome && (
        <div className="border-b border-[var(--border)] bg-[var(--panel)] px-4 py-3">
          <div className="mx-auto flex max-w-4xl items-center gap-3 text-sm text-[var(--text)]">
            <span className="flex h-2 w-2">
              <span className="absolute inline-flex h-2 w-2 animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
            </span>
            <div>
              <strong className="font-semibold">Connected</strong>
              <span className="ml-3 text-[var(--text-dim)]">
                Session: {truncatedSessionId}
              </span>
              <span className="ml-3 text-[var(--text-dim)]">Model: {model}</span>
            </div>
          </div>
        </div>
      )}
      <InputBar onSend={onSend} />
    </>
  );
}
