# MarkLens visual evaluation

This directory defines a versioned, visual-only calibration protocol. Human
labels describe what two rendered marks look like. They are not conclusions
about registration, infringement, availability, ownership, or legal rights.

## Artifact generation gate

The artifact-generating evaluation CLIs load `kipris_manifest.json` as the generation commit
marker before reading index content. They fail closed unless all of the
following agree:

- index and metadata filenames, byte counts, and SHA-256 digests;
- manifest and metadata generation IDs;
- model name, pretrained weights, embedding dimension, and embedding contract;
- inner-product/L2-normalization and preprocess contracts;
- authoritative key count, ordered image keys, per-image SHA-256 values, and
  aggregate image-set SHA-256;
- the local authoritative-source SHA-256 when that source is available.

`--with-model` additionally requires the OpenCLIP, FAISS, PyTorch, Pillow, and
NumPy runtime versions to equal the versions recorded by the manifest. An
explicit `--preprocess-version` is only an assertion; evaluation always uses
the manifest's version.

The current 1,000-vector generation is `20260815T023540Z-0d79c662f4c8` and
records `git.dirty=true`. The current labeling pack and v4 robustness reports
use that generation. The preprocessing comparison and v3 robustness JSON files
belong to the historical 105-vector generation. All are execution evidence,
not release/deployment evidence. Before deployment, commit the integrated source,
rebuild the index from a clean tree so the new manifest records
`git.dirty=false`, and regenerate every current evaluation artifact against
that new generation. Deployment must stop if this gate is not satisfied.

## Labeling pack v2

Generate the unlabelled 200-pair pack from one verified generation:

```powershell
venv\Scripts\python.exe scripts\generate_labeling_pack.py `
  --metadata data\index\kipris_metadata.json `
  --index data\index\kipris.faiss `
  --output evaluation\labeling_pack_v2.json
```

The v2 protocol first joins images into one family when their source bytes are
identical or their embedding similarity is at least `0.995`. It assigns each
complete family to either development or frozen holdout before selecting any
pairs. Therefore no image or near-duplicate family can cross the split.

Each split is then sampled across four current similarity regions:

| Selection stratum | Cosine interval | Development | Frozen holdout |
| --- | --- | ---: | ---: |
| `below_weak` | `[-1, 0.45)` | 40 | 10 |
| `weak_band` | `[0.45, 0.55)` | 40 | 10 |
| `possible_band` | `[0.55, 0.75)` | 40 | 10 |
| `strong_band` | `[0.75, 1]` | 40 | 10 |

The pack contains exactly 160 development pairs and 40 frozen-holdout pairs.
All annotation fields are `null`; the generator never infers labels. The JSON
contract is `labeling_pack_v2.schema.json`. The writer will not replace a
different existing pack, which protects labels and frozen membership.

The current blank pack is `vlp2_d32d53e3b6c101517517`, generated from
`20260815T023540Z-0d79c662f4c8`. It contains 769 automatically grouped visual
families and 200 pairs: 160 development, 40 frozen holdout, and zero human
labels. The family count follows the byte-identical/`>=0.995` embedding rule;
it is not an independently adjudicated count of distinct designs.

For the required clean-release regeneration, explicitly replace the current
unlabelled v2 pack after rebuilding the index:

```powershell
venv\Scripts\python.exe scripts\generate_labeling_pack.py `
  --metadata data\index\kipris_metadata.json `
  --index data\index\kipris.faiss `
  --output evaluation\labeling_pack_v2.json `
  --replace-blank
```

`--replace-blank` first validates the complete existing v2 contract and then
requires both label fields to be `null` and annotator/notes fields to be
`null` or whitespace-only. It writes atomically only after those checks. Once
any human annotation exists, the command fails closed; preserve that reviewed
pack and do not use this replacement path.

Annotators inspect only the two images and select one label:

- `same_or_near_duplicate`: effectively the same visible design.
- `visually_similar`: meaningful visible shape/composition resemblance.
- `visually_distinct`: no meaningful visible resemblance.
- `cannot_assess`: missing, corrupt, illegible, or otherwise not judgeable.

Confidence is `high`, `medium`, or `low`. The annotation UI must hide the
similarity stratum, family membership, model score, search rank, trademark
name, owner, classes, and all other legal/model metadata. Resolve development
set disagreements before threshold fitting. Open the 40 frozen pairs only once
the scoring rule and thresholds are fixed.

### Local human review tool

Run the reviewer from the `ml/` directory. It binds only to `127.0.0.1`, uses
no CDN or remote API, and opens only the 160 development pairs by default:

```powershell
venv\Scripts\python.exe scripts\review_labeling_pack.py `
  --annotator-id "jhsoo"
```

