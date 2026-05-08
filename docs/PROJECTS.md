# Multi-Project Support

OpenHarness supports managing multiple project directories through a **project registry**.
Each project maps a friendly name to a filesystem path, letting you switch between
repositories or workspaces without reconfiguring `cwd` or environment variables.

---

## How It Works

- The **registry** is a single JSON file at `~/.openharness/projects.json`.
- Exactly **one** project is *active* at a time. The active project determines:
  - The working directory for new sessions.
  - Project-specific memory and context.
- Adding, removing, or switching projects does not delete any files or git state.

### Registry file

```
~/.openharness/projects.json
```

Example content:

```json
{
  "projects": [
    {
      "id": "my-app",
      "name": "My App",
      "path": "/Users/you/code/my-app",
      "description": "Main web app",
      "created_at": "2025-01-15T10:00:00Z",
      "updated_at": "2025-01-15T10:00:00Z"
    }
  ],
  "active_project_id": "my-app"
}
```

> **Note**: `~/.openharness/` is `XDG_CONFIG_HOME` aware. On Linux you may
> find the file at `$XDG_CONFIG_HOME/openharness/projects.json` instead.

---

## CLI Commands

All project commands live under `oh project`:

### `oh project list`

List all registered projects. The active project is marked with `(*)`:

```
oh project list
```

### `oh project add`

Register a new project:

```
oh project add --name "My App" --path /Users/you/code/my-app [--description "optional"]
```

Requirements:
- The path must be an **existing directory**.
- No duplicate paths are allowed.
- A project with the same name slug must not already exist.

### `oh project switch`

Set the active project (by name or ID):

```
oh project switch my-app
```

New sessions will use the project's directory as their working directory.

### `oh project remove`

Remove a project from the registry:

```
oh project remove my-app
```

You will be prompted for confirmation. The **active project cannot be deleted**
while it is active; switch to another project first.

### `oh project info`

Show details for a specific project, or the active project if no argument is given:

```
oh project info
oh project info my-app
```

---

## Web UI — Projects Page

In the Web UI, navigate to **Projects** from the sidebar. The page shows all
registered projects in a card grid.

### Add a project

1. Click **+ New Project**.
2. Fill in:
   - **Project Name** — a friendly label.
   - **Project Path** — absolute path to an existing directory on this machine.
   - **Description** — optional, for your own reference.
3. Click **Create Project**.

### Switch to a project

Find the project card and click **Activate**. The card gets a cyan border
and an **active** badge. Subsequent sessions open in that project's directory.

### Edit a project

Click **Edit** on any card to change the name or description inline.
Click **Save** to persist.

### Delete a project

Click **Delete** on the card. A confirmation dialog appears.
The active project cannot be deleted — switch away first.

---

## Session and Memory Interaction

- When you switch projects, active WebSocket sessions receive a
  `project_switched` event and update their working directory.
- Project-specific `MEMORY.md` files live inside each project directory.
- Switching projects does **not** move or rename git branches — those are
  independent of the project registry.

---

## API Reference

### Endpoints

| Method | Path                        | Description                        |
|--------|-----------------------------|------------------------------------|
| GET    | `/api/projects`             | List all projects + active ID       |
| POST   | `/api/projects`             | Register a new project             |
| PATCH  | `/api/projects/{id}`         | Update name or description          |
| DELETE | `/api/projects/{id}`         | Remove a project (not active)      |
| POST   | `/api/projects/{id}/activate` | Set as active project, broadcast  |

All endpoints require a valid session token in the `Authorization` header.

### GET /api/projects

```json
{
  "projects": [
    {
      "id": "my-app",
      "name": "My App",
      "path": "/Users/you/code/my-app",
      "description": "Main web app",
      "created_at": "2025-01-15T10:00:00+00:00",
      "updated_at": "2025-01-15T10:00:00+00:00",
      "is_active": true
    }
  ],
  "active_project_id": "my-app"
}
```

### POST /api/projects

```json
// Request
{
  "name": "My App",
  "path": "/Users/you/code/my-app",
  "description": "Main web app"
}
```

```json
// Response 201
{
  "id": "my-app",
  "name": "My App",
  "path": "/Users/you/code/my-app",
  "description": "Main web app",
  "created_at": "2025-01-15T10:00:00+00:00",
  "updated_at": "2025-01-15T10:00:00+00:00",
  "is_active": false
}
```

Errors:
- `400` — path is not a directory.
- `409` — path already registered.

### POST /api/projects/{id}/activate

```json
// Response 200
{
  "ok": true,
  "project": { ... }
}
```

Emits a `project_switched` WebSocket event to all connected sessions.

---

## Related Docs

- [`WEBUI.md`](./WEBUI.md) — Web UI overview
- [`WEBUI-SETTINGS.md`](./WEBUI-SETTINGS.md) — Settings pages guide
- [`frontend/webui/README.md`](../frontend/webui/README.md) — Web UI developer guide