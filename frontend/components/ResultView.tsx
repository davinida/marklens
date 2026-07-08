"use client";

import { useState } from "react";
import type { GradeCode, SearchMatch, SearchResponse } from "@/lib/api";
import { imageUrl } from "@/lib/api";

/** 등급별 화면 표현 — 문구·색은 scoring.py 4단계와 1:1 대응 */
const GRADE_VIEW: Record<
  GradeCode,
  { emoji: string; headline: string; text: string; bg: string; pill: string }
> = {
  CAUTION: {
    emoji: "🚨",
    headline: "매우 닮은 상표가 있어요",
    text: "text-caution-deep",
    bg: "bg-caution-bg",
    pill: "bg-caution text-white",
  },
  REVIEW: {
    emoji: "🧐",
    headline: "닮았을 수 있는 상표가 있어요",
    text: "text-review-deep",
    bg: "bg-review-bg",
    pill: "bg-review text-white",
  },
  LOW: {
    emoji: "🙂",
    headline: "특별히 가까운 상표는 없었어요",
    text: "text-sub",
    bg: "bg-low-bg",
    pill: "bg-low text-white",
  },
  SAFE: {
    emoji: "😌",
    headline: "시각적으로 충돌하는 상표는 안 보여요",
    text: "text-safe-deep",
    bg: "bg-safe-bg",
    pill: "bg-safe text-white",
  },
};

function simTone(sim: number): string {
  if (sim >= 0.75) return "text-caution";
  if (sim >= 0.55) return "text-review";
  return "text-blue";
}

function MatchRow({ match }: { match: SearchMatch }) {
  const [open, setOpen] = useState(false);
  const t = match.trademark;
  const src = imageUrl(match.이미지URL);
  const pct = Math.round(match.similarity * 100);

  return (
    <li className="border-b border-line last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3.5 py-3.5 text-left transition-colors hover:bg-bg/60"
        aria-expanded={open}
      >
        {src ? (
          /* eslint-disable-next-line @next/next/no-img-element -- 백엔드 정적 서빙 이미지 */
          <img
            src={src}
            alt={t?.상표한글명 ?? match.이미지파일 ?? "상표 이미지"}
            className="h-12 w-12 shrink-0 rounded-xl border border-line bg-white object-contain"
          />
        ) : (
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-low-bg text-[11px] font-bold text-muted">
            ?
          </span>
        )}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[15px] font-bold">
            {t?.상표한글명 || t?.상표영문명 || t?.출원번호 || "메타 미연결"}
          </span>
          <span className="mt-0.5 block truncate text-[12px] text-muted">
            {t
              ? [t.출원인, t.류.length ? `${t.류.join("·")}류` : null]
                  .filter(Boolean)
                  .join(" · ") || "정보 없음"
              : "상표 정보가 연결되지 않았어요"}
          </span>
        </span>
        <span className={`shrink-0 text-[17px] font-extrabold tnum ${simTone(match.similarity)}`}>
          {pct}%
        </span>
        <span
          className={`shrink-0 text-faint transition-transform ${open ? "rotate-90" : ""}`}
        >
          ›
        </span>
      </button>
      {open && (
        <dl className="mb-3.5 grid grid-cols-2 gap-x-4 gap-y-2 rounded-2xl bg-bg p-4 text-[12.5px]">
          <Info k="유사도" v={`${match.similarity.toFixed(4)} (${pct}%)`} />
          <Info k="순위" v={`${match.rank}위`} />
          <Info k="출원번호" v={t?.출원번호 ?? "—"} />
          <Info k="등록번호" v={t?.등록번호 ?? "—"} />
          <Info k="비엔나코드" v={t?.비엔나코드.join(", ") || "—"} />
          <Info k="유사군" v={t?.유사군.join(", ") || "—"} />
          <Info k="출원일자" v={t?.출원일자 ?? "—"} />
          <Info k="이미지 파일" v={match.이미지파일 ?? "—"} />
        </dl>
      )}
    </li>
  );
}

function Info({ k, v }: { k: string; v: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-semibold text-muted">{k}</dt>
      <dd className="mt-0.5 truncate font-semibold text-sub tnum">{v}</dd>
    </div>
  );
}

