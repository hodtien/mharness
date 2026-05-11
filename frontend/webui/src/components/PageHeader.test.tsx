import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import PageHeader from "./PageHeader";

describe("PageHeader", () => {
  it("renders title as h1", () => {
    render(<PageHeader title="My Page" />);
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("My Page");
  });

  it("renders description when provided", () => {
    render(<PageHeader title="My Page" description="What this page does." />);
    expect(screen.getByText("What this page does.")).toBeTruthy();
  });

  it("does not render description when omitted", () => {
    const { container } = render(<PageHeader title="My Page" />);
    expect(container.querySelector("p")).toBeNull();
  });

  it("renders primaryAction when provided", () => {
    render(
      <PageHeader
        title="My Page"
        primaryAction={<button type="button">Add Item</button>}
      />,
    );
    expect(screen.getByRole("button", { name: "Add Item" })).toBeTruthy();
  });

  it("renders secondaryAction when provided", () => {
    render(
      <PageHeader
        title="My Page"
        secondaryAction={<button type="button">Filter</button>}
      />,
    );
    expect(screen.getByRole("button", { name: "Filter" })).toBeTruthy();
  });

  it("renders metadata items", () => {
    render(
      <PageHeader
        title="My Page"
        metadata={[
          { label: "Project", value: "my-repo" },
          { label: "Jobs", value: "3" },
        ]}
      />,
    );
    expect(screen.getByText("Project")).toBeTruthy();
    expect(screen.getByText("my-repo")).toBeTruthy();
    expect(screen.getByText("Jobs")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
  });

  it("renders dot separators between metadata items", () => {
    render(
      <PageHeader
        title="My Page"
        metadata={[
          { label: "Project", value: "my-repo" },
          { label: "Jobs", value: "3" },
        ]}
      />,
    );
    const dots = screen.getAllByText("·");
    expect(dots.length).toBeGreaterThan(0);
  });

  it("renders accent class on value when specified", () => {
    const { container } = render(
      <PageHeader
        title="My Page"
        metadata={[
          { label: "Status", value: "Running", accent: "cyan" },
        ]}
      />,
    );
    // value element should have cyan class
    const valueEl = container.querySelector(".text-cyan-300");
    expect(valueEl).toBeTruthy();
  });

  it("renders nothing when metadata is empty array", () => {
    const { container } = render(<PageHeader title="My Page" metadata={[]} />);
    expect(container.querySelector("[class*='mt-2']")).toBeNull();
  });

  it("renders nothing when metadata is undefined", () => {
    const { container } = render(<PageHeader title="My Page" />);
    expect(container.querySelector("[class*='mt-2']")).toBeNull();
  });

  it("renders both primary and secondary actions", () => {
    render(
      <PageHeader
        title="My Page"
        primaryAction={<button type="button">Primary</button>}
        secondaryAction={<button type="button">Secondary</button>}
      />,
    );
    expect(screen.getByRole("button", { name: "Primary" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Secondary" })).toBeTruthy();
  });
});
