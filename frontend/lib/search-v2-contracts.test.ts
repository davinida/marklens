// @vitest-environment node

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { SearchV2ResponseSchema } from "@/lib/contracts";
import textFixture from "@/test/fixtures/search-v2-text.json";
import imageFixture from "@/test/fixtures/search-v2-image.json";
import famousFixture from "@/test/fixtures/search-v2-famous.json";
import descriptiveFixture from "@/test/fixtures/search-v2-descriptive.json";

describe("SearchV2ResponseSchema", () => {
  it.each([textFixture, imageFixture, famousFixture, descriptiveFixture])("accepts and preserves the complete contract fixture", (fixture) => {
    expect(SearchV2ResponseSchema.parse(fixture)).toEqual(fixture);
  });

  it("uses the four verbatim JSON blocks from contract §3", () => {
    const contract = readFileSync(new URL("../../docs/MarkLens_API계약_v2.md", import.meta.url), "utf8");
    const blocks = [...contract.matchAll(/```json\r?\n([\s\S]*?)\r?\n```/g)];
    expect(blocks).toHaveLength(4);
    for (const [index, file] of ["text", "image", "famous", "descriptive"].entries()) {
      const fixture = readFileSync(new URL(`../test/fixtures/search-v2-${file}.json`, import.meta.url), "utf8");
      expect(fixture.trimEnd()).toBe(blocks[index][1]);
    }
  });

  it("accepts any rule trigger string, including goods_floor and nameless_floor (v1.4)", () => {
    const fixture = structuredClone(imageFixture);
    fixture.candidates[0].risk.rule_triggers = ["figure_x2_img", "goods_floor", "nameless_floor"];
    expect(SearchV2ResponseSchema.parse(fixture).candidates[0].risk.rule_triggers).toEqual([
      "figure_x2_img",
      "goods_floor",
      "nameless_floor",
    ]);
  });

  it("rejects an unknown grade in overall or a candidate (ported from v1 SearchResponseSchema)", () => {
    const overall = structuredClone(imageFixture) as { overall: { grade: string } };
    overall.overall.grade = "CAUTION";
    expect(SearchV2ResponseSchema.safeParse(overall).success).toBe(false);
    const candidate = structuredClone(imageFixture) as { candidates: { risk: { grade: string } }[] };
    candidate.candidates[0].risk.grade = "UNKNOWN";
    expect(SearchV2ResponseSchema.safeParse(candidate).success).toBe(false);
  });

  it("accepts an empty candidate result with nullable overall fields", () => {
    const fixture = structuredClone(textFixture);
    const empty = {
      ...fixture,
      candidates: [],
      overall: { ...fixture.overall, grade: null, prob: null, caveats: ["비교할 후보가 없습니다 — 안전하다는 뜻이 아닙니다"] },
      top_k_returned: 0,
      meta: { ...fixture.meta, pool: { image: 0, phonetic: 0, spelling: 0, semantic: 0, goods: 0, total: 0 } },
    };
    expect(SearchV2ResponseSchema.parse(empty)).toEqual(empty);
  });

  it("allows signed logit contributions and missing adjustments", () => {
    const fixture = structuredClone(imageFixture);
    fixture.candidates[0].risk.contributions.X1 = -2.5;
    fixture.candidates[0].risk.contributions.요부 = -0.2;
    fixture.candidates[0].risk.missing_adjustment = -0.5;
    expect(SearchV2ResponseSchema.parse(fixture)).toEqual(fixture);
  });

  it("preserves additive fields at every object boundary", () => {
    const fixture = structuredClone(textFixture);
    const candidate = fixture.candidates[0];
    const objects = [
      fixture, fixture.overall, fixture.overall.query_type, candidate,
      candidate.axes, candidate.risk, candidate.risk.contributions,
      candidate.salient, candidate.salient.removed[0], candidate.goods,
      fixture.meta, fixture.meta.thresholds, fixture.meta.thresholds.grade,
      fixture.meta.thresholds.standalone, fixture.meta.pool, fixture.dataset_info,
    ];
    for (const value of objects) Object.assign(value, { future_field: "retained" });
    expect(SearchV2ResponseSchema.parse(fixture)).toEqual(fixture);
    const image = structuredClone(imageFixture);
    Object.assign(image.overall.query_type.detail, { future_detail: 1 });
    expect(SearchV2ResponseSchema.parse(image)).toEqual(image);
  });

  it.each([
    ["research flag", ["research_beta"], false],
    ["legal flag", ["legal_conclusion"], true],
    ["API version", ["api_version"], "v1"],
    ["grade enum", ["overall", "grade"], "SAFE"],
    ["source enum", ["overall", "query_type", "source"], "automatic"],
    ["query type enum", ["overall", "query_type", "type"], "결합"],
    ["visual status enum", ["overall", "visual_status"], "SAFE"],
    ["caveat strings", ["overall", "caveats"], [1]],
    ["overall probability", ["overall", "prob"], 1.01],
    ["axis lower bound", ["candidates", 0, "axes", "x1"], -0.01],
    ["axis upper bound", ["candidates", 0, "axes", "x2_img"], 1.01],
    ["risk null", ["candidates", 0, "risk", "prob"], null],
    ["risk probability", ["candidates", 0, "risk", "prob"], 1.01],
    ["candidate grade", ["candidates", 0, "risk", "grade"], null],
    ["nonfinite contribution", ["candidates", 0, "risk", "contributions", "X1"], Infinity],
    ["nonfinite adjustment", ["candidates", 0, "risk", "missing_adjustment"], NaN],
    ["figure boolean", ["candidates", 0, "risk", "figure_caveat"], "true"],
    ["candidate type", ["candidates", 0, "type"], "결합-문자요부"],
    ["removed side", ["candidates", 0, "salient", "removed", 0, "side"], "all"],
    ["goods similarity", ["candidates", 0, "goods", "jaccard"], -0.1],
    ["nice class integer", ["candidates", 0, "nice_classes"], [1.2]],
    ["nice class range", ["candidates", 0, "nice_classes"], [46]],
    ["precision range", ["meta", "grade_precision"], 1.1],
    ["threshold range", ["meta", "thresholds", "grade", "주의"], -0.1],
    ["threshold numeric", ["meta", "thresholds", "standalone", "x1"], "0.98"],
    ["pool integer", ["meta", "pool", "image"], 1.5],
    ["pool nonnegative", ["meta", "pool", "total"], -1],
    ["elapsed integer", ["meta", "elapsed_ms"], 1.2],
    ["index nonnegative", ["index_size"], -1],
    ["top_k range", ["top_k_requested"], 21],
    ["returned integer", ["top_k_returned"], 0.5],
    ["required field", ["candidates", 0, "risk", "missing_adjustment"], undefined],
  ] as const)("rejects malformed %s", (_label, path, value) => {
    const fixture = structuredClone(textFixture);
    let target: Record<string | number, unknown> = fixture;
    for (const key of path.slice(0, -1)) target = target[key] as Record<string | number, unknown>;
    target[path[path.length - 1]] = value;
    expect(SearchV2ResponseSchema.safeParse(fixture).success).toBe(false);
  });

  it("rejects OCR ratios outside 0..1", () => {
    const fixture = structuredClone(imageFixture);
    fixture.overall.query_type.detail.fig_ratio = 1.1;
    expect(SearchV2ResponseSchema.safeParse(fixture).success).toBe(false);
  });

  it("allows null in candidate metadata and every nullable axis", () => {
    const fixture = structuredClone(imageFixture);
    Object.assign(fixture.candidates[0], { title: null, image_url: null, type: null, applicant: null });
    Object.assign(fixture.candidates[0].axes, { x1: null, x2_text: null, x2_img: null, x3: null, x4: null });
    expect(SearchV2ResponseSchema.safeParse(fixture).success).toBe(true);
  });
});

