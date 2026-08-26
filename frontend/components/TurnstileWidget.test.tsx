import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import TurnstileWidget from "@/components/TurnstileWidget";

const scriptState = vi.hoisted(() => ({
  onReady: null as (() => void) | null,
}));

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

// 사이트 키·bypass 는 빌드 인라인이 아니라 /api/turnstile-config 런타임 응답에서 온다.
function stubConfigFetch(config: { siteKey: string; devBypass: boolean }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => config,
    })) as unknown as typeof fetch,
  );
}

describe("TurnstileWidget", () => {
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
    stubConfigFetch({ siteKey: "test-site-key", devBypass: false });
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
    // 런타임 설정 로딩이 끝나야 Script 가 마운트된다
    await waitFor(() => expect(scriptState.onReady).not.toBeNull());
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

  it("applies dev bypass from runtime config and emits the bypass token", async () => {
    stubConfigFetch({ siteKey: "", devBypass: true });
    const onTokenChange = vi.fn();

    render(<TurnstileWidget onTokenChange={onTokenChange} />);

    await waitFor(() =>
      expect(onTokenChange).toHaveBeenCalledWith("dev-bypass"),
    );
    expect(
      screen.getByText("개발용 자동 요청 확인이 적용됐어요."),
    ).toBeInTheDocument();
  });

  it("shows the missing-config alert when runtime config has no site key", async () => {
    stubConfigFetch({ siteKey: "", devBypass: false });

    render(<TurnstileWidget onTokenChange={vi.fn()} />);

    expect(
      await screen.findByText("자동 요청 확인 설정이 없어 검색을 시작할 수 없어요."),
    ).toBeInTheDocument();
  });

  it("shows a reload alert when the runtime config request fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 500,
        json: async () => ({}),
      })) as unknown as typeof fetch,
    );

    render(<TurnstileWidget onTokenChange={vi.fn()} />);

    expect(
      await screen.findByText(
        "자동 요청 확인 설정을 불러오지 못했어요. 페이지를 새로고침해 주세요.",
      ),
    ).toBeInTheDocument();
  });
});
