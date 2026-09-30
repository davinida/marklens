import { describe, expect, it } from "vitest";
import {
  addSelectedGood,
  goodsCodeUnion,
  goodsSummaryText,
  MAX_SELECTED_GOODS,
  removeSelectedGood,
  selectedGoodKey,
  type SelectedGood,
} from "@/lib/goods";

const COFFEE: SelectedGood = { name: "커피", nice_class: 30, similarity_codes: ["G0502"] };
const CAFE: SelectedGood = {
  name: "커피전문점업",
  nice_class: 43,
  similarity_codes: ["S120602", "G0502"],
};

describe("goods selection helpers", () => {
  it("unions similarity codes without duplicates, sorted", () => {
    expect(goodsCodeUnion([])).toEqual([]);
    expect(goodsCodeUnion([COFFEE, CAFE])).toEqual(["G0502", "S120602"]);
  });

  it("adds, rejects duplicates by name+class and enforces the cap", () => {
    const first = addSelectedGood([], COFFEE);
    expect(first).toEqual({ added: true, next: [COFFEE] });
    const dup = addSelectedGood(first.next, { ...COFFEE, similarity_codes: ["G9999"] });
    expect(dup.added).toBe(false);
    expect(dup).toMatchObject({ reason: "duplicate" });
    // 같은 이름이라도 류가 다르면 다른 상품
    expect(addSelectedGood(first.next, { ...COFFEE, nice_class: 43 }).added).toBe(true);

    const full = Array.from({ length: MAX_SELECTED_GOODS }, (_, i) => ({
      name: `상품${i}`,
      nice_class: 1,
      similarity_codes: [`G${i}`],
    }));
    expect(addSelectedGood(full, CAFE)).toMatchObject({ added: false, reason: "limit" });
    expect(addSelectedGood(full, CAFE).next).toHaveLength(MAX_SELECTED_GOODS);
  });

  it("removes by key and summarises names with the code count", () => {
    expect(selectedGoodKey(COFFEE)).toBe("30:커피");
    expect(removeSelectedGood([COFFEE, CAFE], COFFEE)).toEqual([CAFE]);
    expect(goodsSummaryText([])).toBe("");
    expect(goodsSummaryText([COFFEE, CAFE])).toBe("커피, 커피전문점업 (유사군 2개)");
  });
});
