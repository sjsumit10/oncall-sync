import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import Activity from "./Activity";
import Overview from "./Overview";

const SESSION = {
  user: {
    id: "u1",
    email: "ada@acme.dev",
    name: "Ada Lovelace",
    role: "owner",
    is_active: true,
    created_at: new Date().toISOString(),
  },
  organization: { id: "o1", name: "Acme", slug: "acme" },
  csrf_token: "t",
};

function stubApi(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const path = url.split("?")[0];
      const match = Object.keys(routes).find((route) => path.endsWith(route));
      return new Response(JSON.stringify(match ? routes[match] : []), { status: 200 });
    }),
  );
}

function renderWith(node: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Activity", () => {
  it("shows a run with its rule name and membership change", async () => {
    stubApi({
      "/auth/me": SESSION,
      "/activity": [
        {
          id: "run1",
          rule_id: "r1",
          rule_name: "DevOps on-call",
          trigger: "scheduled",
          status: "success",
          started_at: new Date().toISOString(),
          finished_at: new Date().toISOString(),
          duration_ms: 412,
          previous_members: ["U_ADA"],
          new_members: ["U_BOB"],
          actions: ["Updated group membership", "Announced the handoff"],
          problems: [],
          error: null,
        },
      ],
    });
    renderWith(<Activity />);

    // Readable without opening the rule.
    expect(await screen.findByText("DevOps on-call")).toBeDefined();
    expect(screen.getByText("U_ADA → U_BOB")).toBeDefined();
    expect(screen.getByText(/Announced the handoff/)).toBeDefined();
  });

  it("surfaces the error on a failed run", async () => {
    stubApi({
      "/auth/me": SESSION,
      "/activity": [
        {
          id: "run2",
          rule_id: "r1",
          rule_name: "DevOps on-call",
          trigger: "scheduled",
          status: "failed",
          started_at: new Date().toISOString(),
          finished_at: null,
          duration_ms: null,
          previous_members: null,
          new_members: null,
          actions: [],
          problems: [],
          error: "PagerDuty rejected our credentials",
        },
      ],
    });
    renderWith(<Activity />);

    expect(await screen.findByText("failed")).toBeDefined();
    expect(screen.getByText(/rejected our credentials/)).toBeDefined();
  });
});

describe("Overview", () => {
  it("calls out degraded rules and broken connections", async () => {
    stubApi({
      "/auth/me": SESSION,
      "/overview": {
        rules_total: 3,
        rules_by_status: { healthy: 1, degraded: 2 },
        rules_paused: 0,
        connections_needing_attention: 1,
        last_handoff_at: null,
        last_run_at: new Date().toISOString(),
      },
    });
    renderWith(<Overview />);

    expect(await screen.findByText("Needs attention")).toBeDefined();
    expect(screen.getByText(/2 rules are not tracking on-call/)).toBeDefined();
    expect(screen.getByText(/1 connection needs reconnecting/)).toBeDefined();
  });

  it("stays quiet when everything is healthy", async () => {
    stubApi({
      "/auth/me": SESSION,
      "/overview": {
        rules_total: 2,
        rules_by_status: { healthy: 2 },
        rules_paused: 0,
        connections_needing_attention: 0,
        last_handoff_at: new Date().toISOString(),
        last_run_at: new Date().toISOString(),
      },
    });
    renderWith(<Overview />);

    expect(await screen.findByText("Rules")).toBeDefined();
    expect(screen.queryByText("Needs attention")).toBeNull();
  });

  it("prompts a brand new org to connect its tools", async () => {
    stubApi({
      "/auth/me": SESSION,
      "/overview": {
        rules_total: 0,
        rules_by_status: {},
        rules_paused: 0,
        connections_needing_attention: 0,
        last_handoff_at: null,
        last_run_at: null,
      },
    });
    renderWith(<Overview />);

    expect(await screen.findByText(/Connect PagerDuty/)).toBeDefined();
  });
});
