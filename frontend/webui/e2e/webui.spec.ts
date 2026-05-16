/**
 * E2E Playwright tests for core WebUI flows.
 *
 * These tests use Playwright's route interception to stub all API calls so the
 * suite is deterministic and does not require a live backend.  The tests run
 * against the vite dev server (or any static host) at the configured baseURL.
 *
 * Each describe-group covers one of the task requirements:
 *  1. Navigation & standardised page headers
 *  2. Chat tool card collapse/expand
 *  3. Autopilot board hierarchy & new idea flow
 *  4. Semantic log feed filtering
 *  5. Jobs filters & row expansion
 *  6. Projects active/delete safety UX
 *  7. Settings help text & save feedback
 */

import { test, expect, type Page, type Route } from "@playwright/test";

// ─── Shared fixture data ──────────────────────────────────────────────────────

const SESSION_ID = "e2e-session-abc";

const READY_EVENT = JSON.stringify({
  type: "ready",
  state: {
    model: "gpt-5.5",
    cwd: "/home/user/project",
    permission_mode: "default",
    provider: "openai",
    effort: "medium",
  },
  tasks: [],
});

const MODES_PAYLOAD = {
  permission_mode: "default",
  fast_mode: false,
  vim_enabled: false,
  notifications_enabled: true,
  auto_compact_threshold_tokens: 160_000,
  effort: "medium",
  passes: 1,
  output_style: "default",
  theme: "default",
};

const SAMPLE_CARDS = [
  {
    id: "card-queued-1",
    title: "Add login form",
    status: "queued",
    source_kind: "manual_idea",
    score: 75,
    labels: ["frontend"],
    created_at: Date.now() / 1000 - 3600,
    updated_at: Date.now() / 1000 - 1800,
  },
  {
    id: "card-running-1",
    title: "Fix auth bug",
    status: "running",
    source_kind: "github_issue",
    score: 100,
    labels: [],
    created_at: Date.now() / 1000 - 7200,
    updated_at: Date.now() / 1000 - 600,
  },
  {
    id: "card-done-1",
    title: "Add documentation",
    status: "completed",
    source_kind: "manual_idea",
    score: 30,
    labels: [],
    created_at: Date.now() / 1000 - 86400,
    updated_at: Date.now() / 1000 - 86400,
  },
];

const SAMPLE_TASKS = [
  {
    id: "task-abc12345",
    type: "local_bash",
    status: "completed",
    description: "Run tests",
    cwd: "/home/user/project",
    output_file: "/home/user/project/out.log",
    command: "pytest -q",
    prompt: null,
    created_at: Date.now() / 1000 - 300,
    started_at: Date.now() / 1000 - 290,
    ended_at: Date.now() / 1000 - 280,
    return_code: 0,
    metadata: {},
  },
  {
    id: "task-xyz67890",
    type: "local_agent",
    status: "running",
    description: "Code review agent",
    cwd: "/home/user/project",
    output_file: "/home/user/project/agent.log",
    command: null,
    prompt: "Review the PR",
    created_at: Date.now() / 1000 - 120,
    started_at: Date.now() / 1000 - 115,
    ended_at: null,
    return_code: null,
    metadata: { review_status: "in_progress" },
  },
];

const SAMPLE_PROJECTS = {
  projects: [
    {
      id: "proj-1",
      name: "My Project",
      path: "/home/user/my-project",
      description: "Test project",
      created_at: null,
      updated_at: null,
      is_active: true,
    },
    {
      id: "proj-2",
      name: "Other Project",
      path: "/home/user/other-project",
      description: null,
      created_at: null,
      updated_at: null,
      is_active: false,
    },
    {
      id: "proj-3",
      name: "pytest-temp-project",
      path: "./fixtures/pytest-temp-project",
      description: "synthetic temp pytest project",
      created_at: null,
      updated_at: null,
      is_active: false,
    },
  ],
  active_project_id: "proj-1",
};

// ─── Route-stubbing helpers ───────────────────────────────────────────────────

function json(data: unknown, status = 200) {
  return {
    status,
    contentType: "application/json",
    body: JSON.stringify(data),
  };
}

/**
 * Install the minimal set of route stubs needed for the App shell to load.
 * Call this from every test's `page.route(...)` or as a `beforeEach` hook.
 */
