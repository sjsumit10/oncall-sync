import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import Connections from "./Connections";

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
  csrf_token: "token",
};

const PAGERDUTY = {
  kind: "pagerduty",
  display_name: "PagerDuty",
  auth_modes: ["oauth", "api_key"],
  supports_oauth: true,
  oauth_configured: false,
};

const SLACK = {
  kind: "slack",
  display_name: "Slack",
  install_configured: true,
};

function stubApi(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const match = Object.keys(routes).find((path) => url.includes(path));
      return new Response(JSON.stringify(match ? routes[match] : []), { status: 200 });
    }),
  );
}

function renderPage(path = "/connections") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Connections />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Connections", () => {
  it("offers the API key form when no OAuth app is configured", async () => {
    stubApi({
      "/auth/me": SESSION,
      "/oncall/providers": [PAGERDUTY],
      "/oncall/connections": [],
    });
    renderPage();

    expect(await screen.findByText("Connect PagerDuty")).toBeDefined();
    expect(screen.getByLabelText("Read-only API key")).toBeDefined();
    expect(screen.queryByText("Connect with PagerDuty")).toBeNull();
  });

  it("shows the OAuth button when the deployment has an app registered", async () => {
    stubApi({
      "/auth/me": SESSION,
      "/oncall/providers": [{ ...PAGERDUTY, oauth_configured: true }],
      "/oncall/connections": [],
    });
    renderPage();

    expect(await screen.findByText("Connect with PagerDuty")).toBeDefined();
    expect(screen.getByLabelText("Or paste a read-only API key")).toBeDefined();
  });

  it("renders a connected provider instead of the connect form", async () => {
    stubApi({
      "/auth/me": SESSION,
      "/oncall/providers": [PAGERDUTY],
      "/oncall/connections": [
        {
          id: "c1",
          kind: "pagerduty",
          auth_mode: "api_key",
          display_name: "Acme PagerDuty",
          status: "active",
          scopes: null,
          last_verified_at: new Date().toISOString(),
          last_error: null,
          schedules_synced_at: null,
          created_at: new Date().toISOString(),
        },
      ],
    });
    renderPage();

    expect(await screen.findByText("Acme PagerDuty")).toBeDefined();
    expect(screen.getByText("Connected")).toBeDefined();
    expect(screen.queryByText("Connect PagerDuty")).toBeNull();
  });

  it("surfaces a failed OAuth callback", async () => {
    stubApi({
      "/auth/me": SESSION,
      "/oncall/providers": [PAGERDUTY],
      "/oncall/connections": [],
    });
    renderPage("/connections?error=invalid_state");

    expect(await screen.findByRole("alert")).toBeDefined();
    expect(screen.getByText(/invalid_state/)).toBeDefined();
  });
});

describe("Connections — Slack", () => {
  it("offers the install button when a Slack app is configured", async () => {
    stubApi({
      "/auth/me": SESSION,
      "/oncall/providers": [PAGERDUTY],
      "/oncall/connections": [],
      "/chat/providers": [SLACK],
      "/chat/connections": [],
    });
    renderPage();

    expect(await screen.findByText("Add to Slack")).toBeDefined();
  });

  it("warns when a workspace was installed without a user token", async () => {
    stubApi({
      "/auth/me": SESSION,
      "/oncall/providers": [PAGERDUTY],
      "/oncall/connections": [],
      "/chat/providers": [SLACK],
      "/chat/connections": [
        {
          id: "w1",
          kind: "slack",
          external_team_id: "T123",
          team_name: "Acme Workspace",
          status: "active",
          scopes: null,
          has_user_token: false,
          last_verified_at: null,
          last_error: null,
          groups_synced_at: null,
          created_at: new Date().toISOString(),
        },
      ],
    });
    renderPage();

    expect(await screen.findByText("Acme Workspace")).toBeDefined();
    expect(screen.getByText(/restricts who may manage user groups/)).toBeDefined();
  });

  it("shows a reinstall prompt when Slack revoked the token", async () => {
    stubApi({
      "/auth/me": SESSION,
      "/oncall/providers": [PAGERDUTY],
      "/oncall/connections": [],
      "/chat/providers": [SLACK],
      "/chat/connections": [
        {
          id: "w1",
          kind: "slack",
          external_team_id: "T123",
          team_name: "Acme Workspace",
          status: "needs_reauth",
          scopes: null,
          has_user_token: true,
          last_verified_at: null,
          last_error: "Slack reported app_uninstalled; reinstall required",
          groups_synced_at: null,
          created_at: new Date().toISOString(),
        },
      ],
    });
    renderPage();

    expect(await screen.findByText("Reconnect required")).toBeDefined();
    expect(screen.getByText(/reinstall required/)).toBeDefined();
  });
});
