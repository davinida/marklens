"use strict";

const REVIEW_PROTOCOL = "marklens-local-human-review-v1";
const LABEL_VALUES = [
  "same_or_near_duplicate",
  "visually_similar",
  "visually_distinct",
  "cannot_assess",
];
const CONFIDENCE_VALUES = ["high", "medium", "low"];
const FILTER_LABELS = {
  remaining: "미완료",
  all: "전체",
  labeled: "완료",
  cannot_assess: "판정 불가",
  low: "낮은 확신도",
};

const csrfToken = document
  .querySelector('meta[name="marklens-csrf"]')
  .getAttribute("content");

const elements = {
  workspace: document.getElementById("workspace"),
  modeBadge: document.getElementById("modeBadge"),
  annotatorText: document.getElementById("annotatorText"),
  progressText: document.getElementById("progressText"),
  remainingText: document.getElementById("remainingText"),
  progressTrack: document.getElementById("progressTrack"),
  filterButtons: Array.from(document.querySelectorAll(".filter-button")),
  previousButton: document.getElementById("previousButton"),
  nextButton: document.getElementById("nextButton"),
  pairPosition: document.getElementById("pairPosition"),
  pairId: document.getElementById("pairId"),
  emptyState: document.getElementById("emptyState"),
  imageGrid: document.getElementById("imageGrid"),
  leftImage: document.getElementById("leftImage"),
  rightImage: document.getElementById("rightImage"),
  leftImageButton: document.getElementById("leftImageButton"),
  rightImageButton: document.getElementById("rightImageButton"),
  leftFallback: document.getElementById("leftFallback"),
  rightFallback: document.getElementById("rightFallback"),
  annotationForm: document.getElementById("annotationForm"),
  labelFieldset: document.getElementById("labelFieldset"),
  confidenceFieldset: document.getElementById("confidenceFieldset"),
  notesInput: document.getElementById("notesInput"),
  characterCount: document.getElementById("characterCount"),
  saveState: document.getElementById("saveState"),
  ownershipNotice: document.getElementById("ownershipNotice"),
  saveButton: document.getElementById("saveButton"),
  clearButton: document.getElementById("clearButton"),
  appStatus: document.getElementById("appStatus"),
  imageDialog: document.getElementById("imageDialog"),
  dialogTitle: document.getElementById("dialogTitle"),
  dialogImage: document.getElementById("dialogImage"),
  closeDialogButton: document.getElementById("closeDialogButton"),
};

let reviewState = null;
let currentPairId = null;
let activeFilter = "remaining";
let dirty = false;
let saving = false;

function annotationIsComplete(annotation) {
  return (
    annotation !== null &&
    LABEL_VALUES.includes(annotation.visual_similarity) &&
    CONFIDENCE_VALUES.includes(annotation.confidence) &&
    typeof annotation.annotator_id === "string" &&
    annotation.annotator_id.length > 0
  );
}

function validateState(value) {
  if (
    value === null ||
    typeof value !== "object" ||
    value.protocol !== REVIEW_PROTOCOL ||
    value.label_origin !== "human_annotation_not_gold" ||
    !["dev", "frozen_holdout"].includes(value.mode) ||
    typeof value.pack_id !== "string" ||
    typeof value.annotator_id !== "string" ||
    typeof value.revision !== "string" ||
    value.counts === null ||
    typeof value.counts !== "object" ||
    !Array.isArray(value.pairs)
  ) {
    throw new Error("서버 상태가 로컬 검수 계약과 일치하지 않습니다.");
  }
  for (const pair of value.pairs) {
    if (
      pair === null ||
      typeof pair !== "object" ||
      typeof pair.pair_id !== "string" ||
      typeof pair.position !== "number" ||
      typeof pair.left_url !== "string" ||
      typeof pair.right_url !== "string" ||
      typeof pair.editable !== "boolean" ||
      pair.annotation === null ||
      typeof pair.annotation !== "object"
    ) {
      throw new Error("검수 쌍 데이터가 올바르지 않습니다.");
    }
  }
  return value;
}

