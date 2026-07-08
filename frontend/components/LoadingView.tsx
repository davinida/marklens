"use client";

import { useEffect, useState } from "react";

const MESSAGES = [
  "로고의 형태를 읽고 있어요",
  "등록상표들과 대조하고 있어요",
  "닮은 정도를 계산하고 있어요",
];

export default function LoadingView({
  queryPreview,
}: {
  queryPreview: string | null;
}) {
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setIdx((i) => (i + 1) % MESSAGES.length), 1800);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="rise flex flex-col items-center gap-6 rounded-[24px] bg-card px-6 py-16">
      <div className="scan-pulse flex h-24 w-24 items-center justify-center rounded-full border-2 border-blue bg-blue-bg">
        {queryPreview ? (
          /* eslint-disable-next-line @next/next/no-img-element -- 로컬 blob 미리보기 */
          <img
            src={queryPreview}
            alt="분석 중인 로고"
            className="h-16 w-16 rounded-full bg-white object-contain"
          />
        ) : (
          <span className="text-[30px]">🔍</span>
        )}
      </div>
      <div className="text-center">
        <p aria-live="polite" className="text-[17px] font-extrabold">
          {MESSAGES[idx]}
        </p>
        <p className="mt-1.5 text-[13px] text-muted">
          보통 몇 초면 끝나요
        </p>
      </div>
      <div className="flex gap-1.5" aria-hidden>
        <span className="loading-dot h-2 w-2 rounded-full bg-blue" />
        <span className="loading-dot h-2 w-2 rounded-full bg-blue" />
        <span className="loading-dot h-2 w-2 rounded-full bg-blue" />
      </div>
    </div>
  );
}
