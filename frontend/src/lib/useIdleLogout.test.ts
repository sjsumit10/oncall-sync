import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useIdleLogout } from "./useIdleLogout";

describe("useIdleLogout", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("does not fire before the timeout elapses", () => {
    const onIdle = vi.fn();
    renderHook(() => useIdleLogout(true, 1000, onIdle));

    vi.advanceTimersByTime(999);
    expect(onIdle).not.toHaveBeenCalled();
  });

  it("fires once the timeout elapses with no activity", () => {
    const onIdle = vi.fn();
    renderHook(() => useIdleLogout(true, 1000, onIdle));

    vi.advanceTimersByTime(1000);
    expect(onIdle).toHaveBeenCalledOnce();
  });

  it("resets the countdown on activity", () => {
    const onIdle = vi.fn();
    renderHook(() => useIdleLogout(true, 1000, onIdle));

    vi.advanceTimersByTime(700);
    window.dispatchEvent(new MouseEvent("mousemove"));
    vi.advanceTimersByTime(700);
    // 1400ms of elapsed time, but the reset at 700ms means only 700ms since.
    expect(onIdle).not.toHaveBeenCalled();

    vi.advanceTimersByTime(300);
    expect(onIdle).toHaveBeenCalledOnce();
  });

  it("does nothing while disabled", () => {
    const onIdle = vi.fn();
    renderHook(() => useIdleLogout(false, 1000, onIdle));

    vi.advanceTimersByTime(5000);
    expect(onIdle).not.toHaveBeenCalled();
  });

  it("stops listening once unmounted", () => {
    const onIdle = vi.fn();
    const { unmount } = renderHook(() => useIdleLogout(true, 1000, onIdle));

    unmount();
    vi.advanceTimersByTime(5000);
    expect(onIdle).not.toHaveBeenCalled();
  });
});
