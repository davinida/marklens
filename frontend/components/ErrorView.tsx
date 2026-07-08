"use client";

import { ApiError } from "@/lib/api";

export default function ErrorView({
  error,
  onRetry,
  onReset,
}: {
  error: unknown;
  onRetry: () => void;
  onReset: () => void;
}) {
  const isApi = error instanceof ApiError;
  const status = isApi ? (error as ApiError).status : 0;
  const message = isApi
    ? (error as ApiError).message
    : "알 수 없는 오류가 발생했어요.";

  return (
    <div className="rise flex flex-col items-center gap-5 rounded-[24px] bg-card px-6 py-14 text-center">
      <span className="flex h-16 w-16 items-center justify-center rounded-full bg-caution-bg text-[28px]">
        😵
      </span>
      <div>
        <h1 className="text-[20px] font-extrabold">검색하지 못했어요</h1>
        <p className="mt-2 text-[14px] leading-relaxed text-sub">{message}</p>
        <span className="mt-3 inline-block rounded-full bg-low-bg px-3 py-1 text-[11px] font-bold text-muted tnum">
          {status > 0 ? `HTTP ${status}` : "연결 실패"}
        </span>
      </div>
      <div className="flex w-full max-w-xs flex-col gap-2">
        <button
          type="button"
          onClick={onRetry}
          className="press w-full rounded-2xl bg-blue py-3.5 text-[15px] font-bold text-white hover:bg-blue-dark"
        >
          다시 시도하기
        </button>
        <button
          type="button"
          onClick={onReset}
          className="press w-full rounded-2xl bg-low-bg py-3.5 text-[15px] font-bold text-sub"
        >
          처음으로
        </button>
      </div>
    </div>
  );
}
