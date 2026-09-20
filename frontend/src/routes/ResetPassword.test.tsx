import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import ResetPassword from "./ResetPassword";

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

function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/overview" element={<p>overview page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("ResetPassword", () => {
  it("shows a message instead of the form when the link has no token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "Not authenticated" }), { status: 401 })),
    );

    renderAt("/reset-password");

    expect(await screen.findByText(/missing its token/)).toBeDefined();
    expect(screen.queryByLabelText("New password")).toBeNull();
  });

  it("blocks submission when the two passwords don't match", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "Not authenticated" }), { status: 401 })),
    );

    renderAt("/reset-password?token=abc123");
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("New password"), "a-long-password-1");
    await user.type(screen.getByLabelText("Confirm new password"), "a-different-password");

    expect(screen.getByText("Passwords don't match.")).toBeDefined();
    const button = screen.getByRole("button", { name: "Reset password" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("resets the password and redirects once signed in", async () => {
    const calls: { url: string; body: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.includes("/auth/password-reset/confirm")) {
          calls.push({ url, body: init?.body ? JSON.parse(init.body as string) : undefined });
          return new Response(JSON.stringify(SESSION), { status: 200 });
        }
        // /auth/me: unauthenticated until the reset confirms.
        return new Response(JSON.stringify({ detail: "Not authenticated" }), { status: 401 });
      }),
    );

    renderAt("/reset-password?token=abc123");
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("New password"), "a-long-password-1");
    await user.type(screen.getByLabelText("Confirm new password"), "a-long-password-1");
    await user.click(screen.getByRole("button", { name: "Reset password" }));

    expect(await screen.findByText("overview page")).toBeDefined();
    expect(calls).toHaveLength(1);
    expect(calls[0].body).toEqual({ token: "abc123", password: "a-long-password-1" });
  });
});
