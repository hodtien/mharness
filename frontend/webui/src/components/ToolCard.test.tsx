import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ToolCard from "./ToolCard";
import { getContentSize } from "./ToolCard";

describe("ToolCard", () => {
  describe("collapsed/expanded behavior", () => {
    it("renders collapsed by default for large content", () => {
      const longText = "a".repeat(2000);
      render(<ToolCard role="tool_result" tool_name="bash" text={longText} />);

      // Should show header with expand icon
      expect(screen.getByText(/result/)).toBeTruthy();
      expect(screen.getByText(/bash/)).toBeTruthy();
      // Should show ▶ icon (collapsed)
      expect(screen.getByText("▶")).toBeTruthy();
    });

    it("auto-expands for small content", () => {
      render(<ToolCard role="tool_result" tool_name="bash" text="short output" />);

      // Should show ▼ icon (expanded)
      expect(screen.getByText("▼")).toBeTruthy();
      // Should show output content
      expect(screen.getByText("short output")).toBeTruthy();
    });

    it("auto-expands tool role (input)", () => {
      render(
        <ToolCard
          role="tool"
          tool_name="bash"
          tool_input={{ command: "ls" }}
          text=""
        />
      );

      // Should show ▼ icon (expanded)
      expect(screen.getByText("▼")).toBeTruthy();
      // Should show Input label
      expect(screen.getByText("Input")).toBeTruthy();
    });

    it("toggles to expanded state on click", () => {
      const longText = "a".repeat(2000);
      render(<ToolCard role="tool_result" tool_name="bash" text={longText} />);

      // Initially collapsed
      expect(screen.getByText("▶")).toBeTruthy();

      // Click header to expand
      fireEvent.click(screen.getByText(/result/));
      expect(screen.getByText("▼")).toBeTruthy();
    });

    it("toggles back to collapsed state on second click", () => {
      const longText = "a".repeat(2000);
      render(<ToolCard role="tool_result" tool_name="bash" text={longText} />);

      // Expand
      fireEvent.click(screen.getByText(/result/));
      expect(screen.getByText("▼")).toBeTruthy();

      // Collapse
      fireEvent.click(screen.getByText(/result/));
      expect(screen.getByText("▶")).toBeTruthy();
    });
  });

  describe("size-based behavior", () => {
    it("auto-expands small content (<=200 chars)", () => {
      const shortText = "echo hello";
      render(<ToolCard role="tool_result" tool_name="bash" text={shortText} />);

      // Should show output content (expanded)
      expect(screen.getByText("echo hello")).toBeTruthy();
    });

    it("shows collapsed header for medium content (200-1500 chars)", () => {
      const mediumText = "a".repeat(500);
      render(<ToolCard role="tool_result" tool_name="bash" text={mediumText} />);

      // Should show header
      expect(screen.getByText(/bash/)).toBeTruthy();
      // Should show collapsed indicator
      expect(screen.getByText("▶")).toBeTruthy();
    });

    it("shows semantic summary for large content (>1500 chars)", () => {
      const longText = "some important output\nline2\nline3";
      render(<ToolCard role="tool_result" tool_name="bash" text={longText} />);

      // Should show semantic summary
      expect(screen.getByText(/some important output/)).toBeTruthy();
    });
  });

  describe("status indicators", () => {
    it("shows error styling for failed tool results", () => {
      render(
        <ToolCard
          role="tool_result"
          tool_name="bash"
          text="Error: file not found"
          is_error={true}
        />
      );

      // Should show error badge
      expect(screen.getByText(/error/)).toBeTruthy();
    });

    it("shows amber styling for tool input", () => {
      render(
        <ToolCard
          role="tool"
          tool_name="bash"
          tool_input={{ command: "ls -la" }}
          text=""
        />
      );

      // Should show tool badge
      expect(screen.getByText(/tool/)).toBeTruthy();
    });
  });

  describe("content truncation", () => {
    it("truncates very large content (>2000 chars)", () => {
      const veryLongText = "x".repeat(3000);
      render(<ToolCard role="tool_result" tool_name="bash" text={veryLongText} />);

      // Expand to see content
      fireEvent.click(screen.getByText(/result/));

      // Should show truncation message
      expect(screen.getByText(/\+ \d+ chars truncated/)).toBeTruthy();
    });
  });
});

describe("getContentSize", () => {
  it("returns 'small' for text <= 200 chars", () => {
    expect(getContentSize("")).toBe("small");
    expect(getContentSize("a".repeat(200))).toBe("small");
  });

  it("returns 'medium' for text 201-1500 chars", () => {
    expect(getContentSize("a".repeat(201))).toBe("medium");
    expect(getContentSize("a".repeat(1500))).toBe("medium");
  });

  it("returns 'large' for text > 1500 chars", () => {
    expect(getContentSize("a".repeat(1501))).toBe("large");
    expect(getContentSize("a".repeat(5000))).toBe("large");
  });
});