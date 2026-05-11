import { useEffect, useState, useRef, useCallback } from "react";
import { HeroBackground } from "./components/HeroBackground";
import { PipelineAnimation } from "./components/PipelineAnimation";
import type { Snapshot, TaskCard, JournalEntry } from "./types";
import { STATUS_LABELS, STATUS_COLORS, KANBAN_GROUPS, ACTIVE_STATUSES } from "./types";

/* ── Helpers ─────────────────────────────────── */

function fmtAgo(ts?: number): string {
  if (!ts) return "-";
  const delta = Math.max(0, Math.floor(Date.now() / 1000 - (ts || 0)));
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

function statusBadgeClass(status: string): string {
  if (["running", "completed", "merged", "preparing"].includes(status)) return "badge-teal";
  if (["repairing"].includes(status)) return "badge-orange";
  if (["accepted", "pr_open", "code_review"].includes(status)) return "badge-violet";
  if (["failed", "rejected", "killed"].includes(status)) return "badge-red";
  if (["verifying", "waiting_ci"].includes(status)) return "badge-blue";
  if (["superseded"].includes(status)) return "badge-amber";
  return "badge-gray";
}

/** Spinner SVG for active cards */
function SpinnerIcon() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      focusable="false"
      style={{ flexShrink: 0 }}
    >
      <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.5" strokeDasharray="8 20" />
    </svg>
  );
}

/** Pull request icon */
function PRIcon() {
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 10 10"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      focusable="false"
      style={{ flexShrink: 0 }}
    >
      <path
        d="M1 3h5M1 5h8M1 7h5"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** Attempt badge */
function AttemptBadge({ count, max }: { count: number; max: number }) {
  if (!count) return null;
  return (
    <span className="attempt-badge">
      #{count}{max ? `/${max}` : ""}
    </span>
  );
}

/* ── Card Component ──────────────────────────── */

function CardView({ card }: { card: TaskCard }) {
  const isActive = ACTIVE_STATUSES.has(card.status);
  const attempt_count = card.metadata?.attempt_count ?? 0;
  const max_attempts = card.metadata?.max_attempts ?? 0;
  const pr_url = card.metadata?.linked_pr_url;
  const head_branch = card.metadata?.head_branch;
  const borderColor = STATUS_COLORS[card.status] || "#333";

  return (
    <article
      className={`card${isActive ? " card-active" : ""}`}
      style={{ "--card-accent": borderColor } as React.CSSProperties}
    >
      <div className="card-meta">
        <span className={`badge ${statusBadgeClass(card.status)}`}>
          {isActive && <SpinnerIcon />}
          {STATUS_LABELS[card.status] || card.status}
        </span>
        <div className="card-meta-right">
          {pr_url && (
            <a
              href={pr_url}
              target="_blank"
              rel="noopener noreferrer"
              className="pr-link"
              title={`Open PR: ${pr_url}`}
              aria-label={`Open pull request in a new tab: ${pr_url}`}
              onClick={(e) => e.stopPropagation()}
            >
              <PRIcon />
              PR
            </a>
          )}
          <AttemptBadge count={attempt_count} max={max_attempts} />
        </div>
      </div>

      <h3>{card.title}</h3>
      {card.body && (
        <p className="card-body">{card.body.slice(0, 200)}</p>
      )}

      {/* branch + source */}
      {(head_branch || card.source_ref || card.source_kind) && (
        <div className="card-tags">
          {head_branch && <span className="tag tag-branch">{head_branch}</span>}
          {card.source_kind && (
            <span className="tag">{card.source_kind}</span>
          )}
          {card.source_ref && (
            <span className="tag tag-ref">{card.source_ref}</span>
          )}
        </div>
      )}

      <div className="card-footer">
        <div>
          score {card.score} · updated {fmtAgo(card.updated_at)}
        </div>
        {card.metadata?.last_note && (
          <div className="card-note" title={card.metadata.last_note}>
            {card.metadata.last_note.length > 60
              ? card.metadata.last_note.slice(0, 60) + "…"
              : card.metadata.last_note}
          </div>
        )}
        {card.metadata?.last_ci_summary && (
          <div className="card-ci">
            {card.metadata.last_ci_summary}
          </div>
        )}
        {card.metadata?.human_gate_pending && (
          <div className="card-gate">⏳ verification passed; human gate pending</div>
        )}
      </div>
    </article>
  );
}

/* ── Grouped Column Component ────────────────── */

function GroupColumnView({
  label,
  color,
  cards,
  showCount = true,
  emptyAction,
  emptyText,
}: {
  label: string;
  color: string;
  cards: TaskCard[];
  showCount?: boolean;
  emptyAction?: { label: string; onClick: () => void };
  emptyText?: string;
}) {
  return (
    <section className="column" aria-label={`${label} column`}>
      <div className="column-header">
        <div className="column-title-row">
          <span className="column-dot" style={{ background: color }} aria-hidden="true" />
          <h2>{label}</h2>
        </div>
        {showCount && (
          <span aria-label={`${cards.length} items`} className="column-count">
            {cards.length}
          </span>
        )}
      </div>
      <div className="cards">
        {cards.length > 0
          ? cards.map((card) => <CardView key={card.id} card={card} />)
          : emptyAction
            ? (
              <div className="empty-state">
                {emptyText && <span className="empty-text">{emptyText}</span>}
                <button className="btn-empty-action" onClick={emptyAction.onClick}>
                  {emptyAction.label}
                </button>
              </div>
            )
            : <div className="empty" role="status">—</div>
        }
      </div>
    </section>
  );
}

/* ── Journal Component ───────────────────────── */

function JournalView({ entries }: { entries: JournalEntry[] }) {
  return (
    <section className="journal">
      <div className="journal-header">
        <span style={{ color: "var(--accent)", fontSize: 10, letterSpacing: 2, fontWeight: 700 }}>
          //
        </span>
        <h2>RECENT JOURNAL</h2>
      </div>
      <div className="journal-list">
        {entries.length > 0
          ? entries.slice().reverse().slice(0, 20).map((entry, i) => (
              <article key={i} className="journal-item">
                <time>
                  {new Date(entry.timestamp * 1000)
                    .toISOString()
                    .replace("T", " ")
                    .replace(".000Z", " UTC")}
                </time>
                <div>
                  <span className="kind">{entry.kind}</span>
                  {entry.task_id && <span className="task-ref"> [{entry.task_id}]</span>}
                </div>
                <div className="summary">{entry.summary}</div>
              </article>
            ))
          : <div className="empty">Journal is empty.</div>
        }
      </div>
    </section>
  );
}

/* ── Auto-refresh hook ────────────────────────── */

function useAutoRefresh(
  hasActive: boolean,
  onRefresh: () => void,
) {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    const delay = hasActive ? 3_000 : 15_000;
    intervalRef.current = setInterval(onRefresh, delay);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [hasActive, onRefresh]); // eslint-disable-line react-hooks/exhaustive-deps
}