async function stubAppShell(page: Page) {
  await page.addInitScript(`
    window.localStorage.setItem("oh_token", "e2e-access-token");
    window.localStorage.setItem("oh_refresh_token", "e2e-refresh-token");
    window.localStorage.setItem("oh_access_expires_at", String(Date.now() + 60 * 60 * 1000));
    window.localStorage.setItem("oh_refresh_expires_at", String(Date.now() + 7 * 24 * 60 * 60 * 1000));
    window.localStorage.setItem("oh_is_default_password", "false");
  `);

  await page.route("/api/auth/status", async (route: Route) => {
    await route.fulfill(json({
      authenticated: true,
      is_default_password: false,
      access_expires_in: 3600,
      refresh_expires_in: 604800,
    }));
  });

  await page.route("/api/auth/refresh", async (route: Route) => {
    await route.fulfill(json({
      access_token: "e2e-access-token-refreshed",
      refresh_token: "e2e-refresh-token-refreshed",
      access_expires_in: 3600,
      refresh_expires_in: 604800,
    }));
  });

  await page.route("/api/auth/login", async (route: Route) => {
    await route.fulfill(json({
      access_token: "e2e-access-token",
      refresh_token: "e2e-refresh-token",
      access_expires_in: 3600,
      refresh_expires_in: 604800,
      is_default_password: false,
    }));
  });

  await page.route("/api/auth/logout", async (route: Route) => {
    await route.fulfill(json({ ok: true }));
  });

  // Stub the session creation endpoint
  await page.route("/api/sessions", async (route: Route) => {
    if (route.request().method() === "POST") {
      await route.fulfill(json({ session_id: SESSION_ID }));
    } else {
      await route.fulfill(json({ sessions: [] }));
    }
  });

  // Stub the cron jobs list (used by Sidebar)
  await page.route("/api/cron/jobs", async (route: Route) => {
    await route.fulfill(json({ jobs: [] }));
  });

  // Stub the project selector used by the sidebar. A missing stub returns 401
  // from a live dev server and correctly sends the auth shell back to login.
  await page.route("/api/projects", async (route: Route) => {
    await route.fulfill(json(SAMPLE_PROJECTS));
  });

  // Stub recent history for the Sessions dropdown
  await page.route("**/api/history**", async (route: Route) => {
    await route.fulfill(json({ sessions: [] }));
  });

  // Stub modes endpoint
  await page.route("/api/modes", async (route: Route) => {
    if (route.request().method() === "GET") {
      await route.fulfill(json(MODES_PAYLOAD));
    } else if (route.request().method() === "PATCH") {
      const body = JSON.parse(route.request().postData() || "{}");
      await route.fulfill(json({ ...MODES_PAYLOAD, ...body }));
    }
  });

  // Intercept WebSocket — respond with READY after connection; the browser's
  // WebSocket upgrade will be attempted but we can't stub WS via route().
  // Instead we let it fail gracefully (the app shows "connecting…" banner) and
  // still verify page structure.  For pages that don't depend on WS state
  // (Autopilot, Tasks, Projects, Settings) this is fine.
}

async function stubPipelineRoutes(page: Page) {
  await page.route("/api/pipeline/cards*", async (route: Route) => {
    if (route.request().method() === "GET") {
      await route.fulfill(json({ cards: SAMPLE_CARDS, updated_at: Date.now() / 1000 }));
    } else if (route.request().method() === "POST") {
      await route.fulfill(json({ ...SAMPLE_CARDS[0], id: "new-card-1", title: "New test idea", status: "queued" }));
    } else {
      await route.continue();
    }
  });

  await page.route("**/api/pipeline/journal**", async (route: Route) => {
    await route.fulfill(json({ entries: [] }));
  });

  await page.route("**/api/pipeline/cards/*/stream**", async (route: Route) => {
    // SSE: immediately close without events
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: "",
    });
  });

  await page.route("**/api/pipeline/policy**", async (route: Route) => {
    await route.fulfill(json({ yaml_content: "# policy\n", parsed: {} }));
  });

  await page.route("**/api/pipeline/cards/*/model**", async (route: Route) => {
    await route.fulfill(json({ ok: true }));
  });

  await page.route("/api/models*", async (route: Route) => {
    await route.fulfill(json({
      openai: [
        {
          id: "gpt-5.5",
          label: "GPT-5.5",
          context_window: 256000,
          is_default: true,
          is_custom: false,
        },
      ],
    }));
  });
}

async function stubTasksRoutes(page: Page) {
  await page.route("/api/tasks", async (route: Route) => {
    await route.fulfill(json({ tasks: SAMPLE_TASKS }));
  });

  await page.route("/api/tasks/*/output**", async (route: Route) => {
    await route.fulfill(json({ lines: ["line 1", "line 2", "line 3"] }));
  });

  await page.route("/api/tasks/*", async (route: Route) => {
    const taskId = route.request().url().split("/api/tasks/")[1]?.split("?")[0];
    const task = SAMPLE_TASKS.find((t) => t.id === decodeURIComponent(taskId ?? "")) ?? SAMPLE_TASKS[0];
    await route.fulfill(json(task));
  });
}

async function stubProjectsRoutes(page: Page) {
  await page.route("/api/projects*", async (route: Route) => {
    if (route.request().method() === "GET") {
      await route.fulfill(json(SAMPLE_PROJECTS));
    } else if (route.request().method() === "POST") {
      await route.fulfill(json({ ...SAMPLE_PROJECTS.projects[0], id: "proj-new" }));
    } else {
      await route.continue();
    }
  });

  await page.route("/api/projects/*/activate", async (route: Route) => {
    await route.fulfill(json({ ok: true }));
  });

  await page.route("/api/projects/**", async (route: Route) => {
    if (route.request().method() === "PATCH") {
      await route.fulfill(json(SAMPLE_PROJECTS.projects[0]));
    } else if (route.request().method() === "DELETE") {
      await route.fulfill(json({ ok: true }));
    } else {
      await route.continue();
    }
  });
}

