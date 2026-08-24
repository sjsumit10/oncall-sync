import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RulePreviewPanel } from "./RulePreviewPanel";
import Rules from "./Rules";
import type { RulePreview } from "@/lib/types";

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
  status: "healthy",
  last_synced_at: null,
  last_error: null,
  consecutive_failures: 0,
  created_at: new Date().toISOString(),
};

function stubApi(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      // Match on the path suffix so "/chat/connections" does not shadow the
      // nested "/groups" and "/schedules" routes hanging off it.
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

const BASE_PREVIEW: RulePreview = {
  evaluated_at: new Date().toISOString(),
  schedule_name: "Primary",
  on_call: [],
  resolved: [],
  unmapped: [],
  desired_member_ids: [],
  current_member_ids: [],
  would_write: true,
  would_add: [],
  would_remove: [],
  used_fallback: false,
  next_change_at: null,
  problems: [],
};

afterEach(() => vi.unstubAllGlobals());

describe("Rules", () => {
  it("prompts to connect providers when none exist", async () => {
    stubApi({ "/auth/me": SESSION, "/oncall/connections": [], "/chat/connections": [] });
    renderWith(<Rules />);

    expect(await screen.findByText(/Connect an on-call provider/)).toBeDefined();
  });

  it("lists a rule with its handle and schedule", async () => {
    stubApi({
      "/auth/me": SESSION,
      "/oncall/connections": [{ id: "oc1", kind: "pagerduty" }],
      "/chat/connections": [{ id: "cc1", kind: "slack" }],
      "/rules": [RULE],
      "/schedules": [{ external_id: "PSCHED1", name: "Primary", timezone: "UTC" }],
      "/groups": [{ external_id: "S_DEVOPS", handle: "devops-on-call", name: "DevOps" }],
    });
    renderWith(<Rules />);

    expect(await screen.findByText("DevOps on-call")).toBeDefined();
    expect(await screen.findByText("@devops-on-call")).toBeDefined();
    expect(await screen.findByText("← Primary")).toBeDefined();
  });
});

describe("RulePreviewPanel", () => {
  it("says the handle is untouched when the rule would not write", () => {
    renderWith(
      <RulePreviewPanel
        preview={{
          ...BASE_PREVIEW,
          would_write: false,
          current_member_ids: ["U_STALE"],
          unmapped: [{ external_id: "PU9", name: "Contractor", email: "c@vendor.dev" }],
          problems: ["No chat account matched for: Contractor"],
        }}
      />,
    );

    expect(screen.getByText(/left exactly as it is/)).toBeDefined();
    expect(screen.getByText(/No chat account matched/)).toBeDefined();
    expect(screen.queryByText(/Would remove/)).toBeNull();
  });

  it("shows the additions and removals a real run would make", () => {
    renderWith(
      <RulePreviewPanel
        preview={{
          ...BASE_PREVIEW,
          desired_member_ids: ["U_ADA"],
          current_member_ids: ["U_STALE"],
          would_add: ["U_ADA"],
          would_remove: ["U_STALE"],
          resolved: [
            {
              provider_user: { external_id: "PU1", name: "Ada", email: "ada@acme.dev" },
              chat_user_id: "U_ADA",
              chat_user_name: "Ada",
              source: "auto_email",
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("Would add: U_ADA")).toBeDefined();
    expect(screen.getByText("Would remove: U_STALE")).toBeDefined();
  });

  it("reports when nothing would change", () => {
    renderWith(
      <RulePreviewPanel
        preview={{ ...BASE_PREVIEW, desired_member_ids: ["U_ADA"], current_member_ids: ["U_ADA"] }}
      />,
    );
    expect(screen.getByText(/Already correct/)).toBeDefined();
  });

  it("flags fallback use", () => {
    renderWith(
      <RulePreviewPanel
        preview={{ ...BASE_PREVIEW, desired_member_ids: ["U_LEAD"], used_fallback: true }}
      />,
    );
    expect(screen.getByText(/does not allow an empty user group/)).toBeDefined();
  });
});