/* ── New Idea Modal ────────────────────────────── */

function NewIdeaModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [labelsRaw, setLabelsRaw] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const titleRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !submitting) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, submitting]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setError(null);
    setSubmitting(true);
    try {
      const labels = labelsRaw
        ? labelsRaw.split(",").map((l) => l.trim()).filter(Boolean)
        : undefined;
      await fetch("/api/pipeline/cards", {
        method: "POST",
        body: JSON.stringify({ title: title.trim(), body: body.trim() || undefined, labels }),
        headers: { "Content-Type": "application/json" },
      });
      onSuccess();
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <div className="modal-overlay" onClick={onClose} aria-hidden="true" />
      <div className="modal-box" role="dialog" aria-modal="true" aria-labelledby="new-idea-title">
        <div className="modal-header">
          <h2 id="new-idea-title">New idea</h2>
          <button onClick={onClose} className="btn-close" aria-label="Close dialog">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="modal-form">
          <div className="form-field">
            <label htmlFor="idea-title">Title <span className="required">*</span></label>
            <input
              id="idea-title"
              ref={titleRef}
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="What needs to be done?"
              required
            />
          </div>
          <div className="form-field">
            <label htmlFor="idea-body">Body</label>
            <textarea
              id="idea-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Optional details…"
              rows={4}
              aria-describedby="idea-body-hint"
            />
            <span id="idea-body-hint" className="label-hint">Markdown supported</span>
          </div>
          <div className="form-field">
            <label htmlFor="idea-labels">Labels <span className="label-hint">(comma-separated)</span></label>
            <input
              id="idea-labels"
              type="text"
              value={labelsRaw}
              onChange={(e) => setLabelsRaw(e.target.value)}
              placeholder="frontend, bug, enhancement"
            />
          </div>
          {error && (
            <div className="error-msg" role="alert" aria-live="assertive">
              {error}
            </div>
          )}
          <div className="modal-actions">
            <button type="button" onClick={onClose} disabled={submitting} className="btn-cancel">Cancel</button>
            <button type="submit" disabled={!title.trim() || submitting} className="btn-submit">
              {submitting ? "Submitting…" : "Submit"}
            </button>
          </div>
        </form>
      </div>
    </>
  );
}

