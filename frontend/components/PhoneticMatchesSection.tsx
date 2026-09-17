"use client";

import { useState } from "react";
import { ImageIcon } from "lucide-react";
import { imageUrl } from "@/lib/api";
import type { PhoneticMatch, PhoneticSearchResponse } from "@/lib/contracts";

export type PhoneticPhase =
  | { name: "idle" }
  | { name: "loading" }
  | { name: "result"; data: PhoneticSearchResponse }
  | { name: "error"; message: string };

// ResultView.similarityPercentage 와 같은 규칙(소수 첫째 자리 내림). ResultView 가 이
// 컴포넌트를 import 하므로 순환 import 를 피하려고 같은 계산을 여기에 둔다.
export function phoneticPercentage(value: number): number {
  const clamped = Math.max(0, Math.min(1, value));
  return Math.floor(clamped * 1000) / 10;
}

function MatchImage({ match }: { match: PhoneticMatch }) {
  const [failed, setFailed] = useState(false);
  const src = imageUrl(match.이미지URL);

  if (!src || failed) {
    return (
      <span
        role="img"
        aria-label={`${match.상표한글명} 상표 이미지 없음`}
        className="flex h-full w-full items-center justify-center bg-low-bg text-sub"
      >
        <ImageIcon aria-hidden size={18} strokeWidth={1.8} />
      </span>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element -- same-origin BFF image path
    <img
      src={src}
      alt={`${match.상표한글명} 등록상표`}
      loading="lazy"
      onError={() => setFailed(true)}
      className="h-full w-full bg-white object-contain"
    />
  );
}

function MatchRow({ match }: { match: PhoneticMatch }) {
  const score = phoneticPercentage(match.similarity);
  const meta = [
    match.출원번호,
    match.출원인,
    match.류.length > 0 ? `제 ${match.류.join("·")}류` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <li className="border-b border-line py-3 last:border-b-0">
      <div className="flex items-center gap-3">
        <span className="h-12 w-12 shrink-0 overflow-hidden rounded-sm border border-line bg-white">
          <MatchImage match={match} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block break-words text-[14px] font-extrabold text-ink">
            {match.상표한글명}
          </span>
          <span className="mt-0.5 block break-words text-[11.5px] text-sub tnum">{meta}</span>
        </span>
        <span className="shrink-0 text-right text-blue-dark">
          <span className="block text-[17px] font-extrabold tnum">{score}%</span>
          <span className="block text-[9.5px] font-semibold">호칭 유사도</span>
        </span>
      </div>
      {/* ResultView 후보 행과 같은 막대 스타일. 시각 임계값과 무관한 점수라 단일 톤을 쓴다. */}
      <span aria-hidden className="mt-2 block h-1.5 overflow-hidden rounded-sm bg-low-bg">
        <span className="block h-full bg-blue-dark" style={{ width: `${score}%` }} />
      </span>
    </li>
  );
}

export default function PhoneticMatchesSection({
  phase,
  live = false,
}: {
  phase: PhoneticPhase;
  live?: boolean;
}) {
  if (phase.name === "idle") return null;
  const data = phase.name === "result" ? phase.data : null;
  const subtitle = data
    ? `X1 호칭 유사도 · DB ${data.searched_count}건 대상 · 참고 정보`
    : "X1 호칭 유사도 · 참고 정보";
  const minPercent = data ? Math.round(data.params.min_similarity * 100) : null;

  return (
    <div data-phonetic-matches>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-[14px] font-extrabold text-ink">발음(호칭)이 비슷한 등록상표</h3>
          <p className="mt-0.5 text-[11px] text-sub tnum">{subtitle}</p>
        </div>
        {data && data.matches.length > 0 && (
          <span className="shrink-0 text-[11px] font-bold text-blue-dark tnum">
            {data.matches.length}건
          </span>
        )}
      </div>

      {phase.name === "loading" && (
        <p role="status" aria-live="polite" className="mt-3 text-[12px] text-sub">
          발음 유사도를 계산하는 중이에요.
        </p>
      )}

      {phase.name === "error" && (
        <p role="alert" className="mt-3 text-[12px] font-semibold text-caution-deep">
          {phase.message}
        </p>
      )}

      {data && (
        <>
          {live && (
            <p role="status" aria-live="polite" className="sr-only">
              발음 유사도 계산 완료. 후보 {data.matches.length}건입니다.
            </p>
          )}
          {!data.query.has_pronunciation ? (
            <p className="mt-3 text-[12px] leading-relaxed text-sub">
              입력한 이름에서 발음(호칭)을 얻지 못해 비교하지 않았어요.
            </p>
          ) : data.matches.length === 0 ? (
            <p className="mt-3 text-[12px] leading-relaxed text-sub">
              유사도 {minPercent}% 이상인 등록상표가 없습니다.
            </p>
          ) : (
            <ul className="mt-2">
              {data.matches.map((match) => (
                <MatchRow key={`${match.rank}-${match.출원번호}`} match={match} />
              ))}
            </ul>
          )}
          <p className="mt-3 border-t border-line pt-3 text-[11px] leading-relaxed text-sub">
            {data.note ?? "호칭(발음) 유사도만 반영한 참고 정보"} · 외관·관념·지정상품은 반영되지
            않았고, 법적 판단이 아니에요.
          </p>
        </>
      )}
    </div>
  );
}