// 유명 상표 확인(v1.4.7) — famous·overall.famous_floor·candidates[].famous_brand 는 모두 선택 필드
describe("SearchV2ResponseSchema — famous check fields (v1.4.7)", () => {
  function famousMatch(overrides: Record<string, unknown> = {}) {
    return {
      brand: "스타벅스",
      level: "강함",
      basis: "이름",
      notation: "스타벅스",
      matched_text: "스타벅스",
      protection: "업종 불문",
      goods_overlap: false,
      floor: "위험",
      logos: [{ id: "4020190000001", image_url: "/images/4020190000001.png" }],
      ...overrides,
    };
  }

  function withFamousFields() {
    const fixture = structuredClone(textFixture);
    Object.assign(fixture.overall, { famous_floor: true });
    Object.assign(fixture.candidates[0], { famous_brand: "스타벅스" });
    Object.assign(fixture, {
      famous: {
        status: "checked",
        brand_count: 58,
        matches: [
          famousMatch(),
          famousMatch({
            brand: "스타벅스 리저브", level: "약함", basis: "로고", notation: null,
            matched_text: null, protection: "같은·가까운 업종 중심", goods_overlap: null, floor: null,
            logos: [{ id: "4020190000002", image_url: null }],
          }),
        ],
      },
    });
    return fixture;
  }

  it("accepts the new fields and keeps them after parsing", () => {
    const fixture = withFamousFields();
    const parsed = SearchV2ResponseSchema.parse(fixture);
    expect(parsed).toEqual(fixture);
    expect(parsed.overall.famous_floor).toBe(true);
    expect(parsed.candidates[0].famous_brand).toBe("스타벅스");
    expect(parsed.famous?.brand_count).toBe(58);
    expect(parsed.famous?.matches[1].logos[0].image_url).toBeNull();
  });

  it("accepts a response without the new fields and does not invent them", () => {
    for (const fixture of [textFixture, imageFixture]) {
      // 유명 상표 확인이 꺼진 서버(v1.4.6 이하)의 응답 — 픽스처에서 새 선택 필드를 뺀 것
      const older = structuredClone(fixture) as Record<string, unknown> & {
        overall: Record<string, unknown>;
      };
      delete older.famous;
      delete older.overall.famous_floor;
      const parsed = SearchV2ResponseSchema.parse(older);
      expect("famous" in parsed).toBe(false);
      expect("famous_floor" in parsed.overall).toBe(false);
      expect(parsed.candidates.some((candidate) => "famous_brand" in candidate)).toBe(false);
    }
  });

  it("accepts an unavailable check and a checked one without matches", () => {
    for (const famous of [
      { status: "unavailable", brand_count: 58, matches: [] },
      { status: "checked", brand_count: 58, matches: [] },
    ]) {
      const fixture = Object.assign(structuredClone(textFixture), { famous });
      expect(SearchV2ResponseSchema.parse(fixture)).toEqual(fixture);
    }
  });

  it("keeps unknown status/level/basis strings and additive keys (the screen draws only known values)", () => {
    const fixture = withFamousFields();
    const { famous } = fixture as unknown as {
      famous: { status: string; matches: { logos: object[] }[] };
    };
    famous.status = "partial";
    Object.assign(famous, { future_field: "retained" });
    Object.assign(famous.matches[0], { level: "보통", basis: "소리", future_field: 1 });
    Object.assign(famous.matches[0].logos[0], { future_field: true });
    expect(SearchV2ResponseSchema.parse(fixture)).toEqual(fixture);
  });

  it("drops a malformed famous field instead of rejecting the whole response", () => {
    const fixture = structuredClone(textFixture);
    Object.assign(fixture.overall, { famous_floor: "yes" });
    Object.assign(fixture.candidates[0], { famous_brand: 3 });
    Object.assign(fixture, { famous: { status: "checked", brand_count: -1, matches: "none" } });
    const parsed = SearchV2ResponseSchema.safeParse(fixture);
    expect(parsed.success).toBe(true);
    expect(parsed.data?.famous).toBeUndefined();
    expect(parsed.data?.overall.famous_floor).toBeUndefined();
    expect(parsed.data?.candidates[0].famous_brand).toBeUndefined();
    // 나머지는 그대로
    expect(parsed.data?.overall.grade).toBe(textFixture.overall.grade);
    expect(parsed.data?.candidates).toHaveLength(textFixture.candidates.length);
  });
});

