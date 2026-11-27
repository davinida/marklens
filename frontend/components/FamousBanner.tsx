"use client";

import { useId, useState } from "react";
import { AlertCircle, AlertTriangle, Info, type LucideIcon } from "lucide-react";
import { imageUrl } from "@/lib/api";
import type { SearchV2Famous, SearchV2FamousMatch, SearchV2Grade } from "@/lib/contracts";
import type { FamousBannerState } from "@/lib/descriptiveNotice";
import { josaEunNeun, josaIGa, josaWaGwa } from "@/lib/josa";

// 유명 상표 확인(v1.4.7) — 결과 맨 위 안내 배너. 문구는 정해진 글자 그대로(다듬지 말 것) — 브랜드·표기·
// 글자 뒤의 조사만 받침에 맞춘다('스타벅스'와 / '삼성'과). 응답의 famous 가 없으면(확인이 꺼진 서버)
// 아무것도 그리지 않는다.

const LEVEL_STRONG = "강함";
const LEVEL_WEAK = "약함";
const LEVEL_DESCRIPTIVE = "설명적 사용";
const BASIS_LOGO = "로고";
const BASIS_OCR = "이미지 속 글자";

const DANGER_LEAD =
  "널리 알려진 상표는 업종이 달라도 보호될 수 있어요. 소비자가 관련 있는 곳으로 오해하거나 그 상표의 명성을 해친다고 보면, 등록이 거절되거나 쓰는 것 자체가 분쟁이 될 수 있어요.";
const BODY_DANGER = `${DANGER_LEAD} 다른 이름을 권해요.`;
const BODY_LOGO = `${DANGER_LEAD} 다른 로고를 권해요.`;
const BODY_REVIEW =
  "업종이 달라서 함께 등록될 수도 있지만, 유명한 상표라 문제가 될 수 있어요. 출원 전에 꼭 확인해 보세요.";
const BODY_WEAK =
  "유명한 상표를 떠올리게 하는 이름은 업종이 달라도 문제가 될 수 있어요. 출원 전에 꼭 확인해 보세요.";
const BODY_DESCRIPTIVE =
  "상품을 설명하는 말로 쓰는 건 괜찮을 수 있어요. 다만 가게 이름처럼 눈에 띄게 쓰거나 그 상표의 글자 모양·로고와 비슷하게 쓰면 문제가 될 수 있어요.";

const UNAVAILABLE_TEXT = "유명 상표 확인을 하지 못했어요.";

function famousFootnote(brandCount: number): string {
  return `MarkLens가 정리한 유명 상표 ${brandCount}개 브랜드 기준이에요. 목록에 없는 유명 상표도 있어요.`;
}

const FLOOR_REASON_WEAK = "널리 알려진 상표와 이름이 닮아서 이 등급으로 봤어요.";
const FLOOR_REASON_STRONG = "널리 알려진 상표와 같거나 거의 같아서 이 등급으로 봤어요.";

// 종류를 색만으로 구분하지 않게 아이콘 + 보이는 글(라벨)을 함께 둔다.
const LEVEL_VIEW: Record<
  string,
  { label: string; Icon: LucideIcon; box: string; text: string }
> = {
  [LEVEL_STRONG]: {
    label: "강한 일치",
    Icon: AlertTriangle,
    box: "border-caution bg-caution-bg",
    text: "text-caution-deep",
  },
  [LEVEL_WEAK]: {
    label: "약한 일치",
    Icon: AlertCircle,
    box: "border-review bg-review-bg",
    text: "text-review-deep",
  },
  [LEVEL_DESCRIPTIVE]: {
    label: "설명적 사용",
    Icon: Info,
    box: "border-line bg-card",
    text: "text-blue-dark",
  },
};

/** 빈 글은 없는 것으로 본다. */
function present(value: string | null | undefined): string | null {
  return value && value.trim() ? value : null;
}

