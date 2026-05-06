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
- Open a provider card to edit:
  - API key
  - Base URL
- Verify connectivity before activating the profile.
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
- See each model's label, context window, and whether it is built in or custom.
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
- **Output Style** — select the response format
- **Theme** — select the UI theme

Changes are applied immediately so you can experiment without restarting the UI.

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
