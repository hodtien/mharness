import { beforeEach, describe, expect, it, vi } from "vitest";
import { openWebSocket } from "./client";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readonly url: string;
  readyState = FakeWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  closeCalls: Array<{ code?: number; reason?: string }> = [];

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close(code?: number, reason?: string) {
    this.readyState = FakeWebSocket.CLOSED;
    this.closeCalls.push({ code, reason });
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  closeFromServer(code: number) {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code });
  }
}

describe("openWebSocket", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => (key === "oh_token" ? "secret" : null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
    Object.defineProperty(window, "location", {
      value: { protocol: "http:", host: "localhost:8765", search: "", pathname: "/chat", hash: "" },
      writable: true,
    });
  });

  it("does not surface a banner detail for manual closes", () => {
    const statuses: Array<[string, string | undefined]> = [];
    const handle = openWebSocket("session-1", vi.fn(), (status, detail) => {
      statuses.push([status, detail]);
    });

    const socket = FakeWebSocket.instances[0];
    socket.open();
    handle.close();
    socket.closeFromServer(1000);

    expect(socket.closeCalls).toEqual([{ code: 1000, reason: "client closing" }]);
    expect(statuses).toEqual([
      ["open", undefined],
      ["closed", undefined],
    ]);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("reconnects after abnormal closes and clears stale detail when reopened", () => {
    const statuses: Array<[string, string | undefined]> = [];
    openWebSocket("session-1", vi.fn(), (status, detail) => {
      statuses.push([status, detail]);
    });

    FakeWebSocket.instances[0].closeFromServer(1006);
    expect(statuses).toEqual([["closed", "code=1006"]]);

    vi.advanceTimersByTime(1500);
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(statuses[statuses.length - 1]).toEqual(["connecting", "reconnecting"]);

    FakeWebSocket.instances[1].open();
    expect(statuses[statuses.length - 1]).toEqual(["open", undefined]);
  });

  it("surfaces auth failures without retrying", () => {
    const statuses: Array<[string, string | undefined]> = [];
    openWebSocket("session-1", vi.fn(), (status, detail) => {
      statuses.push([status, detail]);
    });

    FakeWebSocket.instances[0].closeFromServer(1008);
    vi.advanceTimersByTime(1500);

    expect(statuses).toEqual([["closed", "Authentication failed (code=1008)"]]);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
