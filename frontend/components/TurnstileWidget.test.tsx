import { act, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import TurnstileWidget from "@/components/TurnstileWidget";

const scriptState = vi.hoisted(() => ({
  onReady: null as (() => void) | null,
}));

vi.hoisted(() => {
  vi.stubEnv("NEXT_PUBLIC_TURNSTILE_SITE_KEY", "test-site-key");
  vi.stubEnv("NEXT_PUBLIC_TURNSTILE_DEV_BYPASS", "0");
});

vi.mock("next/script", () => ({
  default: function MockScript({ onReady }: { onReady?: () => void }) {
    scriptState.onReady = onReady ?? null;
    return null;
  },
}));

let resizeCallback: ResizeObserverCallback | null = null;

function emitResize(width: number) {
  resizeCallback?.(
    [{ contentRect: { width } } as ResizeObserverEntry],
    {} as ResizeObserver,
  );
}

describe("TurnstileWidget sizing", () => {
  afterEach(() => {
    delete window.turnstile;
    resizeCallback = null;
    scriptState.onReady = null;
    vi.unstubAllGlobals();
  });

  it("waits for layout, uses compact below 300px, and rerenders at 300px", async () => {
    class ResizeObserverMock {
      constructor(callback: ResizeObserverCallback) {
        resizeCallback = callback;
      }

      observe() {}
      disconnect() {}
    }

    vi.stubGlobal("ResizeObserver", ResizeObserverMock);
    const renderWidget = vi
      .fn()
      .mockReturnValueOnce("compact-widget")
      .mockReturnValueOnce("flexible-widget");
    const removeWidget = vi.fn();
    window.turnstile = {
      render: renderWidget,
      reset: vi.fn(),
      remove: removeWidget,
    };
    const onTokenChange = vi.fn();

    const view = render(<TurnstileWidget onTokenChange={onTokenChange} />);
    act(() => scriptState.onReady?.());

    expect(renderWidget).not.toHaveBeenCalled();

    act(() => emitResize(299));
    await waitFor(() => expect(renderWidget).toHaveBeenCalledTimes(1));
    expect(renderWidget.mock.calls[0][1]).toEqual(
      expect.objectContaining({
        action: "marklens",
        sitekey: "test-site-key",
        size: "compact",
      }),
    );

    act(() => emitResize(300));
    await waitFor(() => expect(renderWidget).toHaveBeenCalledTimes(2));
    expect(removeWidget).toHaveBeenCalledWith("compact-widget");
    expect(renderWidget.mock.calls[1][1]).toEqual(
      expect.objectContaining({ size: "flexible" }),
    );
    expect(onTokenChange).toHaveBeenCalledWith(null);

    view.unmount();
    expect(removeWidget).toHaveBeenCalledWith("flexible-widget");
  });
});
