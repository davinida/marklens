import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Home from "@/app/page";

// 포커스와 화면 낭독기용 알림(API 계약 v2 §4-10) — 검색 중·결과·오류에서 알림 글자가 맞는지, 처음 열었을
// 때는 알림도 포커스 이동도 없는지, 입력 화면으로 돌아가는 버튼이 가리키는 칸으로 포커스가 가는지.

const searchMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({ searchV2: searchMock }));
vi.mock("@/lib/useObjectUrl", () => ({ useObjectUrl: () => null }));
vi.mock("@/components/SearchForm", () => ({
  default: ({ onSubmit }: { onSubmit: (value: Record<string, unknown>) => void }) => (
    <div>
      <h1 data-phase-heading tabIndex={-1}>
        input title
      </h1>
      <button type="button" data-logo-picker>
        pick logo
      </button>
      <input id="mark-text" aria-label="상표 이름" defaultValue="블루커피" />
      <button
        type="button"
        onClick={() =>
          onSubmit({ file: null, markName: "블루커피", topK: 5, goodsCodes: [], turnstileToken: "t" })
        }
      >
        start search
      </button>
    </div>
  ),
}));
vi.mock("@/components/LoadingView", () => ({
  default: ({ onCancel }: { onCancel: () => void }) => (
    <div>
      <h1 data-phase-heading tabIndex={-1}>
        loading title
      </h1>
      <button type="button" onClick={onCancel}>
        cancel search
      </button>
    </div>
  ),
}));
vi.mock("@/components/ResultViewV2", () => ({
  default: (props: {
    onReset: () => void;
    onRename: () => void;
    onRetypeTo: (type: "문자" | "도형" | "결합") => void;
    onUseSuggestedName: (name: string) => void;
    onAddName: (name: string | null) => void;
  }) => (
    <div>
      <h1 data-phase-heading tabIndex={-1}>
        result title
      </h1>
      <button type="button" onClick={props.onReset}>
        other logo
      </button>
      <button type="button" onClick={props.onRename}>
        rename
      </button>
      <button type="button" onClick={() => props.onRetypeTo("도형")}>
        retype
      </button>
      <button type="button" onClick={() => props.onUseSuggestedName("읽은 글자")}>
        use suggested
      </button>
      <button type="button" onClick={() => props.onAddName(null)}>
        add name
      </button>
    </div>
  ),
}));
vi.mock("@/components/ErrorView", () => ({
  default: ({ onEdit, onReset }: { onEdit: () => void; onReset: () => void }) => (
    <div>
      <h1 data-phase-heading tabIndex={-1}>
        error title
      </h1>
      <p role="alert">error sentence</p>
      <button type="button" onClick={onEdit}>
        edit input
      </button>
      <button type="button" onClick={onReset}>
        to start
      </button>
    </div>
  ),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

const result = (grade: string | null) => ({
  overall: { grade, query_type: { type: "문자", source: "fallback", detail: null, suggested_name: null } },
});
const announcement = () => screen.getByTestId("page-announcement");
const heading = (name: string) => screen.getByRole("heading", { level: 1, name });

async function searchTo(grade: string | null) {
  searchMock.mockResolvedValueOnce(result(grade));
  const user = userEvent.setup();
  render(<Home />);
  await user.click(screen.getByRole("button", { name: "start search" }));
  await screen.findByRole("heading", { level: 1, name: "result title" });
  return user;
}

describe("Home — 화면 낭독기용 알림", () => {
  beforeEach(() => searchMock.mockReset());

  it("처음 열었을 때는 알림도 포커스 이동도 없다", async () => {
    render(<Home />);
    // 포커스 이동은 다음 화면 그리기 때 일어난다 — 한 번 기다린 뒤에도 그대로여야 한다
    await act(() => new Promise((resolve) => requestAnimationFrame(() => resolve(undefined))));
    expect(announcement()).toBeEmptyDOMElement();
    expect(document.body).toHaveFocus();
  });

  it("알림 줄은 화면에 보이지 않는 status 한 줄이고 본문(main) 안에 하나뿐이다", () => {
    render(<Home />);
    const line = announcement();
    expect(line).toHaveAttribute("role", "status");
    expect(line).toHaveAttribute("aria-live", "polite");
    expect(line).toHaveClass("sr-only");
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.getByRole("main")).toContainElement(line);
  });

  it("검색 중 → '검색하고 있어요', 결과 → 전체 등급을 알리고 결과 제목으로 포커스", async () => {
    const pending = deferred<unknown>();
    searchMock.mockReturnValueOnce(pending.promise);
    const user = userEvent.setup();
    render(<Home />);
    const line = announcement(); // 화면이 바뀌어도 같은 줄이 남아 있어야 읽힌다

    await user.click(screen.getByRole("button", { name: "start search" }));
    expect(line).toHaveTextContent("검색하고 있어요");
    await vi.waitFor(() => expect(heading("loading title")).toHaveFocus());

    await act(async () => pending.resolve(result("위험")));
    expect(announcement()).toBe(line);
    expect(line).toHaveTextContent("검색 결과가 나왔어요. 전체 등급은 위험이에요.");
    await vi.waitFor(() => expect(heading("result title")).toHaveFocus());
  });

  it("등급 이름의 받침에 맞춘다 — 주의예요", async () => {
    await searchTo("주의");
    expect(announcement()).toHaveTextContent("검색 결과가 나왔어요. 전체 등급은 주의예요.");
  });

  it("등급이 없으면 '비교할 후보가 없어요'", async () => {
    await searchTo(null);
    expect(announcement()).toHaveTextContent("검색 결과가 나왔어요. 비교할 후보가 없어요.");
  });

  it("오류 — 알림 줄은 비우고(오류 화면의 alert 가 알린다) 오류 제목으로 포커스", async () => {
    searchMock.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    render(<Home />);
    await user.click(screen.getByRole("button", { name: "start search" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("error sentence");
    expect(announcement()).toBeEmptyDOMElement();
    await vi.waitFor(() => expect(heading("error title")).toHaveFocus());
  });
});

describe("Home — 입력 화면으로 돌아갈 때의 포커스", () => {
  beforeEach(() => searchMock.mockReset());

  it.each([
    ["다른 이름으로 다시 확인하기", "rename"],
    ["이름 넣고 다시 확인하기", "add name"],
    ["상표명으로 넣기", "use suggested"],
  ])("%s → 이름 칸", async (_label, button) => {
    const user = await searchTo("위험");
    await user.click(screen.getByRole("button", { name: button }));
    await vi.waitFor(() => expect(screen.getByRole("textbox", { name: "상표 이름" })).toHaveFocus());
    expect(announcement()).toBeEmptyDOMElement();
  });

  it("다른 로고 비교하기 → 로고 고르기 버튼", async () => {
    const user = await searchTo("위험");
    await user.click(screen.getByRole("button", { name: "other logo" }));
    await vi.waitFor(() => expect(screen.getByRole("button", { name: "pick logo" })).toHaveFocus());
  });

  it("유형 고치기 → 가리키는 칸이 없어 입력 화면의 제목", async () => {
    const user = await searchTo("위험");
    await user.click(screen.getByRole("button", { name: "retype" }));
    await vi.waitFor(() => expect(heading("input title")).toHaveFocus());
  });

  it("검색 취소 → 입력 화면의 제목, 알림 줄은 비운다", async () => {
    searchMock.mockReturnValueOnce(deferred<unknown>().promise);
    const user = userEvent.setup();
    render(<Home />);
    await user.click(screen.getByRole("button", { name: "start search" }));
    await user.click(await screen.findByRole("button", { name: "cancel search" }));
    await vi.waitFor(() => expect(heading("input title")).toHaveFocus());
    expect(announcement()).toBeEmptyDOMElement();
  });

  it("오류 화면의 두 버튼 → 입력 화면의 제목", async () => {
    for (const button of ["edit input", "to start"]) {
      searchMock.mockRejectedValueOnce(new Error("boom"));
      const user = userEvent.setup();
      const { unmount } = render(<Home />);
      await user.click(screen.getByRole("button", { name: "start search" }));
      await user.click(await screen.findByRole("button", { name: button }));
      await vi.waitFor(() => expect(heading("input title")).toHaveFocus());
      unmount();
    }
  });
});