describe("contract §3-3 fixture — a famous mark match (v1.4.7)", () => {
  it("keeps the famous block, the floor flag and the brand tags through the schema", () => {
    const parsed = SearchV2ResponseSchema.parse(famousFixture);
    expect(parsed.famous?.status).toBe("checked");
    expect(parsed.famous?.matches).toHaveLength(1);
    expect(parsed.famous?.matches[0]).toMatchObject({
      brand: "스타벅스",
      level: "강함",
      basis: "이름",
      floor: "위험",
      goods_overlap: false,
    });
    expect(parsed.famous?.matches[0].logos.length).toBeGreaterThan(0);
    expect(parsed.overall.grade).toBe("위험");
    expect(parsed.overall.famous_floor).toBe(true);
    expect(parsed.candidates.every((candidate) => candidate.famous_brand === "스타벅스")).toBe(true);
    // 유명 상표 확인을 켠 서버의 일치 없는 응답 — 확인함·일치 없음·바닥 아님
    for (const fixture of [textFixture, imageFixture]) {
      const plain = SearchV2ResponseSchema.parse(fixture);
      expect(plain.famous).toEqual({ status: "checked", brand_count: famousFixture.famous.brand_count, matches: [] });
      expect(plain.overall.famous_floor).toBe(false);
    }
  });
});