function currentPair() {
  if (reviewState === null || currentPairId === null) {
    return null;
  }
  return reviewState.pairs.find((pair) => pair.pair_id === currentPairId) || null;
}

function pairsForFilter(filterName = activeFilter) {
  if (reviewState === null) {
    return [];
  }
  return reviewState.pairs.filter((pair) => {
    const annotation = pair.annotation;
    const complete = annotationIsComplete(annotation);
    if (filterName === "remaining") {
      return !complete;
    }
    if (filterName === "labeled") {
      return complete;
    }
    if (filterName === "cannot_assess") {
      return annotation.visual_similarity === "cannot_assess";
    }
    if (filterName === "low") {
      return annotation.confidence === "low";
    }
    return true;
  });
}

function persistedPairKey() {
  if (reviewState === null) {
    return "";
  }
  return [
    "marklens-review:last-pair",
    reviewState.pack_id,
    reviewState.mode,
    reviewState.annotator_id,
  ].join(":");
}

function rememberCurrentPair() {
  if (currentPairId === null || reviewState === null) {
    return;
  }
  try {
    window.localStorage.setItem(persistedPairKey(), currentPairId);
  } catch (_error) {
    // The pack itself still provides a deterministic first-unlabelled resume point.
  }
}

function preferredInitialPair(pairs) {
  if (reviewState === null || pairs.length === 0) {
    return null;
  }
  try {
    const savedPairId = window.localStorage.getItem(persistedPairKey());
    if (pairs.some((pair) => pair.pair_id === savedPairId)) {
      return savedPairId;
    }
  } catch (_error) {
    // Fall through to the first pair in the filtered pack order.
  }
  return pairs[0].pair_id;
}

function normalizedNotes(value) {
  const normalized = value.replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
  return normalized.length > 0 ? normalized : null;
}

function selectedValue(name) {
  const checked = elements.annotationForm.querySelector(
    `input[name="${name}"]:checked`,
  );
  return checked ? checked.value : null;
}

function formDraft() {
  return {
    visual_similarity: selectedValue("visualSimilarity"),
    confidence: selectedValue("confidence"),
    notes: normalizedNotes(elements.notesInput.value),
  };
}

function draftDiffersFromSaved() {
  const pair = currentPair();
  if (pair === null) {
    return false;
  }
  const draft = formDraft();
  return (
    draft.visual_similarity !== pair.annotation.visual_similarity ||
    draft.confidence !== pair.annotation.confidence ||
    draft.notes !== pair.annotation.notes
  );
}

function updateDirtyState() {
  dirty = draftDiffersFromSaved();
  renderFormState();
}

function setStatus(message, tone = "neutral") {
  elements.appStatus.textContent = message;
  elements.appStatus.dataset.tone = tone;
}

function clearStatus() {
  elements.appStatus.textContent = "";
  delete elements.appStatus.dataset.tone;
}

function confirmDiscard() {
  return !dirty || window.confirm("저장하지 않은 변경을 버리고 이동할까요?");
}

function filterCounts() {
  return {
    remaining: pairsForFilter("remaining").length,
    all: pairsForFilter("all").length,
    labeled: pairsForFilter("labeled").length,
    cannot_assess: pairsForFilter("cannot_assess").length,
    low: pairsForFilter("low").length,
  };
}

function renderProgress() {
  if (reviewState === null) {
    return;
  }
  const { total, labeled, remaining } = reviewState.counts;
  elements.progressText.textContent = `${labeled} / ${total}`;
  elements.remainingText.textContent = `남은 쌍 ${remaining}`;
  elements.progressTrack.max = total;
  elements.progressTrack.value = labeled;

  const counts = filterCounts();
  for (const button of elements.filterButtons) {
    const filterName = button.dataset.filter;
    button.textContent = `${FILTER_LABELS[filterName]} ${counts[filterName]}`;
    button.setAttribute("aria-pressed", String(filterName === activeFilter));
  }
}

