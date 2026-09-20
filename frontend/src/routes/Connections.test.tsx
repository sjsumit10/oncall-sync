import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

describe("Connections — Slack channels", () => {
  const WORKSPACE = {
    id: "w1",
    kind: "slack",
    external_team_id: "T123",
    team_name: "Acme Workspace",
    status: "active",
    scopes: null,
    has_user_token: true,
    external_resource_id: null,
    last_verified_at: null,
    last_error: null,
    groups_synced_at: null,
    created_at: new Date().toISOString(),
  };

  // Path-precise (endsWith) matching, unlike the file's shared `stubApi`
  // (substring match) — needed here because "/chat/connections" is itself a
  // substring of "/chat/connections/w1/channels", which the shared helper
  // would otherwise match first.
  function stubPreciseApi(routes: Record<string, unknown>) {
    const calls: { url: string }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push({ url });
        const path = url.split("?")[0];
        const match = Object.keys(routes).find((route) => path.endsWith(route));
        return new Response(JSON.stringify(match ? routes[match] : []), { status: 200 });
      }),
    );
    return calls;
  }

  it("shows whether the bot has joined each cached channel", async () => {
    stubPreciseApi({
      "/auth/me": SESSION,
      "/oncall/providers": [PAGERDUTY],
      "/oncall/connections": [],
      "/chat/providers": [SLACK],
      "/chat/connections": [WORKSPACE],
      "/channels": [
        { id: "ch1", external_id: "C1", name: "ops", is_private: false, bot_is_member: true },
        { id: "ch2", external_id: "C2", name: "random", is_private: false, bot_is_member: false },
      ],
    });
    renderPage();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Channels" }));

    expect(await screen.findByText("#ops")).toBeDefined();
    expect(screen.getByText("#random")).toBeDefined();
    expect(screen.getByText("Bot has joined")).toBeDefined();
    expect(screen.getByText("Bot not in channel")).toBeDefined();
  });

  it("refreshes the channel list on request", async () => {
    const calls = stubPreciseApi({
      "/auth/me": SESSION,
      "/oncall/providers": [PAGERDUTY],
      "/oncall/connections": [],
      "/chat/providers": [SLACK],
      "/chat/connections": [WORKSPACE],
      "/channels": [
        { id: "ch1", external_id: "C1", name: "ops", is_private: false, bot_is_member: false },
      ],
    });
    renderPage();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Channels" }));
    await screen.findByText("#ops");
    await user.click(await screen.findByRole("button", { name: "Refresh" }));

    await waitFor(() =>
      expect(calls.some((c) => c.url.includes("/channels?refresh=true"))).toBe(true),
    );
  });
});
