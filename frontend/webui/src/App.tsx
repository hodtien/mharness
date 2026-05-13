import { useEffect, useRef, useState, useCallback } from "react";
import { Navigate, Outlet, Route, Routes, useLocation, useSearchParams } from "react-router-dom";
import {
  api,
  bootstrapAuthSession,
  openWebSocket,
  subscribeAuthChanges,
  type AuthSessionSnapshot,
  type WsHandle,
} from "./api/client";
import { useSession, clearPermission, clearQuestion, clearSelect } from "./store/session";
import Header from "./components/Header";
import LoginScreen from "./components/LoginScreen";
import PermissionModal from "./components/PermissionModal";
import QuestionModal from "./components/QuestionModal";
import SelectModal from "./components/SelectModal";
import Sidebar from "./components/Sidebar";
import ChatPage from "./pages/ChatPage";
import HistoryPage from "./pages/HistoryPage";
import ModesSettingsPage from "./pages/ModesSettingsPage";
import ProviderSettingsPage from "./pages/ProviderSettingsPage";
import ModelsSettingsPage from "./pages/ModelsSettingsPage";
import AgentsSettingsPage from "./pages/AgentsSettingsPage";
import CronSettingsPage from "./pages/CronSettingsPage";
import AutopilotPage from "./pages/PipelinePage";
import TasksPage from "./pages/TasksPage";
import ProjectsPage from "./pages/ProjectsPage";
import PlaceholderPage from "./pages/PlaceholderPage";
import ToastContainer from "./components/ToastContainer";

function RootRedirect() {
  const location = useLocation();
  return <Navigate to={`/chat${location.search}`} replace />;
}

interface LayoutProps {
  onInterrupt: () => void;
  isDefaultPassword?: boolean;
  onLogout?: () => void;
  onPasswordChanged?: () => void;
}

export function AppLayout({
  onInterrupt,
  isDefaultPassword = false,
  onLogout = () => {},
  onPasswordChanged = () => {},
}: LayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const toggleSidebar = useCallback(() => {
    if (window.matchMedia("(min-width: 640px)").matches) {
      setSidebarCollapsed((v) => !v);
      return;
    }
    setSidebarOpen((v) => !v);
  }, []);

  return (
    <div className="flex h-full w-full overflow-hidden">
      <Sidebar open={sidebarOpen} collapsed={sidebarCollapsed} onClose={() => setSidebarOpen(false)} />
      <div className="flex flex-1 flex-col min-w-0">
        <Header
          onToggleSidebar={toggleSidebar}
          onInterrupt={onInterrupt}
          isDefaultPassword={isDefaultPassword}
          onLogout={onLogout}
          onPasswordChanged={onPasswordChanged}
        />
        <main className="flex flex-1 flex-col min-h-0">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export default function App() {
  const wsRef = useRef<WsHandle | null>(null);
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get("project") ?? undefined;
  const [auth, setAuth] = useState<AuthSessionSnapshot & { checking: boolean }>({
    authenticated: false,
    isDefaultPassword: false,
    checking: true,
  });
  const { setStatus, setSessionId, ingest, appendUser, setResumedFrom } = useSession();

  const setupSession = useCallback(
    async (resumeId?: string) => {
      try {
        const result = await api.createSession(resumeId, projectId);
        if (resumeId) {
          setResumedFrom(resumeId);
        }
        setSessionId(result.session_id);
        const ws = openWebSocket(result.session_id, ingest, setStatus);
        wsRef.current = ws;
      } catch (err) {
        console.error("setup failed", err);
        useSession.getState().setError(String(err));
      }
    },
    [ingest, projectId, setStatus, setSessionId, setResumedFrom],
  );

  const reconnectWithSession = useCallback(
    (newSessionId: string, resumeId?: string) => {
      wsRef.current?.close();
      if (resumeId) setResumedFrom(resumeId);
      setSessionId(newSessionId);
      const ws = openWebSocket(newSessionId, ingest, setStatus);
      wsRef.current = ws;
    },
    [ingest, setStatus, setSessionId, setResumedFrom],
  );

  

  useEffect(() => {
    let cancelled = false;
    const unsubscribe = subscribeAuthChanges((snapshot) => {
      setAuth({ ...snapshot, checking: false });
      if (!snapshot.authenticated) {
        wsRef.current?.close();
        wsRef.current = null;
        useSession.getState().reset();
      }
    });
    bootstrapAuthSession()
      .then((snapshot) => {
        if (!cancelled) setAuth({ ...snapshot, checking: false });
      })
      .catch(() => {
        if (!cancelled) setAuth({ authenticated: false, isDefaultPassword: false, checking: false });
      });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  useEffect(() => {
    if (!auth.authenticated) return;
    setupSession();
    return () => wsRef.current?.close();
  }, [auth.authenticated, setupSession]);

  const handleAuthenticated = useCallback((snapshot: AuthSessionSnapshot) => {
    setAuth({ ...snapshot, checking: false });
  }, []);

  const handlePasswordChanged = useCallback(() => {
    setAuth((current) => ({ ...current, isDefaultPassword: false }));
  }, []);

  const handleLogout = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    void api.logout();
  }, []);

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

  if (auth.checking) {
    return (
      <div className="flex h-full items-center justify-center bg-[var(--bg)] text-sm text-[var(--text-dim)]">
        Checking session...
      </div>
    );
  }

  if (!auth.authenticated) {
    return <LoginScreen onAuthenticated={handleAuthenticated} />;
  }

  return (
    <>
      <Routes>
        <Route
          element={
            <AppLayout
              onInterrupt={sendInterrupt}
              isDefaultPassword={auth.isDefaultPassword}
              onLogout={handleLogout}
              onPasswordChanged={handlePasswordChanged}
            />
          }
        >
          <Route path="/" element={<RootRedirect />} />
          <Route path="/chat" element={<ChatPage onSend={sendLine} />} />
          <Route path="/history" element={<HistoryPage onResume={reconnectWithSession} />} />
          <Route path="/autopilot" element={<AutopilotPage />} />
          <Route path="/pipeline" element={<Navigate to="/autopilot" replace />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route
            path="/settings/modes"
            element={<ModesSettingsPage />}
          />
          <Route
            path="/settings/provider"
            element={<ProviderSettingsPage />}
          />
          <Route
            path="/settings/models"
            element={<ModelsSettingsPage />}
          />
          <Route
            path="/settings/agents"
            element={<AgentsSettingsPage />}
          />
          <Route
            path="/settings/cron"
            element={<CronSettingsPage />}
          />
          <Route
            path="/settings/*"
            element={<PlaceholderPage title="Settings" description="Provider, model, and agent settings." />}
          />
          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Route>
      </Routes>

      <PermissionModal onRespond={sendPermission} />
      <QuestionModal onRespond={sendQuestionAnswer} />
      <SelectModal onSelect={sendSelectChoice} />
      <ToastContainer />
    </>
  );
}
