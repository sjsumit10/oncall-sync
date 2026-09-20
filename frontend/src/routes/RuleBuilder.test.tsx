import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import RuleBuilder from "./RuleBuilder";

// jsdom has no ResizeObserver, which Radix's Select trigger reads on mount.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

const SESSION = {
  user: {
    id: "u1",
    email: "ada@acme.dev",
    name: "Ada",
    role: "owner",
    is_active: true,
    created_at: new Date().toISOString(),
  },
  organization: { id: "o1", name: "Acme", slug: "acme" },
  csrf_token: "t",
};

const RULE = {
  id: "r1",
  name: "DevOps on-call",
  enabled: true,
  oncall_connection_id: "oc1",
  schedule_external_id: "PSCHED1",
  escalation_levels: [1],
  chat_connection_id: "cc1",
  group_external_id: "S_DEVOPS",
  fallback_chat_user_id: null,
  notify_channel_external_id: "C_OPS",
  notify_on_change: true,
  message_template: null,
  status: "healthy",
  last_synced_at: null,
  last_error: null,
  consecutive_failures: 0,
  created_at: new Date().toISOString(),
};

const CONNECTIONS: Record<string, unknown> = {
  "/oncall/connections": [{ id: "oc1", kind: "pagerduty" }],
  "/chat/connections": [{ id: "cc1", kind: "slack" }],
  "/schedules": [{ external_id: "PSCHED1", name: "Primary", timezone: "UTC" }],
  "/groups": [{ external_id: "S_DEVOPS", handle: "devops-on-call", name: "DevOps" }],
  "/channels": [{ external_id: "C_OPS", name: "ops", bot_is_member: true }],
  "/template/preview": { text: "", blocks: [], problems: [], variables: {} },
};

function renderEdit() {
  const routes: Record<string, unknown> = { ...CONNECTIONS, "/auth/me": SESSION, "/rules/r1": RULE };
  const calls: { method: string; url: string; body: unknown }[] = [];

  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method !== "GET") {
        calls.push({
          method,
          url,
          body: init?.body ? JSON.parse(init.body as string) : undefined,
        });
      }
      const path = url.split("?")[0];
      const match = Object.keys(routes).find((route) => path.endsWith(route));
      return new Response(JSON.stringify(match ? routes[match] : []), { status: 200 });
    }),
  );

  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/rules/r1/edit"]}>
        <Routes>
          <Route path="/rules/:ruleId/edit" element={<RuleBuilder />} />
          <Route path="/rules" element={<p>rules list</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return calls;
}

function renderCreate() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const path = url.split("?")[0];
      const match = Object.keys(CONNECTIONS).find((route) => path.endsWith(route));
      return new Response(JSON.stringify(match ? CONNECTIONS[match] : []), { status: 200 });
    }),
  );
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/rules/new"]}>
        <Routes>
          <Route path="/rules/new" element={<RuleBuilder />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("RuleBuilder edit mode", () => {
  it("seeds the form from the existing rule and locks the schedule and group", async () => {
    renderEdit();

    expect(await screen.findByRole("heading", { name: "Edit sync rule" })).toBeDefined();
    expect(await screen.findByDisplayValue("DevOps on-call")).toBeDefined();
    // Schedule and group render as read-only text, not a picker, in edit mode.
    expect(await screen.findByText("Primary (UTC)")).toBeDefined();
    expect(screen.getAllByText(/Can't be changed after creation/).length).toBeGreaterThan(0);
  });

  it("PATCHes only the mutable fields on save", async () => {
    const calls = renderEdit();
    const user = userEvent.setup();

    await screen.findByDisplayValue("DevOps on-call");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.url).toContain("/rules/r1");
    expect(patch?.body).toMatchObject({
      name: "DevOps on-call",
      escalation_levels: [1],
      notify_channel_external_id: "C_OPS",
      notify_on_change: true,
      fallback_chat_user_id: null,
    });
    // Immutable fields must never be sent from the edit form.
    expect(patch?.body).not.toHaveProperty("oncall_connection_id");
    expect(patch?.body).not.toHaveProperty("chat_connection_id");
    expect(patch?.body).not.toHaveProperty("schedule_external_id");
    expect(patch?.body).not.toHaveProperty("group_external_id");
  });
});

describe("RuleBuilder create mode", () => {
  it("still shows editable schedule and group pickers", async () => {
    renderCreate();

    expect(await screen.findByRole("heading", { name: "New sync rule" })).toBeDefined();
    expect(await screen.findByText("Choose a schedule…")).toBeDefined();
    expect(screen.queryByText(/Can't be changed after creation/)).toBeNull();
  });
});