function setRadioValue(name, value) {
  for (const input of elements.annotationForm.querySelectorAll(
    `input[name="${name}"]`,
  )) {
    input.checked = input.value === value;
  }
}

function renderImage(img, button, fallback, source) {
  img.hidden = false;
  fallback.hidden = true;
  button.disabled = false;
  img.removeAttribute("src");
  img.src = source;
}

function renderPair() {
  const pair = currentPair();
  const filtered = pairsForFilter();
  const empty = pair === null || !filtered.some((item) => item.pair_id === pair.pair_id);

  elements.emptyState.hidden = !empty;
  elements.imageGrid.hidden = empty;
  elements.annotationForm.hidden = empty;
  if (empty) {
    elements.pairPosition.textContent = "쌍 0 / 0";
    elements.pairId.textContent = "-";
    elements.previousButton.disabled = true;
    elements.nextButton.disabled = true;
    dirty = false;
    return;
  }

  const filterIndex = filtered.findIndex((item) => item.pair_id === pair.pair_id);
  elements.pairPosition.textContent = `쌍 ${filterIndex + 1} / ${filtered.length}`;
  elements.pairId.textContent = pair.pair_id;
  elements.previousButton.disabled = filterIndex <= 0 || saving;
  elements.nextButton.disabled = filterIndex >= filtered.length - 1 || saving;

  renderImage(
    elements.leftImage,
    elements.leftImageButton,
    elements.leftFallback,
    pair.left_url,
  );
  renderImage(
    elements.rightImage,
    elements.rightImageButton,
    elements.rightFallback,
    pair.right_url,
  );

  setRadioValue("visualSimilarity", pair.annotation.visual_similarity);
  setRadioValue("confidence", pair.annotation.confidence);
  elements.notesInput.value = pair.annotation.notes || "";
  elements.characterCount.textContent = `${elements.notesInput.value.length} / 2000`;
  dirty = false;
  renderFormState();
  rememberCurrentPair();
}

function renderFormState() {
  const pair = currentPair();
  if (pair === null) {
    return;
  }
  const complete = annotationIsComplete(pair.annotation);
  const editable = pair.editable && !saving;
  const draft = formDraft();
  elements.labelFieldset.disabled = !editable;
  elements.confidenceFieldset.disabled = !editable;
  elements.notesInput.disabled = !editable;
  elements.ownershipNotice.hidden = pair.editable;
  elements.saveButton.disabled =
    !editable ||
    !dirty ||
    !LABEL_VALUES.includes(draft.visual_similarity) ||
    !CONFIDENCE_VALUES.includes(draft.confidence);
  elements.clearButton.disabled = !editable || !complete || saving;

  if (!pair.editable) {
    elements.saveState.textContent = "읽기 전용";
    elements.saveState.dataset.state = "readonly";
  } else if (dirty) {
    elements.saveState.textContent = "저장되지 않음";
    elements.saveState.dataset.state = "dirty";
  } else if (complete) {
    elements.saveState.textContent = "저장됨";
    elements.saveState.dataset.state = "saved";
  } else {
    elements.saveState.textContent = "미완료";
    elements.saveState.dataset.state = "dirty";
  }
}

function renderEnvironment() {
  if (reviewState === null) {
    return;
  }
  elements.modeBadge.textContent =
    reviewState.mode === "dev" ? "개발 세트" : "동결 홀드아웃 · 해제됨";
  elements.annotatorText.textContent = `검수자: ${reviewState.annotator_id}`;
}

function renderAll() {
  renderEnvironment();
  renderProgress();
  renderPair();
  elements.workspace.setAttribute("aria-busy", "false");
}

function choosePair(pairId) {
  if (!confirmDiscard()) {
    return false;
  }
  currentPairId = pairId;
  clearStatus();
  renderPair();
  return true;
}