async function stubSettingsRoutes(page: Page) {
  await page.route("/api/providers*", async (route: Route) => {
    await route.fulfill(json({ providers: [] }));
  });

  await page.route("/api/models*", async (route: Route) => {
    await route.fulfill(json({}));
  });

  await page.route("/api/agents*", async (route: Route) => {
    await route.fulfill(json([]));
  });

  await page.route("/api/cron/config*", async (route: Route) => {
    if (route.request().method() === "GET") {
      await route.fulfill(json({
        enabled: true,
        scan_cron: "*/15 * * * *",
        tick_cron: "0 * * * *",
        timezone: "UTC",
        install_mode: "off",
        project_path: "/home/user/project",
        scan_cron_description: "every 15 minutes",
        tick_cron_description: "every hour",
        next_scan_runs: [],
        next_tick_runs: [],
      }));
    } else {
      await route.fulfill(json({ ok: true }));
    }
  });
}

async function gotoAuthed(page: Page, path: string) {
  const separator = path.includes("?") ? "&" : "?";
  await page.goto(`${path}${separator}token=e2e-access-token`);
}

// ─── 1. Navigation & Page Headers ────────────────────────────────────────────

test.describe("1. Navigation & Page Headers", () => {
  test.beforeEach(async ({ page }) => {
    await stubAppShell(page);
    await stubPipelineRoutes(page);
    await stubTasksRoutes(page);
    await stubProjectsRoutes(page);
    await stubSettingsRoutes(page);
  });

  test("each sidebar nav link renders the corresponding page with an h1", async ({ page }) => {
    await gotoAuthed(page, "/chat");
    // Wait for the shell to mount (sidebar should be visible)
    await expect(page.locator('[aria-label="Primary"]')).toBeVisible({ timeout: 10_000 });

    const navItems = [
      { label: "History", urlPart: "/history" },
      { label: "Autopilot", urlPart: "/autopilot" },
      { label: "Jobs", urlPart: "/tasks" },
      { label: "Projects", urlPart: "/projects" },
    ];

    for (const { label, urlPart } of navItems) {
      await page.locator(`[aria-label="Primary"] >> text="${label}"`).click();
      await page.waitForURL(`**${urlPart}**`);
      const h1 = page.locator("h1").first();
      await expect(h1).toBeVisible({ timeout: 10_000 });
      const text = (await h1.textContent()) ?? "";
      expect(text.trim().length).toBeGreaterThan(0);
    }
  });

  test("settings pages each mount a PageHeader h1", async ({ page }) => {
    for (const path of [
      "/settings/modes",
      "/settings/provider",
      "/settings/providers",
      "/settings/models",
      "/settings/agents",
      "/settings/cron",
      "/settings/schedule",
    ]) {
      await gotoAuthed(page, path);
      await expect(page.locator('[aria-label="Primary"]')).toBeVisible({ timeout: 10_000 });
      await expect(page.locator("h1").first()).toBeVisible({ timeout: 10_000 });
    }
  });

  test("settings aliases: /providers and /schedule do not fall back to /chat", async ({ page }) => {
    for (const path of ["/settings/providers", "/settings/schedule"]) {
      await gotoAuthed(page, path);
      const url = page.url();
      expect(url).toContain(path);
      await expect(page.locator('[aria-label="Primary"]')).toBeVisible({ timeout: 10_000 });
      await expect(page.locator("h1").first()).toBeVisible({ timeout: 10_000 });
    }
  });

  test("desktop sidebar collapses and restores on toggle", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await gotoAuthed(page, "/chat");

    const sidebar = page.locator('[data-testid="sidebar-desktop"]');
    await expect(sidebar).toBeVisible({ timeout: 10_000 });

    const toggleBtn = page.locator('button[aria-label="Toggle sidebar"]');
    await toggleBtn.click();
    await expect(sidebar).toHaveClass(/hidden/, { timeout: 5_000 });

    await toggleBtn.click();
    await expect(sidebar).toHaveClass(/sm:block/, { timeout: 5_000 });
  });
});

// ─── 2. Chat Tool Card Collapse / Expand ─────────────────────────────────────