/* ── Main App ────────────────────────────────── */

export function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<number>(Date.now());
  const [showIdeaModal, setShowIdeaModal] = useState(false);
  const [ideaSuccess, setIdeaSuccess] = useState(false);
  const ideaOpenerRef = useRef<HTMLElement | null>(null);

  const loadSnapshot = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch("./snapshot.json", { cache: "no-store" });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const data = await r.json();
      setSnapshot(data);
      setLastRefresh(Date.now());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadSnapshot();
  }, [loadSnapshot]);

  // Compute whether any active card exists
  const hasActive = snapshot
    ? snapshot.cards.some((c) => ACTIVE_STATUSES.has(c.status))
    : false;

  // Auto-refresh: 3 s when active, 15 s when idle
  useAutoRefresh(hasActive, loadSnapshot);

  if (error) {
    return (
      <div className="shell" style={{ paddingTop: 80 }}>
        <div className="empty">Failed to load snapshot.json: {error}</div>
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="shell" style={{ paddingTop: 80, textAlign: "center" }}>
        <div style={{ color: "var(--accent)", fontSize: 12, letterSpacing: 2 }}>
          LOADING SNAPSHOT...
        </div>
      </div>
    );
  }

  const counts = snapshot.counts || {};
  const normalizedFilter = filter.trim().toLowerCase();

  // Group cards into kanban columns
  const groupedColumns = KANBAN_GROUPS.map((group) => {
    const allCards = group.statuses.flatMap((s) => snapshot.columns?.[s] || []);
    const cards = allCards.filter((card) => {
      if (!normalizedFilter) return true;
      const haystack = [
        card.id, card.title, card.body, card.source_kind, card.source_ref,
        ...(card.labels || []), ...(card.score_reasons || []),
        card.metadata?.head_branch,
        card.metadata?.last_note,
      ].join(" ").toLowerCase();
      return haystack.includes(normalizedFilter);
    });
    return { ...group, cards };
  });

  // Column counts for stats bar
  const queue = (counts.queued || 0) + (counts.accepted || 0);
  const running = (counts.preparing || 0) + (counts.running || 0) + (counts.verifying || 0);
  const repairing = counts.repairing || 0;
  const waiting_ci = (counts.waiting_ci || 0) + (counts.pr_open || 0);
  const review = counts.code_review || 0;
  const merged = (counts.merged || 0) + (counts.completed || 0);
  const failed = (counts.failed || 0) + (counts.rejected || 0) + (counts.killed || 0) + (counts.superseded || 0);

  const generated = new Date((snapshot.generated_at || 0) * 1000)
    .toISOString().replace("T", " ").replace(".000Z", " UTC");

  return (
    <>
      {/* ── Hero ─────────────────────────── */}
      <section className="hero">
        <div className="hero-bg">
          <HeroBackground />
        </div>
        <div className="hero-content">
          <div className="hero-main">
            <div className="eyebrow">// AUTOPILOT_KANBAN</div>
            <h1>
              OpenHarness<br />
              <span className="accent">SELF-EVOLUTION</span>
            </h1>
            <p className="hero-sub">
              Lifecycle-aware kanban for OpenHarness autopilot.
            </p>
            <div className="focus-box">
              <div className="focus-label">// CURRENT_FOCUS</div>
              <div className="focus-text">
                {snapshot.focus
                  ? `[${snapshot.focus.status}] ${snapshot.focus.title} · score=${snapshot.focus.score} · ${snapshot.focus.source_kind}`
                  : "No active task focus yet."}
              </div>
            </div>
          </div>
          <div className="hero-side">
            <div className="hero-timestamp">
              Snapshot {generated}
            </div>
            <div className="hero-timestamp" style={{ marginTop: -4, fontSize: 9 }}>
              {loading ? "↻ refreshing…" : `Last refresh ${fmtAgo(Math.floor((Date.now() - lastRefresh) / 1000))}`}
              {hasActive && (
                <span style={{ color: "var(--accent)", marginLeft: 8 }}>
                  ● active tasks running
                </span>
              )}
            </div>
            <div className="pipeline-viz" aria-hidden="true">
              <PipelineAnimation />
            </div>
          </div>
        </div>
      </section>

      <div className="shell">
        {/* ── Stats Bar ──────────────────── */}
        <section className="stats-bar">
          <div className="stat">
            <div className="stat-label" style={{ color: "#64748b" }}>QUEUE</div>
            <div className="stat-value">{queue}</div>
            <div className="stat-sub">queued + accepted</div>
          </div>
          <div className="stat">
            <div className="stat-label teal">RUNNING</div>
            <div className="stat-value">{running}</div>
            <div className="stat-sub">prep + run + verify</div>
          </div>
          <div className="stat">
            <div className="stat-label orange">REPAIRING</div>
            <div className="stat-value">{repairing}</div>
            <div className="stat-sub">active repair</div>
          </div>
          <div className="stat">
            <div className="stat-label" style={{ color: "#3b82f6" }}>WAITING CI</div>
            <div className="stat-value">{waiting_ci}</div>
            <div className="stat-sub">ci polling</div>
          </div>
          <div className="stat">
            <div className="stat-label" style={{ color: "#a855f7" }}>REVIEW</div>
            <div className="stat-value">{review}</div>
            <div className="stat-sub">code review</div>
          </div>
          <div className="stat">
            <div className="stat-label teal">MERGED</div>
            <div className="stat-value">{merged}</div>
            <div className="stat-sub">merged + completed</div>
          </div>
          <div className="stat">
            <div className="stat-label" style={{ color: "#ff4444" }}>FAILED</div>
            <div className="stat-value">{failed}</div>
            <div className="stat-sub">failed + rejected + killed</div>
          </div>
        </section>

        {/* ── Toolbar ────────────────────── */}
        <section className="toolbar">
          <label htmlFor="dashboard-filter" className="sr-only">
            Filter tasks
          </label>
          <input
            id="dashboard-filter"
            type="search"
            aria-describedby="dashboard-filter-hint"
            placeholder="Filter by title, body, source, label, branch, or note…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <div id="dashboard-filter-hint" className="hint">
            Reads <code>snapshot.json</code> — auto-refresh{" "}
            <strong>{hasActive ? "3 s (active)" : "15 s (idle)"}</strong>
          </div>
        </section>

        {/* ── Kanban Board (7 columns) ────── */}
        <section className="board board-7col" aria-label="Task board">
          {groupedColumns.map((group) => {
            // Empty state action per column
            const emptyAction = group.key === "queue"
              ? { label: "+ Add idea", onClick: () => setShowIdeaModal(true) }
              : undefined;
            const emptyText = group.key === "queue"
              ? "No tasks queued"
              : group.key === "running"
                ? "No active tasks"
                : undefined;
            return (
              <GroupColumnView
                key={group.key}
                label={group.label}
                color={group.color}
                cards={group.cards}
                emptyAction={emptyAction}
                emptyText={emptyText}
              />
            );
          })}
        </section>

        {/* ── Journal ────────────────────── */}
        <JournalView entries={snapshot.journal || []} />

        {/* ── Modals ─────────────────────── */}
        {showIdeaModal && (
          <NewIdeaModal
            onClose={() => setShowIdeaModal(false)}
            onSuccess={() => {
              setShowIdeaModal(false);
              setIdeaSuccess(true);
              setTimeout(() => setIdeaSuccess(false), 3000);
              loadSnapshot();
            }}
          />
        )}
        {ideaSuccess && (
          <div className="toast" role="status" aria-live="polite">✓ Idea queued successfully</div>
        )}
      </div>
    </>
  );
}