function movePair(offset) {
  const filtered = pairsForFilter();
  const index = filtered.findIndex((pair) => pair.pair_id === currentPairId);
  const next = filtered[index + offset];
  if (next) {
    choosePair(next.pair_id);
  }
}

function changeFilter(filterName) {
  if (!(filterName in FILTER_LABELS) || filterName === activeFilter) {
    return;
  }
  if (!confirmDiscard()) {
    return;
  }
  activeFilter = filterName;
  const filtered = pairsForFilter();
  currentPairId = preferredInitialPair(filtered);
  clearStatus();
  renderProgress();
  renderPair();
}

async function apiRequest(url, options = {}) {
  const response = await fetch(url, {
    cache: "no-store",
    credentials: "same-origin",
    ...options,
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    // A generic local error is safer than rendering arbitrary non-JSON response text.
  }
  if (!response.ok) {
    const error = new Error(
      payload && typeof payload.error === "string"
        ? payload.error
        : `로컬 요청 실패 (${response.status})`,
    );
    error.status = response.status;
    throw error;
  }
  return payload;
}

async function loadState({ preservePair = false } = {}) {
  const previousPair = preservePair ? currentPairId : null;
  const value = await apiRequest("/api/state");
  reviewState = validateState(value);
  if (reviewState.counts.remaining === 0 && activeFilter === "remaining") {
    activeFilter = "all";
  }
  const filtered = pairsForFilter();
  currentPairId = filtered.some((pair) => pair.pair_id === previousPair)
    ? previousPair
    : preferredInitialPair(filtered);
  dirty = false;
  renderAll();
}

function nextVisibleAfter(previousIndex) {
  const filtered = pairsForFilter();
  if (filtered.length === 0) {
    return null;
  }
  return (
    filtered.find(
      (pair) => reviewState.pairs.findIndex((item) => item.pair_id === pair.pair_id) > previousIndex,
    ) || filtered[0]
  );
}

async function submitAnnotation({ clear = false } = {}) {
  const pair = currentPair();
  if (pair === null || saving || !pair.editable) {
    return;
  }
  if (!clear && !dirty) {
    return;
  }
  const draft = formDraft();
  if (
    !clear &&
    (!LABEL_VALUES.includes(draft.visual_similarity) ||
      !CONFIDENCE_VALUES.includes(draft.confidence))
  ) {
    setStatus("시각적 관계와 확신도를 모두 선택하세요.", "error");
    return;
  }

  saving = true;
  renderFormState();
  setStatus(clear ? "저장값을 지우는 중입니다." : "판단을 저장하는 중입니다.");
  const previousIndex = reviewState.pairs.findIndex(
    (item) => item.pair_id === pair.pair_id,
  );
  let pairShouldRender = false;
  try {
    const response = await apiRequest("/api/annotation", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-MarkLens-CSRF": csrfToken,
      },
      body: JSON.stringify({
        pair_id: pair.pair_id,
        expected_revision: reviewState.revision,
        visual_similarity: clear ? null : draft.visual_similarity,
        confidence: clear ? null : draft.confidence,
        notes: clear ? null : draft.notes,
        clear,
      }),
    });
    pair.annotation = response.annotation;
    pair.editable = true;
    reviewState.revision = response.revision;
    reviewState.counts = response.counts;
    dirty = false;

    if (!pairsForFilter().some((item) => item.pair_id === pair.pair_id)) {
      const next = nextVisibleAfter(previousIndex);
      currentPairId = next ? next.pair_id : null;
    }
    if (activeFilter === "remaining" && reviewState.counts.remaining === 0) {
      activeFilter = "all";
      currentPairId = pair.pair_id;
    }
    pairShouldRender = true;
    setStatus(clear ? "저장값을 지웠습니다." : "사람의 판단을 저장했습니다.", "success");
  } catch (error) {
    if (error.status === 409) {
      try {
        await loadState({ preservePair: true });
        pairShouldRender = true;
      } catch (_reloadError) {
        // Keep the original conflict message if a refresh also fails.
      }
      setStatus("파일이 다른 곳에서 변경되었습니다. 최신 상태를 다시 불러왔습니다.", "error");
    } else {
      setStatus(error.message || "저장하지 못했습니다.", "error");
    }
  } finally {
    saving = false;
    renderProgress();
    if (pairShouldRender) {
      renderPair();
    } else {
      renderFormState();
    }
  }
}

