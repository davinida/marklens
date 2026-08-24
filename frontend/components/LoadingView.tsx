"use client";

import { useEffect, useState } from "react";

const MESSAGES = [
  "로고의 형태를 읽고 있어요",
  "등록상표와 비교하고 있어요",
  "유사도와 시각 후보 상태를 계산하고 있어요",
];

export default function LoadingView({
  queryPreview,
  onCancel,
}: {
  queryPreview: string | null;
  onCancel: () => void;
}) {
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    const timer = setInterval(
      () => setIdx((current) => (current + 1) % MESSAGES.length),
      1800,
    );
    return () => clearInterval(timer);
  }, []);

  return (
    <section
      aria-labelledby="loading-title"
      aria-busy="true"
      className="rise flex flex-col items-center gap-6 rounded-lg bg-card px-6 py-16"
    >
      <div className="scan-pulse flex h-24 w-24 items-center justify-center rounded-full border-2 border-blue-dark bg-blue-bg">
        {queryPreview ? (
          // eslint-disable-next-line @next/next/no-img-element -- local blob preview
          <img
            src={queryPreview}
            alt="분석 중인 로고"
            className="h-16 w-16 rounded-full bg-white object-contain"
          />
        ) : (
          <span aria-hidden className="text-[30px] font-extrabold text-blue-dark">
            ML
          </span>
        )}
      </div>
      <div className="text-center">
        <h1
          id="loading-title"
          data-phase-heading
          tabIndex={-1}
          className="text-[18px] font-extrabold outline-none"
        >
          로고를 분석하고 있어요
        </h1>
        <p aria-hidden className="mt-2 text-[14px] font-semibold text-sub">
          {MESSAGES[idx]}
        </p>
        <p className="mt-1.5 text-[13px] text-sub">보통 몇 초면 끝나요.</p>
      </div>
      <div className="flex gap-1.5" aria-hidden>
        <span className="loading-dot h-2 w-2 rounded-full bg-blue-dark" />
        <span className="loading-dot h-2 w-2 rounded-full bg-blue-dark" />
        <span className="loading-dot h-2 w-2 rounded-full bg-blue-dark" />
      </div>
      <button
        type="button"
        onClick={onCancel}
        className="press rounded-md bg-low-bg px-5 py-2.5 text-[13px] font-bold text-sub"
      >
        취소하고 입력으로 돌아가기
      </button>
      <span className="sr-only" role="status" aria-live="polite">
        로고 분석이 진행 중입니다.
      </span>
    </section>
  );
}
