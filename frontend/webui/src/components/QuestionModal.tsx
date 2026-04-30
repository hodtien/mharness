import { useState } from "react";
import { useSession } from "../store/session";

interface Props {
  onRespond: (request_id: string, answer: string) => void;
}

export default function QuestionModal({ onRespond }: Props) {
  const req = useSession((s) => s.pendingQuestion);
  const [answer, setAnswer] = useState("");
  if (!req) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-4 sm:items-center">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-5 shadow-2xl">
        <div className="mb-2 text-xs uppercase tracking-wider text-[var(--accent)]">
          Agent question
        </div>
        <div className="mb-4 text-sm">{req.question}</div>
        <textarea
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          rows={3}
          className="mb-3 w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] placeholder:text-[var(--text-dim)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
          placeholder="Type your answer…"
          autoFocus
        />
        <div className="flex gap-2">
          <button
            onClick={() => {
              onRespond(req.request_id, answer.trim());
              setAnswer("");
            }}
            className="flex-1 rounded-lg bg-[var(--accent-strong)] px-3 py-2 text-sm font-semibold text-white hover:bg-[var(--accent)]"
          >
            Submit
          </button>
        </div>
      </div>
    </div>
  );
}
