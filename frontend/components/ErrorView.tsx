"use client";

import { ApiError } from "@/lib/api";

export default function ErrorView({
  error,
  onEdit,
  onReset,
}: {
  error: unknown;
  onEdit: () => void;
  onReset: () => void;
}) {
  const apiError = error instanceof ApiError ? error : null;
  const message =
    apiError?.message ?? "예상하지 못한 오류가 발생했어요. 다시 시도해 주세요.";

  return (
    <section
      aria-labelledby="error-title"
      className="rise flex flex-col items-center gap-5 rounded-lg bg-card px-6 py-14 text-center"
    >
      <span
        aria-hidden
        className="flex h-16 w-16 items-center justify-center rounded-full bg-caution-bg text-[28px] font-extrabold text-caution-deep"
      >
        !
      </span>
      <div>
        <h1
          id="error-title"
          data-phase-heading
          tabIndex={-1}
          className="text-[20px] font-extrabold outline-none"
        >
          검색을 완료하지 못했어요
        </h1>
        <p role="alert" className="mt-2 text-[14px] leading-relaxed text-sub">
          {message}
        </p>
        <span className="mt-3 inline-block rounded-full bg-low-bg px-3 py-1 text-[11px] font-bold text-sub tnum">
          {apiError?.status ? `HTTP ${apiError.status}` : "연결 실패"}
        </span>
        {apiError?.requestId && (
          <p className="mt-2 break-all text-[11px] text-sub tnum">
            요청 ID: {apiError.requestId}
          </p>
        )}
        {apiError?.retryAfter && (
          <p className="mt-1 text-[11px] text-sub">
            다시 시도 가능: {apiError.retryAfter}초 후
          </p>
        )}
      </div>
      <div className="flex w-full max-w-xs flex-col gap-2">
        <button
          type="button"
          onClick={onEdit}
          className="press w-full rounded-md bg-blue-dark py-3.5 text-[15px] font-bold text-white hover:bg-[#174ea6]"
        >
          입력 확인 후 다시 시도
        </button>
        <button
          type="button"
          onClick={onReset}
          className="press w-full rounded-md bg-low-bg py-3.5 text-[15px] font-bold text-sub"
        >
          처음으로
        </button>
      </div>
    </section>
  );
}
