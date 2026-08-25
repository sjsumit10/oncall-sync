import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TemplateEditor } from "./TemplateEditor";

function stubPreview(response: unknown) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(response), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function Harness() {
  const [value, setValue] = useState("");
  return <TemplateEditor value={value} onChange={setValue} />;
}

function renderEditor() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <Harness />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("TemplateEditor", () => {
  it("shows the rendered preview and the available variables", async () => {
    stubPreview({
      text: "<@U024BE7LH> is now on call",
      blocks: [{ type: "section" }, { type: "context" }],
      problems: [],
      variables: { oncall_mention: "<@U024BE7LH>", handle: "devops-on-call" },
    });
    renderEditor();

    expect(await screen.findByText("<@U024BE7LH> is now on call")).toBeDefined();
    expect(screen.getByText("{{ oncall_mention }}")).toBeDefined();
    expect(screen.getByText(/context line/)).toBeDefined();
  });

  it("surfaces a template problem instead of a preview", async () => {
    stubPreview({
      text: "",
      blocks: [],
      problems: ["Unknown variable: oncall_manager. Available: handle, oncall_mention"],
      variables: { handle: "devops-on-call" },
    });
    renderEditor();

    expect(await screen.findByRole("alert")).toBeDefined();
    expect(screen.getByText(/oncall_manager/)).toBeDefined();
  });

  it("debounces so typing does not fire a request per character", async () => {
    const fetchMock = stubPreview({ text: "hi", blocks: [], problems: [], variables: {} });
    renderEditor();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const afterInitial = fetchMock.mock.calls.length;

    await userEvent.type(screen.getByRole("textbox"), "hello there");

    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(afterInitial));
    expect(fetchMock.mock.calls.length).toBeLessThan(afterInitial + 11);
  });
});