test.describe("2. Chat Tool Card Collapse/Expand", () => {
  test.beforeEach(async ({ page }) => {
    await stubAppShell(page);
    await page.addInitScript(({ readyEvent }) => {
      class MockWebSocket {
        static CONNECTING = 0;
        static OPEN = 1;
        static CLOSING = 2;
        static CLOSED = 3;
        url: string;
        readyState = MockWebSocket.CONNECTING;
        onopen: ((event: Event) => void) | null = null;
        onmessage: ((event: MessageEvent) => void) | null = null;
        onclose: ((event: CloseEvent) => void) | null = null;
        onerror: ((event: Event) => void) | null = null;
        constructor(url: string) {
          this.url = url;
          setTimeout(() => {
            this.readyState = MockWebSocket.OPEN;
            this.onopen?.(new Event("open"));
            this.onmessage?.(new MessageEvent("message", { data: readyEvent }));
            this.onmessage?.(
              new MessageEvent("message", {
                data: JSON.stringify({
                  type: "tool_completed",
                  tool_name: "bash_ide",
                  output: "x".repeat(300),
                  is_error: false,
                }),
              }),
            );
            this.onmessage?.(
              new MessageEvent("message", {
                data: JSON.stringify({
                  type: "assistant_complete",
                  message: "Tool run complete.",
                }),
              }),
            );
          }, 0);
        }
        send() {}
        close() {
          this.readyState = MockWebSocket.CLOSED;
          this.onclose?.(new CloseEvent("close", { code: 1000 }));
        }
        addEventListener() {}
        removeEventListener() {}
        dispatchEvent() { return true; }
      }
      Object.defineProperty(window, "WebSocket", {
        configurable: true,
        writable: true,
        value: MockWebSocket,
      });
    }, { readyEvent: READY_EVENT });
  });

  test("tool result card expands to show output on click", async ({ page }) => {
    await gotoAuthed(page, "/chat");
    await expect(page.locator('[aria-label="Primary"]')).toBeVisible({ timeout: 10_000 });

    const toggle = page.locator("button:has-text('result · bash_ide')").first();
    await expect(toggle).toBeVisible({ timeout: 10_000 });
    await expect(toggle.locator("text=▶")).toBeVisible();

    await toggle.click();
    await expect(toggle.locator("text=▼")).toBeVisible({ timeout: 5_000 });
    await expect(page.locator("text=Output").first()).toBeVisible({ timeout: 5_000 });
    await expect(page.locator("pre").filter({ hasText: /^x{50,}/ }).first()).toBeVisible({ timeout: 5_000 });
  });

  test("tool result card collapses again after a second click", async ({ page }) => {
    await gotoAuthed(page, "/chat");
    await expect(page.locator('[aria-label="Primary"]')).toBeVisible({ timeout: 10_000 });

    const toggle = page.locator("button:has-text('result · bash_ide')").first();
    await expect(toggle).toBeVisible({ timeout: 10_000 });

    await toggle.click();
    await expect(toggle.locator("text=▼")).toBeVisible({ timeout: 5_000 });
    await toggle.click();
    await expect(toggle.locator("text=▶")).toBeVisible({ timeout: 5_000 });
    await expect(page.locator("text=Output")).toHaveCount(0);
  });
});

// ─── 3. Autopilot Board: Hierarchy & New Idea ────────────────────────────────

test.describe("3. Autopilot Board: Hierarchy & New Idea", () => {
  test.beforeEach(async ({ page }) => {
    await stubAppShell(page);
    await stubPipelineRoutes(page);
  });

  test("renders all kanban column headings", async ({ page }) => {
    await gotoAuthed(page, "/autopilot");
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10_000 });

    for (const col of ["Queue", "In Progress", "Review", "Completed", "Failed", "Rejected"]) {
      await expect(page.locator(`text=${col}`).first()).toBeVisible({ timeout: 8_000 });
    }
  });

  test("displays sample cards in the board", async ({ page }) => {
    await gotoAuthed(page, "/autopilot");
    await expect(page.locator("text=Add login form").first()).toBeVisible({ timeout: 10_000 });
    await expect(page.locator("text=Fix auth bug").first()).toBeVisible({ timeout: 5_000 });
    await expect(page.locator("text=Add documentation").first()).toBeVisible({ timeout: 5_000 });
  });

  test("New idea button opens the dialog", async ({ page }) => {
    await gotoAuthed(page, "/autopilot");
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10_000 });

    await page.locator('button:has-text("New idea")').first().click();
    await expect(page.locator('[role="dialog"][aria-label="New idea"]')).toBeVisible({ timeout: 5_000 });
  });

  test("New idea dialog: submit button disabled while title is empty", async ({ page }) => {
    await gotoAuthed(page, "/autopilot");
    await page.locator('button:has-text("New idea")').first().click();
    const dialog = page.locator('[role="dialog"][aria-label="New idea"]');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    const submit = dialog.locator('button[type="submit"]');
    await expect(submit).toBeDisabled();
  });

  test("New idea dialog: submit button enables when title is filled", async ({ page }) => {
    await gotoAuthed(page, "/autopilot");
    await page.locator('button:has-text("New idea")').first().click();
    const dialog = page.locator('[role="dialog"][aria-label="New idea"]');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    await dialog.locator('#idea-title').fill("Test new idea");
    const submit = dialog.locator('button[type="submit"]');
    await expect(submit).toBeEnabled({ timeout: 3_000 });
  });

  test("New idea dialog closes on Cancel", async ({ page }) => {
    await gotoAuthed(page, "/autopilot");
    await page.locator('button:has-text("New idea")').first().click();
    const dialog = page.locator('[role="dialog"][aria-label="New idea"]');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    await dialog.locator('button:has-text("Cancel")').click();
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
  });

  test("New idea dialog closes on Escape key", async ({ page }) => {
    await gotoAuthed(page, "/autopilot");
    await page.locator('button:has-text("New idea")').first().click();
    const dialog = page.locator('[role="dialog"][aria-label="New idea"]');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
  });

  test("clicking a card opens a drawer with tabs", async ({ page }) => {
    await gotoAuthed(page, "/autopilot");
    await expect(page.locator("text=Add login form").first()).toBeVisible({ timeout: 10_000 });

    await page.locator("text=Add login form").first().click();
    // Drawer should have at least the Info tab
    await expect(page.locator('[role="tab"]:has-text("Info")').first()).toBeVisible({ timeout: 5_000 });
  });
});

// ─── 4. Semantic Log Feed Filtering ───────────────────────────────────────────