Use a stable, non-empty reviewer ID. A saved annotation is owned by that ID;
another ID can read it in the local UI but cannot overwrite or clear it. Use
`--no-browser` to print the URL without opening a browser, or `--port 0` to
select a free loopback port automatically.

The UI shows only two opaque image streams, an opaque pair ID, and human-entered
annotation data. It does not expose the selection stratum, model similarity,
family, source image key, trademark record, or legal metadata. Filters cover
remaining, all, completed, `cannot_assess`, and low-confidence pairs. The pack
order and first remaining pair provide deterministic resume behavior; the
browser also remembers the last visible pair when local storage is available.

Keyboard controls are available when focus is outside a text field or control:

| Action | Key |
| --- | --- |
| Previous / next pair | Left / Right arrow |
| Label choices in displayed order | `1` / `2` / `3` / `4` |
| High / medium / low confidence | `H` / `M` / `L` |
| Save | `Ctrl+Enter` or `Cmd+Enter` |

Each save takes a Windows/POSIX process-level file lock, re-reads the pack,
checks the expected revision, validates the full v2 contract, and writes a
same-directory temporary file before atomically replacing the JSON. A stale
browser revision or external file change fails instead of overwriting newer
work. Keep one review server per pack; if a conflict is reported, inspect the
other writer and then reload the displayed state. Missing or unreadable images can be labeled
`cannot_assess`; absolute paths, traversal, unsupported image types, and
symlink escapes are rejected.

These are individual human annotations, not inferred labels and not gold truth.
Do not report them as an adjudicated reference set unless a separate documented
multi-reviewer and disagreement-resolution process has actually occurred.

### Frozen holdout gate

The default development server never sends a frozen-holdout pair ID or image.
Holdout unlock is one-way for a pack:

1. Label all 160 development pairs and finish disagreement handling, scoring,
   model choices, and threshold tuning.
2. Run the command below without a confirmation. It exits without changing any
   file and prints the pack-specific exact confirmation text.
3. Re-run it with that exact text only when the development decisions are
   frozen.

```powershell
venv\Scripts\python.exe scripts\review_labeling_pack.py `
  --annotator-id "jhsoo" `
  --unlock-holdout

venv\Scripts\python.exe scripts\review_labeling_pack.py `
  --annotator-id "jhsoo" `
  --unlock-holdout `
  --holdout-confirmation "UNLOCK_FROZEN_HOLDOUT:<pack_id printed above>"
```

The second command creates
`evaluation/labeling_pack_v2.holdout_unlock.json` atomically and then opens only
the 40 frozen pairs. Preserve this receipt with the controlled evaluation
artifact; it records the reviewer ID and the canonical SHA-256 of all 160 dev
annotations. Its path is derived from the pack and cannot be redirected to
bypass the freeze. Afterward, normal development mode is locked. A changed dev
annotation makes every holdout startup/save fail closed, and existing holdout
labels without a receipt are not accepted as reconstructed provenance.

Resume an already unlocked holdout without recreating the receipt:

```powershell
venv\Scripts\python.exe scripts\review_labeling_pack.py `
  --annotator-id "jhsoo" `
  --holdout
```

Focused workflow verification (no real pack writes and no network calls):

```powershell
venv\Scripts\python.exe -m pytest tests\test_labeling_review.py -q
venv\Scripts\python.exe -m ruff check `
  evaluation\review.py evaluation\review_server.py `
  scripts\review_labeling_pack.py tests\test_labeling_review.py
