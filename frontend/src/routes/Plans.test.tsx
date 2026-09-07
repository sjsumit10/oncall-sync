import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import Plans from "./Plans";
import type { PlanInfo } from "@/lib/types";

const PLAN_INFO: PlanInfo = {
  plan: "free",
  rule_limit: 5,
  rule_count: 2,
  tiers: [
    { plan: "free", rule_limit: 5 },
    { plan: "starter", rule_limit: 100 },
    { plan: "premium", rule_limit: 500 },
  ],
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

describe("Plans", () => {
  it("shows usage, the current plan, and a disabled coming-soon action on the others", async () => {
    stubApi({ "/org/plan": PLAN_INFO });
    renderWith(<Plans />);

    expect(await screen.findByText(/Using/)).toBeDefined();
    expect(screen.getByText("2")).toBeDefined();
    expect(screen.getByText("Current plan")).toBeDefined();

    // Only the two non-current tiers (Starter, Premium) get the disabled action.
    const comingSoon = screen.getAllByRole("button", { name: "Coming soon" });
    expect(comingSoon).toHaveLength(2);
    for (const button of comingSoon) {
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
  });
});
