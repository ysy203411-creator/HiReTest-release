# HiReTest

HiReTest is a historical repair-guided test-generation method for progressive programming assignments. It mines changes between repaired and inherited code, identifies repair-relevant changes, combines them with assignment constraints, and uses a large language model to generate and review tests. This repository contains the HiReTest implementation, public prompt templates, and the released outputs of the main method on five SysY compiler-assignment transitions.

This is the first stable public release, version `1.0.0`.

## Release scope

This repository releases only the implementation and experimental outputs of **HiReTest itself**. Implementations, adapters, configurations, generated outputs, ablation results, and human-evaluation materials for comparison methods are outside the scope of this release.

The comparison experiments reported in the paper were conducted using the corresponding public implementations and the settings described in the paper. This repository is a HiReTest main-method release, not a complete reproduction package for every comparison experiment in the paper.

## Repository layout

```text
.
├── artifacts/                # released HiReTest test cases and result workbooks
├── data/                     # empty placeholder for locally obtained authorized data
├── prompts/public_templates/ # public generation, constraint, and review prompts
├── requirements/core.txt     # Python dependencies for HiReTest
├── scripts/                  # artifact-manifest generator
├── src/hiretest/             # HiReTest implementation and evaluator
├── .env.example              # environment-variable template without real secrets
├── CITATION.cff              # citation metadata
├── LICENSE                   # MIT License
└── pyproject.toml            # Python package metadata
```

## Released artifacts

```text
artifacts/
├── cases/Hiretest/
│   ├── 1to2/
│   ├── 2to3/
│   ├── 3to4/
│   ├── 4to5/
│   └── 5to6/
├── results/Hiretest/
│   ├── analysis_1to2.xlsx
│   ├── analysis_2to3.xlsx
│   ├── analysis_3to4.xlsx
│   ├── analysis_4to5.xlsx
│   └── analysis_5to6.xlsx
└── manifest.json
```

| Transition | Test programs | Input files | Result workbook |
| --- | ---: | ---: | --- |
| `1to2` | 213 | 0 | `analysis_1to2.xlsx` |
| `2to3` | 389 | 0 | `analysis_2to3.xlsx` |
| `3to4` | 93 | 0 | `analysis_3to4.xlsx` |
| `4to5` | 240 | 240 | `analysis_4to5.xlsx` |
| `5to6` | 59 | 59 | `analysis_5to6.xlsx` |

For the first three transitions, each `caseN.txt` is a complete SysY source program. For `4to5` and `5to6`, each test consists of a `caseN.txt` source program and the matching `inputN.txt` standard-input file.

`artifacts/manifest.json` records the released files, counts, and SHA-256 checksums.

## Implementation

The main pipeline is implemented under `src/hiretest/`:

- `compare.py` and `analyse.py` compare adjacent program versions and analyze AST-level changes. Here, “compare” refers to comparing historical program versions, not comparison methods.
- `data_preprocessing.py` converts historical changes and labels into model-ready data.
- `train.py` trains and evaluates the repair-change classifier.
- `export_positive_predictions.py` exports changes predicted to be repair-relevant.
- `get_results.py` extracts source context and constructs history-guided generation prompts.
- `ask_for_llm.py` generates, reviews, and repairs candidate tests through a configured LLM API.
- `test.py` compiles and executes generated tests and produces result workbooks.
- `reproduce_test.py` provides the command-line entry point for reevaluating released HiReTest cases.
- `runtime.ll` provides the LLVM-compatible SysY input/output runtime used by backend stages.

The public files under `prompts/public_templates/` contain generation prompts, processed and raw stage constraints, and test-review prompts for all five transitions.

## Installation

Python 3.10 or later is required. A virtual environment is recommended.

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

or on Linux/macOS:

```bash
source .venv/bin/activate
```

Install the project and its core dependencies:

```bash
python -m pip install -r requirements/core.txt
python -m pip install -e .
```

## Preparing external data

The public repository intentionally leaves `data/` empty. Obtain the authorized or
Zenodo-hosted data package described in the Data and privacy section, extract it outside
the repository when possible, and configure the paths before running the full pipeline.
The assignment IDs below are placeholders; replace them with the ordered IDs documented
by the data package.