/** 배너의 제목·본문 — 모르는 level 이면 null(배너를 그리지 않는다). 표에 없는 조합은 가장 가까운 줄로. */
export function famousBannerText(
  match: SearchV2FamousMatch,
): { title: string; body: string } | null {
  const brand = match.brand;
  const notation = present(match.notation) ?? brand;
  switch (match.level) {
    case LEVEL_DESCRIPTIVE:
      return {
        title: `'${notation}'${josaEunNeun(notation)} 널리 알려진 상표 이름이기도 해요`,
        body: BODY_DESCRIPTIVE,
      };
    case LEVEL_WEAK:
      return {
        title: `널리 알려진 상표 '${brand}'${josaWaGwa(brand)} 이름이 닮았어요`,
        body: BODY_WEAK,
      };
    case LEVEL_STRONG: {
      if (match.basis === BASIS_LOGO) {
        return {
          title: `널리 알려진 상표 '${brand}' 쪽의 등록 로고와 같거나 거의 같아요`,
          body: BODY_LOGO,
        };
      }
      // floor 가 위험이 아니면(검토 권장·null) 둘째 줄 본문
      const body = match.floor === "위험" ? BODY_DANGER : BODY_REVIEW;
      if (match.basis === BASIS_OCR) {
        const text = present(match.matched_text) ?? notation;
        return {
          title: `이미지 속 글자 '${text}'${josaIGa(text)} 널리 알려진 상표 '${brand}'${josaWaGwa(brand)} 같거나 거의 같아요`,
          body,
        };
      }
      return {
        title: `널리 알려진 상표 '${brand}'${josaWaGwa(brand)} 이름이 같거나 거의 같아요`,
        body,
      };
    }
    default:
      return null;
  }
}

/** 둘째 브랜드(matches[1]) 한 줄 — 모르는 level 이면 null. */
export function famousSecondLine(match: SearchV2FamousMatch): string | null {
  switch (match.level) {
    case LEVEL_STRONG:
      return `널리 알려진 상표 '${match.brand}'${josaWaGwa(match.brand)}도 같거나 거의 같아요.`;
    case LEVEL_WEAK:
      return `널리 알려진 상표 '${match.brand}'${josaWaGwa(match.brand)}도 닮았어요.`;
    case LEVEL_DESCRIPTIVE:
      return `'${present(match.notation) ?? match.brand}'도 널리 알려진 상표 이름이에요.`;
    default:
      return null;
  }
}

/** overall.famous_floor 가 true 일 때 전체 등급 아래 한 줄 — floor 가 전체 등급과 같은 첫 일치의 종류로. */
export function famousFloorReason(
  famous: SearchV2Famous | undefined,
  grade: SearchV2Grade | null,
): string {
  const match = famous?.matches.find((item) => item.floor !== null && item.floor === grade);
  return match?.level === LEVEL_WEAK ? FLOOR_REASON_WEAK : FLOOR_REASON_STRONG;
}

/** 배너가 그리는 일치의 종류("강함"·"약함"·"설명적 사용") — 배너를 그리지 않으면 null. 결과 화면이
 *  맨 위 영역의 순서를 정할 때 쓴다(강함·약함 배너 → 설명적 이름 안내 → 설명적 사용 안내). */
export function famousBannerLevel(famous: SearchV2Famous | undefined): string | null {
  if (!famous || famous.status !== "checked") return null;
  const first = famous.matches[0];
  if (!first || !famousBannerText(first) || !LEVEL_VIEW[first.level]) return null;
  return first.level;
}

export const FAMOUS_LEVEL_DESCRIPTIVE = LEVEL_DESCRIPTIVE;

/** 이 배너가 설명적 이름 안내에 주는 영향(계약 v2 §4-7) — 강함·약함 배너가 없으면(없거나 "설명적
 *  사용" 안내) "none", 배너가 이름 쪽의 강한 일치로 떴으면 "name-strong"(설명적 이름 안내를 그리지
 *  않는다), 그 밖의 강함·약함 배너(약한 일치·로고로만 강한 일치)는 "banner"(큰 안내 대신 작은 안내).
 *  이름 쪽 = 로고가 아닌 근거(이름·이미지 속 글자) — 배너가 "이름이 … 같거나 거의 같아요"·"이미지 속
 *  글자 …"라고 말하는 경우와 같다. 배너가 그리는 일치(첫째와 둘째 줄) 가운데 하나라도 그러면 그렇다. */
