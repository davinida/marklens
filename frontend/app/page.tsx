"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ErrorView from "@/components/ErrorView";
import LoadingView from "@/components/LoadingView";
import ResultView from "@/components/ResultView";
import SearchForm, {
  type SearchDraft,
  type SearchFormValue,
} from "@/components/SearchForm";
import { searchTrademark, type SearchResponse } from "@/lib/api";
import { useObjectUrl } from "@/lib/useObjectUrl";

type Phase =
  | { name: "idle" }
  | { name: "loading" }
  | { name: "result"; data: SearchResponse }
  | { name: "error"; error: unknown };

export default function Home() {
  const [phase, setPhase] = useState<Phase>({ name: "idle" });
  const [draft, setDraft] = useState<SearchDraft | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const generationRef = useRef(0);
  const previousPhaseRef = useRef(phase.name);
  const queryPreview = useObjectUrl(phase.name === "idle" ? null : draft?.file ?? null);

  const cancelCurrentRequest = useCallback(() => {
    generationRef.current += 1;
    requestRef.current?.abort();
    requestRef.current = null;
  }, []);

  useEffect(() => cancelCurrentRequest, [cancelCurrentRequest]);

  useEffect(() => {
    if (previousPhaseRef.current === phase.name) return;
    previousPhaseRef.current = phase.name;
    const frame = requestAnimationFrame(() => {
      document.querySelector<HTMLElement>("[data-phase-heading]")?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [phase.name]);

  const runSearch = useCallback(async (value: SearchFormValue) => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const generation = ++generationRef.current;
    setDraft({
      file: value.file,
      markName: value.markName,
      topK: value.topK,
      nameCheck: value.nameCheck ?? null,
    });
    setPhase({ name: "loading" });

    try {
      const data = await searchTrademark(
        value.file,
        value.topK,
        value.turnstileToken,
        controller.signal,
      );
      if (generation === generationRef.current) {
        setPhase({ name: "result", data });
      }
    } catch (error) {
      if (!controller.signal.aborted && generation === generationRef.current) {
        setPhase({ name: "error", error });
      }
    } finally {
      if (generation === generationRef.current) requestRef.current = null;
    }
  }, []);

  const edit = useCallback(() => {
    cancelCurrentRequest();
    setPhase({ name: "idle" });
  }, [cancelCurrentRequest]);

  const reset = useCallback(() => {
    cancelCurrentRequest();
    setDraft(null);
    setPhase({ name: "idle" });
  }, [cancelCurrentRequest]);

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-10 border-b border-line/80 bg-bg/90 backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-[1080px] items-center justify-between px-5">
          <button
            type="button"
            onClick={reset}
            className="press rounded-sm px-1 py-2 text-[17px] font-extrabold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-dark"
            aria-label="MarkLens 처음 화면으로"
          >
            Mark<span className="text-blue-dark">Lens</span>
          </button>
          <span className="rounded-full bg-low-bg px-2.5 py-1 text-[11px] font-bold text-sub">
            연구 베타 · 시각 비교
          </span>
        </div>
      </header>

      <main
        className={`mx-auto w-full flex-1 px-4 pb-16 pt-4 transition-[max-width] ${
          phase.name === "result" ? "max-w-[1080px]" : "max-w-[560px]"
        }`}
      >
        {phase.name === "idle" && (
          <SearchForm onSubmit={runSearch} initialValue={draft} />
        )}
        {phase.name === "loading" && (
          <LoadingView queryPreview={queryPreview} onCancel={edit} />
        )}
        {phase.name === "result" && (
          <ResultView
            result={phase.data}
            queryPreview={queryPreview}
            nameCheck={draft?.nameCheck ?? null}
            onReset={reset}
          />
        )}
        {phase.name === "error" && (
          <ErrorView error={phase.error} onEdit={edit} onReset={reset} />
        )}
      </main>

      <footer className="pb-8 text-center text-[11px] text-sub">
        MarkLens · 선행 시각 후보 비교를 위한 연구 도구
      </footer>
    </div>
  );
}
