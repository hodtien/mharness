# Web UI Pipeline Guide

The Pipeline page is the Web UI view for autopilot work items.
It is designed for tracking ideas, reviewing progress, and driving tasks through the pipeline.

## Where to find it

Open **Pipeline** from the sidebar. The page shows the current autopilot cards and the latest pipeline policy view.

## What the pipeline dashboard shows

The dashboard centers around work cards with information such as:

- title
- body / summary
- status
- source kind
- score
- labels
- timestamps
- model and attempt count, when available
- metadata such as the latest note or resume availability

This makes it easier to see which work is queued, running, waiting for verification, or already completed.

## Kanban workflow

Use the pipeline board like a kanban:

- **Queued** items are waiting to be picked up.
- **Accepted** items have been approved for processing.
- **Running / verifying / repairing** items are actively moving through the pipeline.
- **Completed / merged** items are finished.
- **Rejected / failed / killed** items are no longer active.

The page also lets you submit a new manual idea directly into the queue.

## Auto review

Auto review is part of the pipeline workflow for validating changes before a task is considered done.

In practice, this means:

- the pipeline records review-related progress in the card metadata and journal entries,
- verification and repair phases remain visible in the dashboard,
- you can follow the task as it moves from implementation to review to completion.

When a task is resumed, the UI can also surface resume-related metadata so you can continue from the right point.

## Policy view

The pipeline page includes a policy editor/view that shows the current autopilot policy as YAML.
Use it when you need to inspect or update the workflow rules that drive the pipeline.

## Related docs

- [`WEBUI.md`](./WEBUI.md)
- [`WEBUI-SETTINGS.md`](./WEBUI-SETTINGS.md)
- [`TASKS.md`](../TASKS.md)
