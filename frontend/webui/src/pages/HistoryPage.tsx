import { useNavigate } from "react-router-dom";
import HistoryPanel, { type HistorySession } from "../components/HistoryPanel";
import { api } from "../api/client";

interface Props {
  onResume: (sessionId: string, resumeId: string) => void;
}

export default function HistoryPage({ onResume }: Props) {
  const navigate = useNavigate();

  const handleResume = async (session: HistorySession) => {
    const { session_id } = await api.createSession(session.session_id);
    onResume(session_id, session.session_id);
    navigate("/chat");
  };

  // The detail drawer already creates the new session via api.createSession
  // before invoking this callback, so we just propagate the ids and navigate.
  const handleResumeFromDrawer = (newSessionId: string, resumeId: string) => {
    onResume(newSessionId, resumeId);
    navigate("/chat");
  };

  return (
    <HistoryPanel
      onResume={handleResume}
      onResumeFromDrawer={handleResumeFromDrawer}
    />
  );
}
