"use client";

import { useCallback, useState } from "react";
import ErrorView from "@/components/ErrorView";
import LoadingView from "@/components/LoadingView";
import ResultView from "@/components/ResultView";
import SearchForm, { type SearchFormValue } from "@/components/SearchForm";
import { searchTrademark, type SearchResponse } from "@/lib/api";

type Phase =
  | { name: "idle" }
  | { name: "loading" }
  | { name: "result"; data: SearchResponse }
  | { name: "error"; error: unknown };

export default function Home() {
  const [phase, setPhase] = useState<Phase>({ name: "idle" });
  const [lastQuery, setLastQuery] = useState<SearchFormValue | null>(null);
  const [queryPreview, setQueryPreview] = useState<string | null>(null);

  const runSearch = useCallback(async (value: SearchFormValue) => {
    setLastQuery(value);
    setQueryPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return URL.createObjectURL(value.file);
    });
    setPhase({ name: "loading" });
    try {
      const data = await searchTrademark(value.file, value.topK);
      setPhase({ name: "result", data });
    } catch (error) {
      setPhase({ name: "error", error });
    }
  }, []);

  const reset = useCallback(() => setPhase({ name: "idle" }), []);

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-10 border-b border-line/70 bg-bg/85 backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-[560px] items-center justify-between px-5">
          <button
            type="button"
            onClick={reset}
            className="text-[17px] font-extrabold tracking-tight"
          >
            Mark<span className="text-blue">Lens</span>
          </button>
          <span className="rounded-full bg-low-bg px-2.5 py-1 text-[11px] font-bold text-muted">
            베타 · 외관 진단
          </span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[560px] flex-1 px-4 pb-16 pt-4">
        {phase.name === "idle" && <SearchForm onSubmit={runSearch} />}
        {phase.name === "loading" && (
          <LoadingView queryPreview={queryPreview} />
        )}
        {phase.name === "result" && (
          <ResultView
            result={phase.data}
            queryPreview={queryPreview}
            onReset={reset}
          />
        )}
        {phase.name === "error" && (
          <ErrorView
            error={phase.error}
            onRetry={() => lastQuery && runSearch(lastQuery)}
            onReset={reset}
          />
        )}
      </main>

      <footer className="pb-8 text-center text-[11px] text-faint">
        MarkLens · 건국대학교 컴퓨터공학부 졸업프로젝트
      </footer>
    </div>
  );
}
