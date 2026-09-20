import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function stubSession(status: number, body: unknown = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("routing", () => {
  it("redirects an unauthenticated visitor from a protected route to login", async () => {
    stubSession(401, { detail: "Not authenticated" });
    renderAt("/overview");

    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeDefined();
  });

  it("renders the app shell for an authenticated visitor", async () => {
    stubSession(200, {
      user: {
        id: "u1",
        email: "ada@acme.dev",
        name: "Ada Lovelace",
        role: "owner",
        is_active: true,
        created_at: new Date().toISOString(),
      },
      organization: { id: "o1", name: "Acme", slug: "acme" },
      csrf_token: "token",
    });
    renderAt("/overview");

    expect(await screen.findByText("Welcome, Ada")).toBeDefined();
    expect(screen.getByText(/Acme/)).toBeDefined();
  });

  it("shows the signup form without a session", async () => {
    stubSession(401, { detail: "Not authenticated" });
    renderAt("/signup");

    expect(await screen.findByRole("heading", { name: "Create your account" })).toBeDefined();
  });

  it("shows the public landing page at / without requiring a session", async () => {
    stubSession(401, { detail: "Not authenticated" });
    renderAt("/");

    expect(await screen.findByRole("heading", { name: /one mention away/ })).toBeDefined();
    expect(screen.getByRole("link", { name: "Log in" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Sign Up" })).toBeDefined();
  });

  it("links from login to the forgot-password page", async () => {
    stubSession(401, { detail: "Not authenticated" });
    renderAt("/login");

    const link = await screen.findByRole("link", { name: "Forgot password?" });
    expect((link as HTMLAnchorElement).getAttribute("href")).toBe("/forgot-password");
  });

  it("shows the forgot-password and reset-password pages without a session", async () => {
    stubSession(401, { detail: "Not authenticated" });
    renderAt("/forgot-password");
    expect(await screen.findByRole("heading", { name: "Reset your password" })).toBeDefined();

    renderAt("/reset-password?token=abc");
    expect(await screen.findByRole("heading", { name: "Set a new password" })).toBeDefined();
  });

  it("offers a dashboard link on the landing page for an authenticated visitor", async () => {
    stubSession(200, {
      user: {
        id: "u1",
        email: "ada@acme.dev",
        name: "Ada Lovelace",
        role: "owner",
        is_active: true,
        created_at: new Date().toISOString(),
      },
      organization: { id: "o1", name: "Acme", slug: "acme" },
      csrf_token: "token",
    });
    renderAt("/");

    expect(await screen.findByRole("link", { name: "Dashboard" })).toBeDefined();
    expect(screen.queryByRole("link", { name: "Log in" })).toBeNull();
  });

  it("shows the docs page, linked from the sidebar, for an authenticated visitor", async () => {
    stubSession(200, {
      user: {
        id: "u1",
        email: "ada@acme.dev",
        name: "Ada Lovelace",
        role: "owner",
        is_active: true,
        created_at: new Date().toISOString(),
      },
      organization: { id: "o1", name: "Acme", slug: "acme" },
      csrf_token: "token",
    });
    renderAt("/docs");

    expect(await screen.findByRole("heading", { name: "Docs", level: 1 })).toBeDefined();
    expect(screen.getByRole("link", { name: "Docs" })).toBeDefined();
    expect(screen.getByRole("heading", { name: /Connect an on-call provider/ })).toBeDefined();
    expect(screen.getByRole("heading", { name: /Connect a chat provider/ })).toBeDefined();
    expect(screen.getByRole("heading", { name: /Create a sync rule/ })).toBeDefined();
  });
});
