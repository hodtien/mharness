import { useNavigate, useSearchParams } from "react-router-dom";
import HistoryPanel, { type HistorySession } from "../components/HistoryPanel";
import { api } from "../api/client";
import PageHeader from "../components/PageHeader";

interface Props {
  onResume: (sessionId: string, resumeId: string) => void;
}

export default function HistoryPage({ onResume }: Props) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get("project") ?? undefined;

  const handleResume = async (session: HistorySession) => {
    const { session_id } = await api.createSession(session.session_id, projectId);
    onResume(session_id, session.session_id);
    navigate(`/chat${searchParams.toString() ? `?${searchParams.toString()}` : ""}`);
  };

  // The detail drawer already creates the new session via api.createSession
  // before invoking this callback, so we just propagate the ids and navigate.
  const handleResumeFromDrawer = (newSessionId: string, resumeId: string) => {
    onResume(newSessionId, resumeId);
    navigate(`/chat${searchParams.toString() ? `?${searchParams.toString()}` : ""}`);
  };

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <PageHeader
        title="History"
        description="Browse past chat sessions and resume any conversation."
      />
      <div className="flex flex-1 overflow-hidden">
        <HistoryPanel
          onResume={handleResume}
          onResumeFromDrawer={handleResumeFromDrawer}
        />
      </div>
    </div>
  );
}
