import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "../api/client";

// ─── Types ────────────────────────────────────────────────────────────────────

export type RepoTaskStatus =
  | "queued"
  | "accepted"
  | "preparing"
  | "running"
  | "verifying"
  | "repairing"
  | "pr_open"
  | "waiting_ci"
  | "completed"
  | "merged"
  | "failed"
  | "rejected";

export type RepoTaskSource =
  | "github_issue"
  | "github_pr"
  | "manual_idea"
  | "ohmo_request"
  | "claude_code_candidate";

export interface PipelineCard {
  id: string;
  title: string;
  status: RepoTaskStatus;
  source_kind: RepoTaskSource;
  score: number;
  labels: string[];
  created_at: number;
  updated_at: number;
}

export interface JournalEntry {
  timestamp: number;
  kind: string;
  summary: string;
  task_id: string | null;
  metadata: Record<string, unknown>;
}

// ─── Kanban columns ────────────────────────────────────────────────────────────

const COLUMNS: { id: string; label: string; statuses: RepoTaskStatus[] }[] = [
  { id: "queue", label: "Queue", statuses: ["queued", "accepted"] },
  { id: "in_progress", label: "In Progress", statuses: ["preparing", "running", "verifying", "repairing"] },
  { id: "review", label: "Review", statuses: ["pr_open", "waiting_ci"] },
  { id: "done", label: "Done", statuses: ["completed", "merged", "failed", "rejected"] },
];

const SOURCE_LABELS: Record<RepoTaskSource, string> = {
  github_issue: "Issue",
  github_pr: "PR",
  manual_idea: "Idea",
  ohmo_request: "OHMO",
  claude_code_candidate: "Candidate",
};