export default function ResultView({
  result,
  queryPreview,
  onReset,
}: {
  result: SearchResponse;
  queryPreview: string | null;
  onReset: () => void;
}) {
  const g = result.grade;
  const view = GRADE_VIEW[g.grade_code] ?? GRADE_VIEW.LOW;
  const d = result.dataset_info;

  return (
    <div className="flex flex-col gap-3">
      {/* ── 1층: 등급 · 권장 행동 · 경고 ── */}
      <section className={`rise rounded-[24px] p-6 ${view.bg}`}>
        <div className="text-[36px] leading-none">{view.emoji}</div>
        <h1
          className={`mt-3 text-[23px] font-extrabold leading-snug tracking-tight ${view.text}`}
        >
          {view.headline}
        </h1>
        <p className="mt-2 text-[13.5px] leading-relaxed text-sub">
          {g.message}
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span
            className={`rounded-full px-3 py-1 text-[12px] font-bold ${view.pill}`}
          >
            {g.grade_name} · {g.grade_code}
          </span>
          <span className="rounded-full bg-white/70 px-3 py-1 text-[12px] font-semibold text-sub tnum">
            최고 유사도 {Math.round(g.top1_similarity * 100)}%
          </span>
        </div>
        {g.warnings.length > 0 && (
          <ul className="mt-4 flex flex-col gap-2">
            {g.warnings.map((w) => (
              <li
                key={w}
                className="flex items-start gap-2.5 rounded-2xl bg-white/80 px-4 py-3 text-[12.5px] font-semibold leading-relaxed text-review-deep"
              >
                <span aria-hidden className="mt-px shrink-0">
                  ⚠️
                </span>
                {w}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ── 2층: 유사 상표 비교 ── */}
      <section className="rise rise-1 rounded-[24px] bg-card p-5">
        <div className="flex items-baseline justify-between px-1">
          <h2 className="text-[16px] font-extrabold">
            비슷한 상표 {result.top_k_returned}건
          </h2>
          {queryPreview && (
            <span className="flex items-center gap-1.5 text-[11px] font-semibold text-muted">
              내 로고
              {/* eslint-disable-next-line @next/next/no-img-element -- 로컬 blob 미리보기 */}
              <img
                src={queryPreview}
                alt="내 로고"
                className="h-6 w-6 rounded-md border border-line bg-white object-contain"
              />
            </span>
          )}
        </div>
        <ul className="mt-1">
          {result.matches.map((m) => (
            <MatchRow key={`${m.rank}-${m.이미지파일}`} match={m} />
          ))}
        </ul>
        <p className="mt-3 rounded-2xl bg-bg px-4 py-3 text-[11.5px] leading-relaxed text-muted">
          식별력 경고와 &lsquo;표장 유사·상품 상이&rsquo; 경고는 다축
          모델(호칭·관념·상품 견련성) 확장 후 이 화면에 함께 표시될 예정이에요.
        </p>
      </section>

      {/* ── 3층: 상세 근거 ── */}
      <details className="rise rise-2 group rounded-[24px] bg-card p-5">
        <summary className="flex cursor-pointer list-none items-center justify-between px-1 text-[15px] font-extrabold [&::-webkit-details-marker]:hidden">
          분석 근거 자세히 보기
          <span className="text-faint transition-transform group-open:rotate-90">
            ›
          </span>
        </summary>
        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-[13px] sm:grid-cols-3">
          <Info k="top-1 유사도" v={g.top1_similarity.toFixed(4)} />
          <Info k="격차 A (top1−top2)" v={g.separability_a.toFixed(4)} />
          <Info k="격차 B (top1−평균)" v={g.separability_b.toFixed(4)} />
          <Info k="인덱스 크기" v={`${result.index_size}건`} />
          <Info
            k="요청/반환"
            v={`${result.top_k_requested} / ${result.top_k_returned}`}
          />
          <Info k="판단 축" v="외관(CLIP) 단일 축" />
        </dl>
        <p className="mt-4 rounded-2xl bg-bg px-4 py-3 text-[11.5px] leading-relaxed text-muted">
          등급 기준(임시): 유사도 0.75 이상+격차 조건 → 주의 필요 · 0.55 이상 →
          검토 권장 · 0.45 이상 → 특정 위협 없음 · 그 미만 → 비교적 안전.
          실제 심결 데이터 확보 후 재보정될 예정이에요.
        </p>
      </details>

      <div className="rise rise-3">
        <button
          type="button"
          onClick={onReset}
          className="press w-full rounded-2xl bg-blue py-4 text-[16px] font-bold text-white hover:bg-blue-dark"
        >
          다른 로고 진단하기
        </button>
        <p className="mt-3 text-center text-[11px] leading-relaxed text-muted tnum">
          {d.데이터_기준} · {d.출원일자_범위} · {d.총_상표수}건 기준
          <br />
          법적 판단이 아닌 참고 정보예요
        </p>
      </div>
    </div>
  );
}