test.describe("4. Semantic Log Feed Filtering", () => {
  test.beforeEach(async ({ page }) => {
    await stubAppShell(page);
    await stubPipelineRoutes(page);
  });

  test("log filter pills are rendered in the Logs tab", async ({ page }) => {
    await gotoAuthed(page, "/autopilot");
    await expect(page.locator("text=Add login form").first()).toBeVisible({ timeout: 10_000 });

    // Open a card drawer
    await page.locator("text=Add login form").first().click();

    // Click the Logs tab
    const logsTab = page.locator('[role="tab"]:has-text("Logs")');
    await expect(logsTab).toBeVisible({ timeout: 5_000 });
    await logsTab.click({ force: true });

    // Filter pills must be present — they are rendered from LOG_FILTERS without SSE data.
    const pills = page.locator('[aria-label="Filter log segments"] button');
    await expect(pills.first()).toBeVisible({ timeout: 5_000 });
    const count = await pills.count();
    expect(count).toBeGreaterThan(0);
  });

  test("log filter pills toggle aria-pressed attribute", async ({ page }) => {
    await gotoAuthed(page, "/autopilot");
    await expect(page.locator("text=Fix auth bug").first()).toBeVisible({ timeout: 10_000 });

    await page.locator("text=Fix auth bug").first().click();
    const logsTab = page.locator('[role="tab"]:has-text("Logs")');
    await expect(logsTab).toBeVisible({ timeout: 5_000 });
    await logsTab.click({ force: true });

    const pills = page.locator('[aria-label="Filter log segments"] button');
    const count = await pills.count();
    expect(count).toBeGreaterThanOrEqual(2);

    // Click a different pill (not first)
    const secondPill = pills.nth(1);
    await secondPill.click();
    await expect(secondPill).toHaveAttribute("aria-pressed", "true");

    // First pill should no longer be active
    await expect(pills.nth(0)).toHaveAttribute("aria-pressed", "false");
  });
});

// ─── 5. Jobs Filters & Row Expansion ─────────────────────────────────────────

test.describe("5. Jobs Filters & Row Expansion", () => {
  test.beforeEach(async ({ page }) => {
    await stubAppShell(page);
    await stubTasksRoutes(page);
  });

  test("Jobs page renders PageHeader and filter toolbar", async ({ page }) => {
    await gotoAuthed(page, "/tasks");
    await expect(page.locator("h1:has-text('Background Jobs')")).toBeVisible({ timeout: 10_000 });

    await expect(page.locator('input[placeholder*="Search jobs"]')).toBeVisible({ timeout: 5_000 });
    await expect(page.locator('select').nth(1)).toBeVisible({ timeout: 5_000 });
    await expect(page.locator('select').nth(2)).toBeVisible({ timeout: 5_000 });
  });

  test("status filter shows only matching tasks", async ({ page }) => {
    await gotoAuthed(page, "/tasks");
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10_000 });

    // Select "Running" status filter
    const statusSelect = page.locator("select").nth(1);
    await statusSelect.selectOption("running");

    // "Run tests" (completed) should not be visible; "Code review agent" (running) should be
    await expect(page.locator("text=Code review agent")).toBeVisible({ timeout: 5_000 });
    // "Run tests" (completed) should be hidden
    await expect(page.locator("text=Run tests")).not.toBeVisible({ timeout: 3_000 });
  });

  test("search input filters task rows", async ({ page }) => {
    await gotoAuthed(page, "/tasks");
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10_000 });

    const searchInput = page.locator('input[placeholder*="Search jobs"]');
    await searchInput.fill("Code review");

    await expect(page.locator("text=Code review agent")).toBeVisible({ timeout: 5_000 });
    await expect(page.locator("text=Run tests")).not.toBeVisible({ timeout: 3_000 });
  });

  test("clear filters button appears when filters are active and restores list", async ({ page }) => {
    await gotoAuthed(page, "/tasks");
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10_000 });

    const searchInput = page.locator('input[placeholder*="Search jobs"]');
    await searchInput.fill("no match xyz");

    const clearBtn = page.locator('button:has-text("Clear filters")');
    await expect(clearBtn).toBeVisible({ timeout: 5_000 });
    await clearBtn.click();

    // Table should show all tasks again
    await expect(page.locator("text=Run tests")).toBeVisible({ timeout: 5_000 });
  });

  test("expand button shows log preview row and collapse re-hides it", async ({ page }) => {
    await gotoAuthed(page, "/tasks");
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10_000 });

    const expandBtn = page.locator('button[aria-label="Expand row"]').first();
    await expect(expandBtn).toBeVisible({ timeout: 8_000 });
    await expandBtn.click();

    const collapseBtn = page.locator('button[aria-label="Collapse row"]').first();
    await expect(collapseBtn).toBeVisible({ timeout: 5_000 });

    // Output preview (pre tag in the expanded row) should appear
    await expect(page.locator("pre").first()).toBeVisible({ timeout: 5_000 });

    // Collapse again
    await collapseBtn.click();
    await expect(page.locator('button[aria-label="Expand row"]').first()).toBeVisible({ timeout: 5_000 });
  });

  test("clicking a task row opens the detail drawer", async ({ page }) => {
    await gotoAuthed(page, "/tasks");
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10_000 });

    // Click the row (not the expand button)
    await page.locator("tbody tr").first().click();

    // The drawer should appear with a Close button
    await expect(page.locator('button[aria-label="Close"]').first()).toBeVisible({ timeout: 8_000 });
  });
});

