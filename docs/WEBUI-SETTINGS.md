# Web UI Settings Guide

The Web UI exposes the main runtime settings in a few dedicated pages under **Settings** in the sidebar.

## Where to find them

- **Modes** — `/settings/modes`
- **Provider** — `/settings/provider`
- **Models** — `/settings/models`
- **Agents** — `/settings/agents`

These pages update the local OpenHarness configuration through the same backend the terminal uses.

## Provider settings

Use **Provider** to configure which API provider new sessions should use.

What you can do:

- View the available provider profiles.
- See whether a provider is **Active**, **Configured**, or **Not configured**.
- See connection status on each provider card without reloading the page.
- Open a provider card to edit:
  - API key
  - Base URL
- Verify connectivity before activating the profile.
- Use **Verify all** to check every configured provider at once.
- Review verification details such as latency, model count, and last verified time.
- Activate a provider for new sessions.

Typical flow:

1. Open **Settings → Provider**.
2. Select the provider you want to configure.
3. Enter the API key and, if needed, a custom base URL.
4. Click **Verify** to check the connection.
5. Click **Activate** when the provider is ready.

## Models settings

Use **Models** to manage the model list available to your providers.

What you can do:

- Browse models grouped by provider.
- Search and filter models by ID or label.
- See each model's label, context window, and whether it is built in or custom.
- Compare capability badges when metadata is available, such as vision, tools, long-context, or fast.
- Review clearer grouping and sorting for built-in versus custom models.
- Add a custom model to a provider.
- Remove a custom model when it is no longer needed.

Notes:

- Built-in models cannot be deleted from the UI.
- Custom models are stored in the local settings and are available to agent configuration pages.

## Agents settings

Use **Agents** to tune per-agent defaults.

What you can do:

- Inspect each agent's current model, effort, and permission mode.
- Open a detail view to inspect the agent definition.
- Preview the full system prompt/body in an expandable modal.
- Clone an existing agent config to create a new agent from a template.
- Validate or test an edited agent config before saving.
- See the source file path and whether the definition has local changes.
- Edit an agent inline.
- Save changes back to the local agent definition.

The agent editor lets you choose:

- **Model** — pick a model from the available model list.
- **Effort** — choose `low`, `medium`, or `high`.
- **Permission mode** — choose `default`, `plan`, or `full_auto`.

## Modes settings

Use **Modes** to control runtime behavior for the current session.

Available controls:

- **Permission Mode** — `default`, `plan`, `full_auto`
- **Effort** — `low`, `medium`, `high`
- **Passes** — agent pass count from `1` to `5`
- **Fast Mode** — toggle on/off
- **Vim keybindings** — toggle on/off
- **Notifications** — toggle WebUI/autopilot event notification preferences
- **Auto-compact** — configure transcript compaction behavior when supported by the current runtime
- **Output Style** — select the response format
- **Theme** — select the UI theme

Changes are applied immediately so you can experiment without restarting the UI.

## Form UX

Settings pages share the same form feedback patterns:

- A dirty-state indicator appears when the page has unsaved changes.
- Navigating away with unsaved changes triggers a warning.
- Inline validation messages appear next to invalid fields.
- Save/apply actions show a visible success state when they complete.
- Keyboard navigation and focus states are kept consistent across the settings pages.

## Practical workflow

A common setup looks like this:

1. Configure the provider you want to use.
2. Verify the provider connection.
3. Make sure the required models are available.
4. Tune agent defaults for your workflow.
5. Adjust session modes when you need a faster or more automated run.

## Related docs

- [`WEBUI.md`](./WEBUI.md)
- [`WEBUI-PIPELINE.md`](./WEBUI-PIPELINE.md)
- [`frontend/webui/README.md`](../frontend/webui/README.md)
