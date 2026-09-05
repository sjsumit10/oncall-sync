import { useEffect, useRef } from "react";

const ACTIVITY_EVENTS = ["mousedown", "mousemove", "keydown", "wheel", "touchstart", "scroll"] as const;

/** Calls onIdle after timeoutMs with no user activity. No-ops while disabled. */
export function useIdleLogout(enabled: boolean, timeoutMs: number, onIdle: () => void) {
  const onIdleRef = useRef(onIdle);
  onIdleRef.current = onIdle;

  useEffect(() => {
    if (!enabled) return;

    let timer: ReturnType<typeof setTimeout>;
    const reset = () => {
      clearTimeout(timer);
      timer = setTimeout(() => onIdleRef.current(), timeoutMs);
    };

    reset();
    for (const event of ACTIVITY_EVENTS) {
      window.addEventListener(event, reset, { passive: true });
    }
    return () => {
      clearTimeout(timer);
      for (const event of ACTIVITY_EVENTS) {
        window.removeEventListener(event, reset);
      }
    };
  }, [enabled, timeoutMs]);
}