describe("SearchV2ResponseSchema — name_words (설명적 이름 안내, 선택 필드)", () => {
  it("keeps the word judgements of the three named fixtures and none for the image-only one", () => {
    expect(SearchV2ResponseSchema.parse(descriptiveFixture).name_words).toEqual({
      generic: "all",
      words: [
        { word: "맛있는", distinctive: false, category: "성질·품질", reason: "3호 기술적 표장:품질(류 29,30,43)" },
        { word: "커피", distinctive: false, category: "상품 이름", reason: "3호 기술적 표장:원재료(류 30,35,43)·1호 보통명칭" },
        { word: "전문점", distinctive: false, category: "성질·품질", reason: "3호 기술적 표장:용도(류 35,43)" },
      ],
      more: 0,
      more_generic: 0,
    });
    const text = SearchV2ResponseSchema.parse(textFixture).name_words;
    expect(text?.generic).toBe("some");
    expect(text?.words.map((word) => [word.word, word.distinctive, word.category])).toEqual([
      ["블루", true, null],
      ["커피", false, "상품 이름"],
    ]);
    const famous = SearchV2ResponseSchema.parse(famousFixture).name_words;
    expect(famous?.generic).toBe("none");
    expect(famous?.words[0]).toMatchObject({ word: "스타벅스", distinctive: true, category: null });
    // 이름이 없는 질의에는 싣지 않는다
    expect("name_words" in SearchV2ResponseSchema.parse(imageFixture)).toBe(false);
  });

  it("accepts a response without the field and does not invent it (older server)", () => {
    const older = structuredClone(descriptiveFixture) as Record<string, unknown>;
    delete older.name_words;
    const parsed = SearchV2ResponseSchema.parse(older);
    expect("name_words" in parsed).toBe(false);
    expect(parsed.candidates).toHaveLength(descriptiveFixture.candidates.length);
  });

  it("keeps unknown generic/category strings and additive keys (the screen draws only known values)", () => {
    const fixture = structuredClone(descriptiveFixture) as typeof descriptiveFixture & {
      name_words: Record<string, unknown> & { words: Record<string, unknown>[] };
    };
    fixture.name_words.generic = "most";
    fixture.name_words.words[0].category = "새 분류";
    fixture.name_words.words[0].future = 1;
    fixture.name_words.future = true;
    const parsed = SearchV2ResponseSchema.parse(fixture);
    expect(parsed.name_words).toMatchObject({ generic: "most", future: true });
    expect(parsed.name_words?.words[0]).toMatchObject({ category: "새 분류", future: 1 });
  });

  it("accepts a word without the raw reason", () => {
    const fixture = structuredClone(descriptiveFixture) as unknown as {
      name_words: { words: Record<string, unknown>[] };
    };
    for (const word of fixture.name_words.words) delete word.reason;
    expect(SearchV2ResponseSchema.parse(fixture).name_words?.words).toHaveLength(3);
  });

  it("drops a malformed name_words field instead of rejecting the whole response", () => {
    for (const broken of [
      { generic: "all", words: "커피", more: 0, more_generic: 0 },
      { generic: "all", words: [{ word: "커피", distinctive: "no", category: null }], more: 0, more_generic: 0 },
      { generic: "all", words: [], more: -1, more_generic: 0 },
      "all",
      null,
    ]) {
      const fixture = Object.assign(structuredClone(descriptiveFixture), { name_words: broken });
      const parsed = SearchV2ResponseSchema.safeParse(fixture);
      expect(parsed.success).toBe(true);
      expect(parsed.data?.name_words).toBeUndefined();
      expect(parsed.data?.overall.grade).toBe(descriptiveFixture.overall.grade);
      expect(parsed.data?.candidates).toHaveLength(descriptiveFixture.candidates.length);
    }
  });
});
