"use client";

import Script from "next/script";
import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { TURNSTILE_ACTION } from "@/lib/turnstile";

type WidgetId = string | number;
type WidgetSize = "compact" | "flexible";

interface TurnstileApi {
  render: (
    container: HTMLElement,
    options: Record<string, unknown>,
  ) => WidgetId;
  reset: (widgetId: WidgetId) => void;
  remove: (widgetId: WidgetId) => void;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

export interface TurnstileHandle {
  reset: () => void;
}

// 사이트 키와 bypass 여부는 빌드 시점 인라인(NEXT_PUBLIC_) 대신 요청 시점의
// 서버 설정(/api/turnstile-config)에서 받는다. 빌드 후 키를 교체하거나 bypass 를
// 전환해도 재빌드 없이 반영된다 — 과거에는 이 경우 위젯이 "설정 없음"으로 죽었다.
interface TurnstileConfig {
  siteKey: string;
  devBypass: boolean;
}

const FLEXIBLE_MIN_WIDTH = 300;

const TurnstileWidget = forwardRef<
  TurnstileHandle,
  { onTokenChange: (token: string | null) => void }
>(function TurnstileWidget({ onTokenChange }, ref) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const widgetRef = useRef<WidgetId | null>(null);
  const previousSizeRef = useRef<WidgetSize | null>(null);
  const [config, setConfig] = useState<TurnstileConfig | null>(null);
  const [configError, setConfigError] = useState(false);
  const [scriptReady, setScriptReady] = useState(false);
  const [scriptError, setScriptError] = useState(false);
  const [widgetSize, setWidgetSize] = useState<WidgetSize | null>(null);

  const devBypass = config?.devBypass === true;
  const siteKey = config?.siteKey ?? "";

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/turnstile-config", {
      signal: controller.signal,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`turnstile-config ${response.status}`);
        const data = (await response.json()) as Partial<TurnstileConfig>;
        setConfig({
          siteKey: typeof data.siteKey === "string" ? data.siteKey.trim() : "",
          devBypass: data.devBypass === true,
        });
      })
      .catch(() => {
        if (!controller.signal.aborted) setConfigError(true);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (devBypass) onTokenChange("dev-bypass");
  }, [devBypass, onTokenChange]);

  useEffect(() => {
    if (devBypass || !siteKey) return;
    const wrapper = wrapperRef.current;
    if (!wrapper) return;

    const updateSize = (width: number) => {
      if (width <= 0) return;
      setWidgetSize(width < FLEXIBLE_MIN_WIDTH ? "compact" : "flexible");
    };
    const measure = () => updateSize(wrapper.getBoundingClientRect().width);

    measure();
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(([entry]) => {
        if (entry) updateSize(entry.contentRect.width);
      });
      observer.observe(wrapper);
      return () => observer.disconnect();
    }

    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [devBypass, siteKey]);

  useEffect(() => {
    if (
      previousSizeRef.current !== null &&
      widgetSize !== previousSizeRef.current
    ) {
      onTokenChange(null);
    }
    previousSizeRef.current = widgetSize;
  }, [onTokenChange, widgetSize]);

  useEffect(() => {
    if (
      devBypass ||
      !siteKey ||
      !scriptReady ||
      scriptError ||
      !widgetSize ||
      !window.turnstile
    ) {
      return;
    }
    const container = containerRef.current;
    if (!container || widgetRef.current !== null) return;

    widgetRef.current = window.turnstile.render(container, {
      sitekey: siteKey,
      action: TURNSTILE_ACTION,
      theme: "light",
      language: "ko",
      size: widgetSize,
      callback: (token: string) => onTokenChange(token),
      "expired-callback": () => onTokenChange(null),
      "timeout-callback": () => onTokenChange(null),
      "error-callback": () => {
        onTokenChange(null);
        return true;
      },
    });

    return () => {
      if (widgetRef.current !== null && window.turnstile) {
        window.turnstile.remove(widgetRef.current);
      }
      widgetRef.current = null;
    };
  }, [devBypass, onTokenChange, scriptError, scriptReady, siteKey, widgetSize]);

  useImperativeHandle(ref, () => ({
    reset() {
      if (devBypass) {
        onTokenChange("dev-bypass");
        return;
      }
      onTokenChange(null);
      if (widgetRef.current !== null && window.turnstile) {
        window.turnstile.reset(widgetRef.current);
      }
    },
  }));

  if (configError) {
    return (
      <p role="alert" className="text-[12px] font-semibold text-caution-deep">
        자동 요청 확인 설정을 불러오지 못했어요. 페이지를 새로고침해 주세요.
      </p>
    );
  }

  if (config === null) {
    return (
      <p role="status" className="text-[12px] text-sub">
        자동 요청 확인을 불러오는 중이에요.
      </p>
    );
  }

  if (devBypass) {
    return <p className="text-[12px] text-sub">개발용 자동 요청 확인이 적용됐어요.</p>;
  }

  if (!siteKey) {
    return (
      <p role="alert" className="text-[12px] font-semibold text-caution-deep">
        자동 요청 확인 설정이 없어 검색을 시작할 수 없어요.
      </p>
    );
  }

  return (
    <div
      ref={wrapperRef}
      className="flex min-h-[65px] max-w-full justify-center"
      aria-label="자동 요청 확인"
    >
      <Script
        src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"
        strategy="afterInteractive"
        onReady={() => setScriptReady(true)}
        onError={() => {
          setScriptError(true);
          onTokenChange(null);
        }}
      />
      {!scriptReady && !scriptError && (
        <p role="status" className="text-[12px] text-sub">
          자동 요청 확인을 불러오는 중이에요.
        </p>
      )}
      {scriptError && (
        <p role="alert" className="text-[12px] font-semibold text-caution-deep">
          자동 요청 확인을 불러오지 못했어요. 페이지를 새로고침해 주세요.
        </p>
      )}
      <div ref={containerRef} className="max-w-full" hidden={scriptError} />
    </div>
  );
});

export default TurnstileWidget;