const SOURCE_COLOR: Record<RepoTaskSource, string> = {
  github_issue: "bg-violet-500/20 text-violet-300 border-violet-500/40",
  github_pr: "bg-blue-500/20 text-blue-300 border-blue-500/40",
  manual_idea: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
  ohmo_request: "bg-amber-500/20 text-amber-300 border-amber-500/40",
  claude_code_candidate: "bg-orange-500/20 text-orange-300 border-orange-500/40",
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function relativeAge(timestamp: number): string {
  const diff = Date.now() / 1000 - timestamp;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return `${Math.floor(diff / 604800)}w ago`;
}

// ─── Card ─────────────────────────────────────────────────────────────────────

function Card({ card, onClick }: { card: PipelineCard; onClick: () => void }) {
  const sourceLabel = SOURCE_LABELS[card.source_kind] ?? card.source_kind;
  const sourceColor = SOURCE_COLOR[card.source_kind] ?? "bg-gray-500/20 text-gray-300 border-gray-500/40";

  return (
    <button
      onClick={onClick}
      className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3 text-left text-sm shadow-sm transition hover:border-[var(--accent)]/40 hover:bg-[var(--panel)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
    >
      <div className="mb-1.5 font-medium leading-snug text-[var(--text)]">{card.title}</div>
      <div className="flex items-center justify-between gap-2">
        <span
          className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${sourceColor}`}
        >
          {sourceLabel}
        </span>
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-mono text-[var(--text-dim)]">{card.score}</span>
          <span className="text-[11px] text-[var(--text-dim)]">{relativeAge(card.created_at)}</span>
        </div>
      </div>
    </button>
  );
}

// ─── Drawer ───────────────────────────────────────────────────────────────────

interface DrawerProps {
  card: PipelineCard | null;
  journal: JournalEntry[];
  onClose: () => void;
  onAction: (cardId: string, action: "accept" | "reject" | "retry") => void;
  loadingAction: boolean;
}

function Drawer({ card, journal, onClose, onAction, loadingAction }: DrawerProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (card) {
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }
  }, [card, onClose]);

  if (!card) return null;

  const cardJournal = journal.filter(
    (e) => e.task_id === card.id || e.summary.toLowerCase().includes(card.title.toLowerCase().slice(0, 30)),
  );

  const sourceLabel = SOURCE_LABELS[card.source_kind] ?? card.source_kind;
  const sourceColor = SOURCE_COLOR[card.source_kind] ?? "bg-gray-500/20 text-gray-300 border-gray-500/40";

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/50"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <div
        className="fixed bottom-0 right-0 top-0 z-50 flex w-full max-w-lg flex-col border-l border-[var(--border)] bg-[var(--panel)] shadow-2xl sm:bottom-auto"
        role="dialog"
        aria-modal="true"
        aria-label="Card detail"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-[var(--border)] p-4">
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-semibold leading-snug text-[var(--text)]">{card.title}</h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <span className={`rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${sourceColor}`}>
                {sourceLabel}
              </span>
              <span className="text-[11px] font-mono text-[var(--text-dim)]">#{card.id.slice(0, 8)}</span>
              <span className="rounded border border-[var(--border)] bg-[var(--panel-2)] px-1.5 py-0.5 text-[10px] text-[var(--text-dim)]">
                {card.status}
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 rounded-md border border-[var(--border)] bg-[var(--panel-2)] p-1.5 text-sm text-[var(--text-dim)] transition hover:border-[var(--accent)]/40 hover:text-[var(--text)]"
            aria-label="Close drawer"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Score */}
          <div className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3">
            <div className="text-[10px] uppercase tracking-wider text-[var(--text-dim)] mb-1">Score</div>
            <div className="text-2xl font-bold font-mono text-[var(--accent)]">{card.score}</div>
          </div>

          {/* Labels */}
          {card.labels.length > 0 && (
            <div>
              <div className="mb-1.5 text-[10px] uppercase tracking-wider text-[var(--text-dim)]">Labels</div>
              <div className="flex flex-wrap gap-1.5">
                {card.labels.map((label) => (
                  <span
                    key={label}
                    className="rounded-full border border-[var(--border)] bg-[var(--panel-2)] px-2 py-0.5 text-[11px] text-[var(--text)]"
                  >
                    {label}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Age */}
          <div className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3 text-sm">
            <div className="mb-0.5 text-[10px] uppercase tracking-wider text-[var(--text-dim)]">Created</div>
            <div className="text-[var(--text)]">{relativeAge(card.created_at)}</div>
          </div>

          {/* Journal */}
          <div>
            <div className="mb-2 text-[10px] uppercase tracking-wider text-[var(--text-dim)]">
              Journal ({cardJournal.length})
            </div>
            {cardJournal.length === 0 ? (
              <div className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3 text-sm text-[var(--text-dim)]">
                No journal entries.
              </div>
            ) : (
              <div className="space-y-1.5">
                {cardJournal.slice(0, 20).map((entry, idx) => (
                  <div
                    key={idx}
                    className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] p-2"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="text-[11px] font-medium text-[var(--text)]">{entry.summary}</div>
                      <div className="shrink-0 text-[10px] text-[var(--text-dim)]">
                        {relativeAge(entry.timestamp)}
                      </div>
                    </div>
                    <div className="mt-0.5 text-[10px] text-[var(--text-dim)]">
                      {entry.kind}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-2 border-t border-[var(--border)] p-4">
          <button
            onClick={() => onAction(card.id, "accept")}
            disabled={loadingAction}
            className="flex-1 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-40"
          >
            Accept
          </button>
          <button
            onClick={() => onAction(card.id, "reject")}
            disabled={loadingAction}
            className="flex-1 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm font-medium text-red-300 transition hover:bg-red-500/20 disabled:opacity-40"
          >
            Reject
          </button>
          <button
            onClick={() => onAction(card.id, "retry")}
            disabled={loadingAction}
            className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm font-medium text-[var(--text)] transition hover:border-[var(--accent)]/40 disabled:opacity-40"
          >
            Retry
          </button>
        </div>
      </div>
    </>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function PipelinePage() {
  const [cards, setCards] = useState<PipelineCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCard, setSelectedCard] = useState<PipelineCard | null>(null);
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [loadingAction, setLoadingAction] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      apiFetch<{ cards: PipelineCard[]; updated_at: number }>("/api/pipeline/cards"),
      apiFetch<{ entries: JournalEntry[] }>("/api/pipeline/journal?limit=100"),
    ])
      .then(([cardsData, journalData]) => {
        if (cancelled) return;
        setCards(cardsData.cards);
        setJournal(journalData.entries);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleAction = useCallback(
    async (cardId: string, action: "accept" | "reject" | "retry") => {
      setLoadingAction(true);
      try {
        await apiFetch(`/api/pipeline/cards/${encodeURIComponent(cardId)}/action`, {
          method: "POST",
          body: JSON.stringify({ action }),
          headers: { "Content-Type": "application/json" },
        });
        setSelectedCard(null);
        // Refresh cards
        const data = await apiFetch<{ cards: PipelineCard[]; updated_at: number }>("/api/pipeline/cards");
        setCards(data.cards);
      } catch (err) {
        console.error("action failed:", err);
      } finally {
        setLoadingAction(false);
      }
    },
    [],
  );

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <span className="text-sm text-[var(--text-dim)]">Loading pipeline…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden">
      <div className="flex flex-1 overflow-x-auto overflow-y-hidden p-4 gap-4">
        {COLUMNS.map((col) => {
          const colCards = cards.filter((c) => col.statuses.includes(c.status));
          return (
            <div
              key={col.id}
              className="flex w-72 shrink-0 flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--panel)]"
            >
              {/* Column header */}
              <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-dim)]">
                  {col.label}
                </span>
                <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-[var(--panel-2)] px-1.5 text-[10px] font-medium text-[var(--text-dim)]">
                  {colCards.length}
                </span>
              </div>

              {/* Cards */}
              <div className="flex-1 overflow-y-auto p-2 space-y-2">
                {colCards.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-[var(--border)] p-4 text-center text-xs text-[var(--text-dim)]">
                    No cards
                  </div>
                ) : (
                  colCards.map((card) => (
                    <Card
                      key={card.id}
                      card={card}
                      onClick={() => setSelectedCard(card)}
                    />
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>

      <Drawer
        card={selectedCard}
        journal={journal}
        onClose={() => setSelectedCard(null)}
        onAction={handleAction}
        loadingAction={loadingAction}
      />
    </div>
  );
}