function handleImageError(img, button, fallback) {
  img.hidden = true;
  fallback.hidden = false;
  button.disabled = true;
}

function openImageDialog(img, title) {
  if (!img.src || img.hidden) {
    return;
  }
  elements.dialogTitle.textContent = title;
  elements.dialogImage.src = img.src;
  elements.dialogImage.alt = `${title} 확대 이미지`;
  elements.imageDialog.showModal();
}

function editableTarget(target) {
  return (
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLButtonElement ||
    target instanceof HTMLSelectElement ||
    target.isContentEditable
  );
}

function chooseShortcutRadio(name, value) {
  const pair = currentPair();
  if (pair === null || !pair.editable || saving) {
    return;
  }
  const input = elements.annotationForm.querySelector(
    `input[name="${name}"][value="${value}"]`,
  );
  if (input && !input.disabled) {
    input.checked = true;
    updateDirtyState();
  }
}

elements.filterButtons.forEach((button) => {
  button.addEventListener("click", () => changeFilter(button.dataset.filter));
});
elements.previousButton.addEventListener("click", () => movePair(-1));
elements.nextButton.addEventListener("click", () => movePair(1));
elements.annotationForm.addEventListener("input", () => {
  elements.characterCount.textContent = `${elements.notesInput.value.length} / 2000`;
  updateDirtyState();
});
elements.annotationForm.addEventListener("change", updateDirtyState);
elements.annotationForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void submitAnnotation();
});
elements.clearButton.addEventListener("click", () => {
  if (window.confirm("이 쌍에 저장된 사람의 판단을 지울까요?")) {
    void submitAnnotation({ clear: true });
  }
});
elements.leftImage.addEventListener("error", () =>
  handleImageError(
    elements.leftImage,
    elements.leftImageButton,
    elements.leftFallback,
  ),
);
elements.rightImage.addEventListener("error", () =>
  handleImageError(
    elements.rightImage,
    elements.rightImageButton,
    elements.rightFallback,
  ),
);
elements.leftImageButton.addEventListener("click", () =>
  openImageDialog(elements.leftImage, "이미지 A 크게 보기"),
);
elements.rightImageButton.addEventListener("click", () =>
  openImageDialog(elements.rightImage, "이미지 B 크게 보기"),
);
elements.closeDialogButton.addEventListener("click", () =>
  elements.imageDialog.close(),
);
elements.imageDialog.addEventListener("click", (event) => {
  if (event.target === elements.imageDialog) {
    elements.imageDialog.close();
  }
});

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    elements.annotationForm.requestSubmit();
    return;
  }
  if (event.altKey || event.ctrlKey || event.metaKey || editableTarget(event.target)) {
    return;
  }
  const labelShortcut = {
    1: "same_or_near_duplicate",
    2: "visually_similar",
    3: "visually_distinct",
    4: "cannot_assess",
  }[event.key];
  if (labelShortcut) {
    event.preventDefault();
    chooseShortcutRadio("visualSimilarity", labelShortcut);
    return;
  }
  const confidenceShortcut = {
    h: "high",
    m: "medium",
    l: "low",
  }[event.key.toLowerCase()];
  if (confidenceShortcut) {
    event.preventDefault();
    chooseShortcutRadio("confidence", confidenceShortcut);
    return;
  }
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    movePair(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    movePair(1);
  }
});

window.addEventListener("beforeunload", (event) => {
  if (dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});

loadState().catch((error) => {
  elements.workspace.setAttribute("aria-busy", "false");
  setStatus(error.message || "로컬 검수 상태를 불러오지 못했습니다.", "error");
});