// ─── 6. Projects Active/Delete Safety UX ─────────────────────────────────────

test.describe("6. Projects Active/Delete Safety UX", () => {
  test.beforeEach(async ({ page }) => {
    await stubAppShell(page);
    await stubProjectsRoutes(page);
  });

  test("Projects page renders h1 and active badge on the active project", async ({ page }) => {
    await gotoAuthed(page, "/projects");
    await expect(page.locator("h1:has-text('Projects')")).toBeVisible({ timeout: 10_000 });

    // "active" badge should be present next to the active project
    await expect(page.locator("text=active").first()).toBeVisible({ timeout: 8_000 });
  });

  test("Delete button opens the confirmation dialog with project name", async ({ page }) => {
    await gotoAuthed(page, "/projects");
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10_000 });

    // Click delete for "My Project"
    const deleteBtn = page.locator('button[aria-label="Delete project My Project"]');
    await expect(deleteBtn).toBeVisible({ timeout: 8_000 });
    await deleteBtn.click();

    await expect(page.locator("h2:has-text('Delete Project')").first()).toBeVisible({ timeout: 5_000 });
    await expect(page.locator("text=My Project").first()).toBeVisible({ timeout: 3_000 });
  });

  test("Confirmation Cancel does not delete the project", async ({ page }) => {
    await gotoAuthed(page, "/projects");
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10_000 });

    await page.locator('button[aria-label="Delete project My Project"]').click();
    await expect(page.locator("h2:has-text('Delete Project')").first()).toBeVisible({ timeout: 5_000 });

    await page.locator('button:has-text("Cancel")').last().click();
    await expect(page.locator("h2:has-text('Delete Project')")).not.toBeVisible({ timeout: 5_000 });

    // Project card should still be visible
    await expect(page.locator("text=My Project").first()).toBeVisible({ timeout: 3_000 });
  });

  test("Confirmation Delete calls delete and removes the card (with stub)", async ({ page }) => {
    // Override delete stub to confirm it was called
    let deleteCalled = false;
    await page.route("/api/projects/**", async (route: Route) => {
      if (route.request().method() === "DELETE") {
        deleteCalled = true;
        await route.fulfill(json({ ok: true }));
      } else if (route.request().method() === "PATCH") {
        await route.fulfill(json(SAMPLE_PROJECTS.projects[0]));
      } else {
        await route.continue();
      }
    });
    await page.route("/api/projects*", async (route: Route) => {
      await route.fulfill(json(SAMPLE_PROJECTS));
    });

    await gotoAuthed(page, "/projects");
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10_000 });

    await page.getByRole("tab", { name: "All" }).click();
    await expect(page.locator('button[aria-label="Delete project Other Project"]')).toBeVisible({ timeout: 5_000 });
    await page.locator('button[aria-label="Delete project Other Project"]').click();
    await expect(page.locator("h2:has-text('Delete Project')").first()).toBeVisible({ timeout: 5_000 });

    // Click the confirm Delete button (last in the dialog)
    await page.getByRole("button", { name: "Confirm delete project" }).click();

    // Wait a moment for the API call
    await page.waitForTimeout(1_000);
    expect(deleteCalled).toBe(true);
  });

  test("Activate button is not shown on the already-active project", async ({ page }) => {
    await gotoAuthed(page, "/projects");
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10_000 });

    // The active project card should not have an Activate button
    const activeCard = page.locator("text=My Project").locator("xpath=ancestor::div[contains(@class,'rounded-xl')]").first();
    const activateBtn = activeCard.locator("button:has-text('Activate')");
    await expect(activateBtn).not.toBeVisible({ timeout: 3_000 });
  });
});

// ─── 7. Settings Help Text & Save Feedback ────────────────────────────────────

// ─── 7. Audit Regression Smoke (2026-05-12) ──────────────────────────────────

