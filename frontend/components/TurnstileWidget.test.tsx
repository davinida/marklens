import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import TurnstileWidget, {
  resetTurnstileConfigCache,
} from "@/components/TurnstileWidget";

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

// 모든 실패 응답을 소진한 뒤 성공 응답을 주는 fetch 스텁.
function stubFlakyConfigFetch(
  failures: number,
  config: { siteKey: string; devBypass: boolean },
) {
  let calls = 0;
  const fetchMock = vi.fn(async () => {
    calls += 1;
    if (calls <= failures) throw new Error("network down");
    return { ok: true, json: async () => config };
  });
  vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);
  return fetchMock;
}

// 백오프(500ms + 1500ms)를 모두 소화해 재시도 3회가 확정적으로 끝나게 한다.
async function flushConfigRetries() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2_100);
  });
}

describe("TurnstileWidget", () => {
  afterEach(() => {
    delete window.turnstile;
    resizeCallback = null;
    scriptState.onReady = null;
    // 설정 프로미스는 모듈 스코프에 캐시된다 — 비우지 않으면 앞 케이스의 응답이
    // 다음 케이스로 샌다.
    resetTurnstileConfigCache();
    vi.useRealTimers();
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

  it("recovers from a transient config failure by retrying with backoff", async () => {
    vi.useFakeTimers();
    const fetchMock = stubFlakyConfigFetch(1, { siteKey: "", devBypass: true });
    const onTokenChange = vi.fn();

    render(<TurnstileWidget onTokenChange={onTokenChange} />);
    await flushConfigRetries();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(onTokenChange).toHaveBeenCalledWith("dev-bypass");
    expect(
      screen.getByText("개발용 자동 요청 확인이 적용됐어요."),
    ).toBeInTheDocument();
  });

  it("offers a retry action instead of a reload when every attempt fails", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 500,
      json: async () => ({}),
    }));
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    render(<TurnstileWidget onTokenChange={vi.fn()} />);
    await flushConfigRetries();

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(
      screen.getByText("자동 요청 확인 설정을 불러오지 못했어요."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "다시 시도" }),
    ).toBeInTheDocument();
  });

  it("reloads the runtime config when the retry button is pressed", async () => {
    vi.useFakeTimers();
    // 최초 3회(1회 + 재시도 2회)는 모두 실패하고, 버튼이 낸 4번째 요청이 성공한다.
    const fetchMock = stubFlakyConfigFetch(3, { siteKey: "", devBypass: true });
    const onTokenChange = vi.fn();

    render(<TurnstileWidget onTokenChange={onTokenChange} />);
    await flushConfigRetries();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(onTokenChange).not.toHaveBeenCalledWith("dev-bypass");

    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    await flushConfigRetries();

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(onTokenChange).toHaveBeenCalledWith("dev-bypass");
    expect(
      screen.getByText("개발용 자동 요청 확인이 적용됐어요."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "다시 시도" })).toBeNull();
  });
});
