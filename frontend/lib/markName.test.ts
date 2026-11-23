// @vitest-environment node

// 상표명 입력 정리(cleanInputName)가 백엔드 clean_input_name(ml/src/axes/pair_axes.py)과 같은 결과를 내는지 —
// 공용 사례 shared/text/clean_input_name_cases.json 으로 본다(pytest 도 같은 파일, 견고성 점검 B14·U3).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { cleanInputName, isFormatCharacter, isStripSpace } from "@/lib/markName";

interface SharedCases {
  python_unicode_version: string;
  format_code_points: number[];
  strip_code_points: number[];
  cases: { input: string; expected: string; note: string }[];
}

const shared: SharedCases = JSON.parse(
  readFileSync(new URL("../../shared/text/clean_input_name_cases.json", import.meta.url), "utf8"),
);

describe("cleanInputName — 백엔드 clean_input_name 과 같은 공용 사례", () => {
  it.each(shared.cases.map((item) => [item.note, item.input, item.expected]))(
    "%s",
    (_note, input, expected) => {
      expect(cleanInputName(input)).toBe(expected);
    },
  );

  it("지우는 서식 문자·떼는 공백의 집합이 백엔드 파이썬과 같다(코드 포인트 전체)", () => {
    const format = new Set(shared.format_code_points);
    const strip = new Set(shared.strip_code_points);
    const differ: string[] = [];
    for (let cp = 0; cp <= 0x10ffff; cp += 1) {
      if (cp >= 0xd800 && cp <= 0xdfff) continue; // 홀로 선 대리 코드는 문자열 한 글자가 될 수 없다
      const char = String.fromCodePoint(cp);
      if (isFormatCharacter(char) !== format.has(cp)) differ.push(`서식 U+${cp.toString(16)}`);
      if (isStripSpace(char) !== strip.has(cp)) differ.push(`공백 U+${cp.toString(16)}`);
    }
    expect(differ).toEqual([]);
  });

  it("null·undefined 는 빈 이름", () => {
    expect(cleanInputName(null)).toBe("");
    expect(cleanInputName(undefined)).toBe("");
  });
});