export function famousBannerState(famous: SearchV2Famous | undefined): FamousBannerState {
  const level = famousBannerLevel(famous);
  if (!famous || level === null || level === LEVEL_DESCRIPTIVE) return "none";
  const nameStrong = famous.matches
    .slice(0, 2)
    .some((match) => match.level === LEVEL_STRONG && match.basis !== BASIS_LOGO);
  return nameStrong ? "name-strong" : "banner";
}

/** 대표 로고 최대 2장 — 주소가 없거나 못 받은 그림은 빼고, 하나도 없으면 칸째 그리지 않는다. */
function FamousLogos({
  brand,
  logos,
}: {
  brand: string;
  logos: SearchV2FamousMatch["logos"];
}) {
  const [failed, setFailed] = useState<ReadonlySet<string>>(() => new Set());
  const shown = logos
    .slice(0, 2)
    .map((logo, index) => ({ key: `${index}:${logo.id}`, src: imageUrl(logo.image_url) }))
    .filter(
      (logo): logo is { key: string; src: string } =>
        logo.src !== null && !failed.has(logo.key),
    );
  if (!shown.length) return null;

  return (
    <div data-testid="famous-logos" className="mt-3 flex flex-wrap gap-2">
      {shown.map((logo) => (
        // eslint-disable-next-line @next/next/no-img-element -- same-origin BFF image path
        <img
          key={logo.key}
          src={logo.src}
          alt={`'${brand}' 대표 로고`}
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed((current) => new Set(current).add(logo.key))}
          className="h-14 w-14 rounded-sm border border-line bg-white object-contain"
        />
      ))}
    </div>
  );
}

export default function FamousBanner({ famous }: { famous: SearchV2Famous | undefined }) {
  const headingId = useId();
  if (!famous) return null;

  if (famous.status === "unavailable") {
    return (
      <p
        data-testid="famous-unavailable"
        className="flex items-center gap-1.5 px-1 text-[11.5px] text-sub"
      >
        <Info aria-hidden size={13} className="shrink-0" />
        {UNAVAILABLE_TEXT}
      </p>
    );
  }
  if (famous.status !== "checked") return null;

  const [first, second] = famous.matches;
  if (!first) return null;
  const text = famousBannerText(first);
  const view = LEVEL_VIEW[first.level];
  if (!text || !view) return null;
  const secondLine = second ? famousSecondLine(second) : null;
  const { Icon } = view;

  return (
    <section
      aria-labelledby={headingId}
      data-testid="famous-banner"
      data-level={first.level}
      className={`rounded-lg border p-5 ${view.box}`}
    >
      <div className="flex items-start gap-3">
        <Icon aria-hidden size={20} className={`mt-0.5 shrink-0 ${view.text}`} />
        <div className="min-w-0 flex-1">
          {/* 결과가 뜨면 포커스는 결과 화면의 제목(h1 "검색 결과")으로 간다(§4-10) — 이 제목은 그 아래 h2 */}
          <h2
            id={headingId}
            className="break-words text-[15px] font-extrabold leading-snug text-ink outline-none"
          >
            {text.title}
          </h2>
          <p className="mt-1.5">
            <span
              data-testid="famous-level"
              className={`inline-block rounded-full bg-card px-2 py-0.5 text-[10.5px] font-bold ${view.text}`}
            >
              {`유명 상표 확인 · ${view.label}`}
            </span>
          </p>
          <p className="mt-2 break-words text-[12.5px] leading-relaxed text-ink">{text.body}</p>
          {secondLine && (
            <p
              data-testid="famous-second"
              className="mt-1.5 break-words text-[12px] font-semibold text-ink"
            >
              {secondLine}
            </p>
          )}
          <FamousLogos key={first.brand} brand={first.brand} logos={first.logos} />
          <p data-testid="famous-footnote" className="mt-3 text-[10.5px] leading-relaxed text-sub">
            {famousFootnote(famous.brand_count)}
          </p>
        </div>
      </div>
    </section>
  );
}
