import { useEffect, useRef, useState, useCallback } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api, openWebSocket, type WsHandle } from "./api/client";
import { useSession, clearPermission, clearQuestion, clearSelect } from "./store/session";
import Header from "./components/Header";
import PermissionModal from "./components/PermissionModal";
import QuestionModal from "./components/QuestionModal";
import SelectModal from "./components/SelectModal";
import Sidebar from "./components/Sidebar";
import ChatPage from "./pages/ChatPage";
import PlaceholderPage from "./pages/PlaceholderPage";

function RootRedirect() {
  const location = useLocation();
  return <Navigate to={`/chat${location.search}`} replace />;
}

export default function App() {
  const wsRef = useRef<WsHandle | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { setStatus, ingest, appendUser } = useSession();

  const setupSession = useCallback(async () => {
    try {
      const { session_id } = await api.createSession();
      const ws = openWebSocket(session_id, ingest, setStatus);
      wsRef.current = ws;
    } catch (err) {
      console.error("setup failed", err);
      useSession.getState().setError(String(err));
    }
  }, [ingest, setStatus]);

  useEffect(() => {
    setupSession();
    return () => wsRef.current?.close();
  }, [setupSession]);

  const sendLine = useCallback(
    (text: string) => {
      appendUser(text);
      wsRef.current?.send({ type: "submit_line", line: text });
    },
    [appendUser],
  );

  const sendInterrupt = useCallback(() => {
    wsRef.current?.send({ type: "interrupt" });
  }, []);

  const sendPermission = useCallback((request_id: string, allowed: boolean) => {
    wsRef.current?.send({ type: "permission_response", request_id, allowed });
    clearPermission();
  }, []);

  const sendQuestionAnswer = useCallback((request_id: string, answer: string) => {
    wsRef.current?.send({ type: "question_response", request_id, answer });
    clearQuestion();
  }, []);

  const sendSelectChoice = useCallback((command: string, value: string) => {
    wsRef.current?.send({ type: "apply_select_command", command, value });
    clearSelect();
  }, []);

  return (
    <div className="flex h-full w-full overflow-hidden">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      <div className="flex flex-1 flex-col min-w-0">
        <Header onToggleSidebar={() => setSidebarOpen((v) => !v)} onInterrupt={sendInterrupt} />
        <Routes>
          <Route path="/" element={<RootRedirect />} />
          <Route path="/chat" element={<ChatPage onSend={sendLine} />} />
          <Route
            path="/history"
            element={<PlaceholderPage title="History" description="Chat history will appear here." />}
          />
          <Route
            path="/pipeline"
            element={<PlaceholderPage title="Pipeline" description="Autopilot pipeline dashboard." />}
          />
          <Route
            path="/tasks"
            element={<PlaceholderPage title="Tasks" description="Background task dashboard." />}
          />
          <Route
            path="/settings/*"
            element={<PlaceholderPage title="Settings" description="Provider, model, and agent settings." />}
          />
          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Routes>
      </div>

      <PermissionModal onRespond={sendPermission} />
      <QuestionModal onRespond={sendQuestionAnswer} />
      <SelectModal onSelect={sendSelectChoice} />
    </div>
  );
}