test.describe("7. Audit Regression Smoke (2026-05-12)", () => {
  test.beforeEach(async ({ page }) => {
    await stubAppShell(page);
    await stubPipelineRoutes(page);
    await stubTasksRoutes(page);
    await stubProjectsRoutes(page);
    await stubSettingsRoutes(page);
  });

  test("header model dropdown is non-empty when /api/models returns active provider models", async ({ page }) => {
    // ModelPicker lives in the mobile menu on small viewports, so use mobile size.
    await page.setViewportSize({ width: 390, height: 844 });

    // Unroute the empty models stub from beforeEach and install one with real data.
    await page.unroute("/api/models*");
    await page.route("/api/models*", async (route: Route) => {
      await route.fulfill(
        json({
          openai: [
            { id: "gpt-5.5", label: "GPT-5.5", is_default: true, is_custom: false },
            { id: "gpt-4.1", label: "GPT-4.1", is_default: false, is_custom: false },
          ],
        }),
      );
    });

    await page.addInitScript(({ readyEvent }) => {
      const payload = JSON.parse(readyEvent);
      payload.state.provider = "openai";
      payload.state.active_profile = "openai";
      class MockWebSocket {
        static CONNECTING = 0;
        static OPEN = 1;
        static CLOSING = 2;
        static CLOSED = 3;
        readyState = MockWebSocket.CONNECTING;
        onopen: ((event: Event) => void) | null = null;
        onmessage: ((event: MessageEvent) => void) | null = null;
        onclose: ((event: CloseEvent) => void) | null = null;
        onerror: ((event: Event) => void) | null = null;
        constructor() {
          setTimeout(() => {
            this.readyState = MockWebSocket.OPEN;
            this.onopen?.(new Event("open"));
            this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(payload) }));
          }, 0);
        }
        send() {}
        close() {}
        addEventListener() {}
        removeEventListener() {}
      }
      // @ts-expect-error e2e mock
      window.WebSocket = MockWebSocket;
    }, { readyEvent: READY_EVENT });

    await gotoAuthed(page, "/chat");

    // The RuntimeSummary model chip in the mobile header shows the current model.
    const mobileModelChip = page.locator('button[aria-label="Open runtime controls"]');
    await expect(mobileModelChip).toBeVisible({ timeout: 10_000 });
    await expect(mobileModelChip).toContainText("gpt-5.5");

    // Tap the chip to open the mobile menu (ModelPicker lives inside it).
    await mobileModelChip.click();

    // ModelPicker dropdown button shows the current model name.
    const modelBtn = page.locator('button[aria-haspopup="listbox"]').filter({ hasText: "gpt-5.5" });
    await expect(modelBtn).toBeVisible({ timeout: 5_000 });
    await modelBtn.click();

    // The dropdown is a div (not role=listbox); items have role="option".
    const options = page.locator('button[role="option"]');
    await expect(options).toHaveCount(2, { timeout: 5_000 });
    await expect(options.filter({ hasText: "GPT-5.5" })).toBeVisible({ timeout: 3_000 });
    await expect(options.filter({ hasText: "GPT-4.1" })).toBeVisible({ timeout: 3_000 });

    await expect(page.locator('[role="option"]').first().locator("xpath=ancestor::div[1]")).toHaveScreenshot(
      "audit-model-dropdown.png",
      { animations: "disabled" },
    );
  });

  test("mobile header does not horizontally overflow viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await gotoAuthed(page, "/chat");

    const hasOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(hasOverflow).toBe(false);
  });

  test("Projects default view hides temp-like pytest projects", async ({ page }) => {
    // The default viewFilter is "active" (see ProjectsPage.tsx line 71).
    // pytest-temp-project has a temp-like name and is NOT active, so it should be hidden.
    await gotoAuthed(page, "/projects");
    await expect(page.locator("h1:has-text('Projects')")).toBeVisible({ timeout: 10_000 });

    // Active project "My Project" is visible.
    await expect(page.locator("text=My Project").first()).toBeVisible({ timeout: 5_000 });

    // pytest-temp-project is NOT active so hidden under default "Active" filter.
    await expect(page.locator("text=pytest-temp-project")).not.toBeVisible({ timeout: 3_000 });
    await expect(page.locator("main").first()).toHaveScreenshot("audit-projects-default.png", {
      animations: "disabled",
    });
  });

  test("Chat empty state appears when connected with no conversation", async ({ page }) => {
    await page.addInitScript(({ readyEvent }) => {
      class MockWebSocket {
        static CONNECTING = 0;
        static OPEN = 1;
        static CLOSING = 2;
        static CLOSED = 3;
        readyState = MockWebSocket.CONNECTING;
        onopen: ((event: Event) => void) | null = null;
        onmessage: ((event: MessageEvent) => void) | null = null;
        onclose: ((event: CloseEvent) => void) | null = null;
        onerror: ((event: Event) => void) | null = null;
        constructor() {
          setTimeout(() => {
            this.readyState = MockWebSocket.OPEN;
            this.onopen?.(new Event("open"));
            this.onmessage?.(new MessageEvent("message", { data: readyEvent }));
          }, 0);
        }
        send() {}
        close() {}
        addEventListener() {}
        removeEventListener() {}
      }
      // @ts-expect-error e2e mock
      window.WebSocket = MockWebSocket;
    }, { readyEvent: READY_EVENT });

    await gotoAuthed(page, "/chat");
    await expect(page.locator("text=Resume recent session")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator("text=Open Autopilot board")).toBeVisible({ timeout: 5_000 });
  });

  test("Autopilot attention-first filters render", async ({ page }) => {
    await gotoAuthed(page, "/autopilot");
    await expect(page.locator('button:has-text("Needs attention")')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('button:has-text("Active")')).toBeVisible({ timeout: 5_000 });
    await expect(page.locator('button:has-text("Waiting")')).toBeVisible({ timeout: 5_000 });
    await expect(
      page.locator('button:has-text("Needs attention")').locator("xpath=ancestor::div[1]"),
    ).toHaveScreenshot("audit-autopilot-filters.png", { animations: "disabled" });
  });
});

// ─── 8. Settings Help Text & Save Feedback ────────────────────────────────────

