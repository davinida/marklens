// @vitest-environment node

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { SearchV2ResponseSchema } from "@/lib/contracts";
import textFixture from "@/test/fixtures/search-v2-text.json";
import imageFixture from "@/test/fixtures/search-v2-image.json";

describe("SearchV2ResponseSchema", () => {
  it.each([textFixture, imageFixture])("accepts and preserves the complete contract fixture", (fixture) => {
    expect(SearchV2ResponseSchema.parse(fixture)).toEqual(fixture);
  });

  it("uses the two verbatim JSON blocks from contract §3", () => {
    const contract = readFileSync(new URL("../../docs/MarkLens_API계약_v2.md", import.meta.url), "utf8");
    const blocks = [...contract.matchAll(/```json\r?\n([\s\S]*?)\r?\n```/g)];
    expect(blocks).toHaveLength(2);
    for (const [index, file] of ["text", "image"].entries()) {
      const fixture = readFileSync(new URL(`../test/fixtures/search-v2-${file}.json`, import.meta.url), "utf8");
      expect(fixture.trimEnd()).toBe(blocks[index][1]);
    }
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