node --check evaluation\review_ui\app.js
```

`labeling_pack_v1.json` and `labeling_pack.schema.json` are historical v1
artifacts from an older index generation. V1 selected only the nearest pairs
and allowed the same images to occur in both splits. Never annotate or use v1
for calibration, comparison, or holdout claims.

## Robustness benchmark

The default command verifies the complete artifact generation without
importing OpenCLIP. It prepares a deterministic sample and records whether
rotation, crop, background-margin, and JPEG variants were generated:

```powershell
venv\Scripts\python.exe scripts\evaluate_robustness.py `
  --sample-size 25 --seed 20260814 `
  --output evaluation\robustness_prepare_v4.json
```

Model-backed metrics are opt-in because they load the full model:

```powershell
venv\Scripts\python.exe scripts\evaluate_robustness.py `
  --with-model --sample-size 25 --seed 20260814 `
  --output evaluation\robustness_model_full_v4.json
```

The model report includes exact-item Recall@1/5, target-vector cosine
similarity, and status stability for each transform. Compare reports only when
their recorded generation, manifest/index/metadata/image-set hashes, model,
preprocess, seed, transform version, and runtime versions match.

## Recorded v4 evidence

`robustness_prepare_v4.json` and `robustness_model_full_v4.json` use generation
`20260815T023540Z-0d79c662f4c8`. The deterministic sample contains 25 originals
and 100 transformed queries. All 25 images decoded, all 100 transforms were
created and changed pixels, and decode/transform failures were zero.

| Input | Exact R@1 | Exact R@5 | Status stability | Mean target similarity |
| --- | ---: | ---: | ---: | ---: |
| Original | 0.76 | 1.0 | 1.0 | 1.000000 |
| 90% center crop | 0.72 | 1.0 | 1.0 | 0.945949 |
| 20% gray margin | 0.76 | 1.0 | 1.0 | 0.909052 |
| JPEG quality 60 | 0.76 | 1.0 | 1.0 | 0.982898 |
| 8-degree rotation | 0.76 | 1.0 | 1.0 | 0.936337 |

All six original exact-R@1 misses are members of byte-identical image groups;
the exact target file is at rank 2 or 3 and remains within the top five. The
expanded dataset therefore creates more duplicate/tie opportunities than the
historical 105-image run. This report does not compute family Recall@1, so no
family-retrieval result may be inferred. The v3 and v4 samples also come from
different generations and must not be treated as a paired model comparison.

## Historical paired preprocessing comparison

`preprocess_comparison_full_v1.json` compares legacy center crop with the
global letterbox candidate on the same 105 clean sources. Each mode has 525
queries: 105 originals and 420 deterministic perturbations. The
source-image-level paired gate is `false`; exact and family Recall@1 deltas are
zero, target cosine delta is `+0.003082` with 95% CI
`[-0.001159, 0.007541]`, and non-family margin delta is `-0.003746` with 95%
CI `[-0.014142, 0.006248]`. The evidence therefore retains legacy preprocessing.
All 105 sources are RGB, so this run did not exercise the transparent-alpha
dual-background branch. Fine-tuning remains prohibited because the current
labeling pack has zero completed labels.

## Historical recorded v3 evidence

`robustness_prepare_v3.json` records the seed-20260814 preparation run over 25
images in the pre-expansion 105-vector generation. All 100 perturbations were created,
all 100 changed pixels, and no image failed to decode. This run intentionally
did not load the model.

`robustness_model_full_v3.json` evaluates the same 25-image preparation sample:
25 originals plus 100 transformed queries. Exact-item Recall@1 is `0.96` and
Recall@5 is `1.0` for the original and every transform. The one R@1 miss is a
rank-2 tie inside a byte-identical three-file family. Mean target similarities
are `0.956777` for crop, `0.919369` for gray margin, `0.989764` for JPEG quality
60, and `0.953514` for 8-degree rotation. Status stability is `1.0` except for
gray margin, where it is `0.96`: one query moved from `STRONG_MATCH` to
`POSSIBLE_MATCH` at target similarity `0.716410` while remaining at rank 1.

The full report is a deterministic 25-image sample from the historical 105-image
index, not an independent labelled evaluation set. These results do not show
that thresholds are calibrated or that rates generalize to unseen marks. Use
the frozen 40-pair holdout only after visual labels and development-set
calibration are complete.

The `robustness_*_v1.json`, `robustness_*_v2.json`, and v3 files are historical
reports from earlier artifact generations. Preserve them, but do not compare
them directly across generations or cite them as current 1,000-vector results.
