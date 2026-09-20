import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import ForgotPassword from "./ForgotPassword";

function renderWith(node: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("ForgotPassword", () => {
  it("shows a generic success message after requesting a reset", async () => {
    const calls: { url: string; body: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, body: init?.body ? JSON.parse(init.body as string) : undefined });
        return new Response(null, { status: 204 });
      }),
    );

    renderWith(<ForgotPassword />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Email"), "ada@acme.dev");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));

    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeDefined();
    expect(screen.getByText(/5 minutes/)).toBeDefined();
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toContain("/auth/password-reset/request");
    expect(calls[0].body).toEqual({ email: "ada@acme.dev" });
  });

  it("shows an error when the request itself fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "Too many attempts." }), { status: 429 })),
    );

    renderWith(<ForgotPassword />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Email"), "ada@acme.dev");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));

    expect(await screen.findByText("Too many attempts.")).toBeDefined();
    expect(screen.queryByRole("heading", { name: "Check your email" })).toBeNull();
  });
});