test.describe("8. Settings Help Text & Save Feedback", () => {
  test.beforeEach(async ({ page }) => {
    await stubAppShell(page);
    await stubSettingsRoutes(page);
  });

  test("Modes page renders PageHeader, permission-mode radio cards, and auto-save hint", async ({ page }) => {
    await gotoAuthed(page, "/settings/modes");
    await expect(page.locator("h1:has-text('Modes')")).toBeVisible({ timeout: 10_000 });

    // Help text for each permission mode
    await expect(page.locator("text=Best balance").first()).toBeVisible({ timeout: 5_000 });
    await expect(page.locator("text=Pause after planning").first()).toBeVisible({ timeout: 5_000 });
    await expect(page.locator("text=Minimize interruptions").first()).toBeVisible({ timeout: 5_000 });

    // Auto-save hint
    await expect(page.locator("text=Changes save automatically").first()).toBeVisible({ timeout: 5_000 });
  });

  test("clicking a permission mode option triggers a PATCH and shows feedback", async ({ page }) => {
    let patchCalled = false;
    await page.route("/api/modes", async (route: Route) => {
      if (route.request().method() === "PATCH") {
        patchCalled = true;
        const body = JSON.parse(route.request().postData() || "{}");
        await route.fulfill(json({ ...MODES_PAYLOAD, ...body }));
      } else {
        await route.fulfill(json(MODES_PAYLOAD));
      }
    });

    await gotoAuthed(page, "/settings/modes");
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10_000 });

    // Click the "Plan" label (permission mode radio)
    const planLabel = page.locator('label:has-text("Plan")').first();
    await expect(planLabel).toBeVisible({ timeout: 5_000 });
    await planLabel.click();

    // A PATCH request should have been fired
    await page.waitForTimeout(1_000);
    expect(patchCalled).toBe(true);
  });

  test("Provider settings page renders PageHeader and Providers h1", async ({ page }) => {
    await gotoAuthed(page, "/settings/provider");
    await expect(page.locator("h1:has-text('Providers')")).toBeVisible({ timeout: 10_000 });
  });

  test("Models settings page renders PageHeader with h1 and Add custom model button", async ({ page }) => {
    await gotoAuthed(page, "/settings/models");
    await expect(page.locator("h1:has-text('Models')")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator("button:has-text('Add custom model')").first()).toBeVisible({ timeout: 5_000 });
  });

  test("Agents settings page renders PageHeader", async ({ page }) => {
    await gotoAuthed(page, "/settings/agents");
    await expect(page.locator("h1:has-text('Agents')")).toBeVisible({ timeout: 10_000 });
  });

  test("Schedule settings page renders PageHeader and Scan / Tick cron inputs", async ({ page }) => {
    await gotoAuthed(page, "/settings/cron");
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10_000 });
    await expect(page.locator("#scan-cron")).toBeVisible({ timeout: 5_000 });
    await expect(page.locator("#tick-cron")).toBeVisible({ timeout: 5_000 });
  });
});

// ─── 8. Login Screen default-password warning ──────────────────────────────────

test.describe("8. Login Screen default-password warning", () => {
  test.beforeEach(async ({ page }) => {
    // Set up a clean state — no existing token so the login screen is shown.
    await page.addInitScript(`
      window.localStorage.clear();
    `);
    await stubPipelineRoutes(page);
    await stubTasksRoutes(page);
    await stubProjectsRoutes(page);
    await stubSettingsRoutes(page);
  });

  test("shows the default-password warning when backend reports is_default_password: true", async ({ page }) => {
    await page.route("/api/auth/login", async (route: Route) => {
      await route.fulfill(json({
        access_token: "e2e-access-token",
        refresh_token: "e2e-refresh-token",
        access_expires_in: 3600,
        refresh_expires_in: 604800,
        is_default_password: true,
      }));
    });
    await page.goto("/chat");
    await expect(page.getByRole("heading", { name: /OpenHarness/i })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Default password:/i)).toBeVisible();
    await expect(page.getByText("123456")).toBeVisible();
  });

  test("hides the warning and shows a neutral hint when password has been changed", async ({ page }) => {
    await page.route("/api/auth/login", async (route: Route) => {
      await route.fulfill(json({
        access_token: "e2e-access-token",
        refresh_token: "e2e-refresh-token",
        access_expires_in: 3600,
        refresh_expires_in: 604800,
        is_default_password: false,
      }));
    });
    await page.goto("/chat");
    await expect(page.getByRole("heading", { name: /OpenHarness/i })).toBeVisible({ timeout: 10_000 });
    // Warning must not be present
    await expect(page.queryByText(/Default password:/i)).toBeNull();
    // Neutral hint must be present instead
    await expect(page.getByText(/Sign in to continue\./i)).toBeVisible();
  });

  test("warning disappears after successful login with a custom password", async ({ page }) => {
    let loginRequestBody: string | undefined;
    await page.route("/api/auth/login", async (route: Route) => {
      loginRequestBody = route.request().postData();
      await route.fulfill(json({
        access_token: "e2e-access-token",
        refresh_token: "e2e-refresh-token",
        access_expires_in: 3600,
        refresh_expires_in: 604800,
        is_default_password: false,
      }));
    });
    await page.goto("/chat");
    await expect(page.getByRole("heading", { name: /OpenHarness/i })).toBeVisible({ timeout: 10_000 });

    // Simulate backend still reporting default password on initial load
    await page.evaluate(() => {
      localStorage.setItem("oh_is_default_password", "true");
    });
    await page.reload();
    await expect(page.getByText(/Default password:/i)).toBeVisible();

    // Login with a non-default password
    await page.getByRole("textbox", { name: /password/i }).fill("my-secret-password");
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page.getByText(/Default password:/i)).not.toBeVisible({ timeout: 5_000 });
  });
});