```powershell
$env:HIRETEST_DATA_ROOT = "D:\path\to\authorized\submissions"
$env:HIRETEST_DERIVED_DATA_ROOT = "D:\path\to\hiretest-workspace"
$env:HIRETEST_ASSIGNMENT_SEQUENCE = "assignment1,assignment2,assignment3,assignment4,assignment5,assignment6"
$env:HIRETEST_TARGET_ASSIGNMENT_IDS = "assignment2,assignment3,assignment4,assignment5,assignment6"
$env:HIRETEST_TRANSITION_DIRS = "version_diffs/assignment1_to_assignment2,version_diffs/assignment2_to_assignment3,version_diffs/assignment3_to_assignment4,version_diffs/assignment4_to_assignment5,version_diffs/assignment5_to_assignment6"
```

Generate GumTree comparisons for one adjacent transition with explicit assignment IDs:

```powershell
python -m hiretest.compare `
  --data-root $env:HIRETEST_DATA_ROOT `
  --derived-root $env:HIRETEST_DERIVED_DATA_ROOT `
  --from-assignment assignment1 `
  --to-assignment assignment2
```

Filter one generated transition without relying on repository-specific directories:

```powershell
python -m hiretest.analyse `
  --data-root $env:HIRETEST_DATA_ROOT `
  --diff-root "$env:HIRETEST_DERIVED_DATA_ROOT\version_diffs\assignment1_to_assignment2" `
  --output-root "$env:HIRETEST_DERIVED_DATA_ROOT\filtered_changes\1to2" `
  --report "$env:HIRETEST_DERIVED_DATA_ROOT\outputs\change_analysis_1to2.xlsx"
```

`data_preprocessing.py` and `get_results.py` accept the same mappings through
`--assignment-ids` and `--transition-dirs`. Run either command with `--help` for the
complete interface. Model checkpoints and prediction reports default to `models/` and
`outputs/` under `HIRETEST_DERIVED_DATA_ROOT`. Newly generated LLM cases default to
`artifacts/generated/`; released results under `artifacts/cases/` are never overwritten.

## Inspecting the release

Run a dry check to confirm that all released stage directories are visible:

```bash
python -m hiretest.reproduce_test --case-root artifacts/cases --stage all --dry-run
```

After changing the released artifacts, rebuild the integrity manifest with:

```bash
python scripts/build_artifact_manifest.py
```

## Reevaluating released tests

Raw student submissions, identities, grades, reference implementations, and other course-confidential inputs are not included. Full reevaluation requires an authorized data package plus local MARS and LLVM installations configured through `.env.example`.

For example, on Windows:

```powershell
python -m hiretest.reproduce_test `
  --case-root artifacts/cases `
  --stage 1to2 `
  --students-dir D:\path\to\authorized\submissions `
  --assignment-ids assignment2,assignment3,assignment4,assignment5,assignment6
```

Newly reproduced workbooks are written under `artifacts/reproduced/` by default and do not overwrite the released workbooks.

The evaluator uses the following environment variables when applicable:

- `HIRETEST_DATA_ROOT` points to authorized submissions outside the repository.
- `HIRETEST_DERIVED_DATA_ROOT` points to a writable workspace for intermediate data, models, and reports.
- `HIRETEST_ASSIGNMENT_SEQUENCE` records the six ordered assignment IDs used by the five-stage pipeline.
- `HIRETEST_TARGET_ASSIGNMENT_IDS` records the five target IDs used when reevaluating released tests.
- `HIRETEST_TRANSITION_DIRS` maps the five stages to their generated diff directories.
- `HIRETEST_REPAIR_PROMPT_ROOT` points to authorized history-guided prompts that cannot be published.
- `HIRETEST_MARS_JAR` points to a locally obtained MARS installation.
- `HIRETEST_LLI` points to LLVM `lli`.
- `HIRETEST_RUNTIME_LL` optionally overrides the included `src/hiretest/runtime.ll`.
- `HIRETEST_REFERENCE_IDS_*` identifies authorized reference implementations using pseudonymous IDs.
- `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `OPENAI_MODEL` configure the LLM API used for test generation.

Never commit a populated `.env` file.

## Data and privacy

The repository publishes generated test artifacts, not the underlying student dataset. Raw and derived student data, identities, grades, private prompts, model checkpoints, reference implementations, and API credentials must remain outside the public repository.

If a public or controlled-access dataset is deposited on Zenodo, add its stable DOI link here and describe its access conditions. Do not replace this statement with an unverified URL.

## Citation

If you use HiReTest, please cite the corresponding paper and the artifact version used. `CITATION.cff` records the current author, release version, and license. The public repository URL and paper DOI can be added after they are assigned.

## License

HiReTest's original source code and released artifacts are licensed under the MIT License. See `LICENSE`. Third-party tools and dependencies remain subject to their respective licenses.
