# HiReTest

HiReTest is a historical repair-guided test-generation method for progressive programming assignments. It mines changes between repaired and inherited code, identifies repair-relevant changes, combines them with assignment constraints, and uses a large language model to generate and review tests. This repository provides the HiReTest implementation and the reusable prompt templates required to run the method on five SysY compiler-assignment transitions.

This is the first stable public release, version `1.0.0`.

## Release scope

This repository contains the implementation of **HiReTest itself**, reusable prompt templates, dependency metadata, and instructions for supplying the original inputs.

The comparison experiments reported in the paper were conducted using the corresponding public implementations and the settings described in the paper. This repository is a HiReTest main-method release, not a complete reproduction package for every comparison experiment in the paper.

## Repository layout

```text
.
├── data/                     # empty placeholder for locally obtained authorized data
├── prompts/public_templates/ # shared generation/review templates and raw constraints
├── requirements/core.txt     # Python dependencies for HiReTest
├── src/hiretest/             # HiReTest implementation and evaluator
├── .env.example              # environment-variable template without real secrets
├── CITATION.cff              # citation metadata
├── LICENSE                   # MIT License
└── pyproject.toml            # Python package metadata
```

## Implementation

The main pipeline is implemented under `src/hiretest/`:

- `compare.py` and `analyse.py` compare adjacent program versions and analyze AST-level changes. Here, “compare” refers to comparing historical program versions, not comparison methods.
- `data_preprocessing.py` converts historical changes and labels into model-ready data.
- `train.py` trains and evaluates the repair-change classifier.
- `export_positive_predictions.py` exports changes predicted to be repair-relevant.
- `get_results.py` extracts source context and constructs history-guided generation prompts.
- `ask_for_llm.py` generates, reviews, and repairs candidate tests through a configured LLM API.
- `test.py` compiles and executes generated tests and produces result workbooks.
- `reproduce_test.py` provides the command-line entry point for evaluating locally generated HiReTest cases.
- `runtime.ll` provides the LLVM-compatible SysY input/output runtime used by backend stages.

The prompt directory contains one shared set of reusable resources for all five
assignment transitions:

```text
prompts/public_templates/
├── prompt.txt
├── check_prompt.txt
└── raw_constraint.txt
```

`prompt.txt` provides the shared generation instructions, `check_prompt.txt` provides the
shared test-review instructions, and `raw_constraint.txt` contains the original constraint
text used by both prompt construction and review.

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

The public repository intentionally leaves `data/` empty. Obtain the original input
dataset from the [HiReTest data record on Zenodo](https://zenodo.org/records/22226749)
(DOI: [`10.5281/zenodo.22226749`](https://doi.org/10.5281/zenodo.22226749)), extract it
outside the repository when possible, and configure the paths before running the full pipeline.
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
`outputs/` under `HIRETEST_DERIVED_DATA_ROOT`. Per-case prompts, generated tests, and
evaluation reports are created only in the user's local workspace. These generated
materials are not part of this source release and must not be committed.

## Evaluating locally generated tests

Evaluation requires locally generated test cases, an authorized input package, and local
MARS and LLVM installations configured through `.env.example`. By default,
`reproduce_test.py` reads checked cases from `artifacts/generated/checked_cases/` and
writes evaluation workbooks under `artifacts/generated/evaluation/`. Both directories
contain local generated outputs and are excluded from version control.

For example, on Windows with an explicit case directory:

```powershell
python -m hiretest.reproduce_test `
  --case-root D:\path\to\generated\cases `
  --stage 1to2 `
  --students-dir D:\path\to\authorized\submissions `
  --assignment-ids assignment2,assignment3,assignment4,assignment5,assignment6
```

The evaluator uses the following environment variables when applicable:

- `HIRETEST_DATA_ROOT` points to authorized submissions outside the repository.
- `HIRETEST_DERIVED_DATA_ROOT` points to a writable workspace for intermediate data, models, and reports.
- `HIRETEST_ASSIGNMENT_SEQUENCE` records the six ordered assignment IDs used by the five-stage pipeline.
- `HIRETEST_TARGET_ASSIGNMENT_IDS` records the five target IDs used when evaluating locally generated tests.
- `HIRETEST_TRANSITION_DIRS` maps the five stages to their generated diff directories.
- `HIRETEST_REPAIR_PROMPT_ROOT` points to authorized history-guided prompts that cannot be published.
- `HIRETEST_MARS_JAR` points to a locally obtained MARS installation.
- `HIRETEST_LLI` points to LLVM `lli`.
- `HIRETEST_RUNTIME_LL` optionally overrides the included `src/hiretest/runtime.ll`.
- `HIRETEST_REFERENCE_IDS_*` identifies authorized reference implementations using pseudonymous IDs.
- `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `OPENAI_MODEL` configure the LLM API used for test generation.

Never commit a populated `.env` file.

## Data and privacy

The repository does not publish generated tests, experimental results, or the underlying student dataset. Raw and derived student data, identities, grades, instantiated prompts, model checkpoints, reference implementations, generated outputs, and API credentials must remain outside the public repository.

The original input dataset is available from the
[HiReTest data record on Zenodo](https://zenodo.org/records/22226749), DOI:
[`10.5281/zenodo.22226749`](https://doi.org/10.5281/zenodo.22226749). Users must follow
the access conditions and license stated in the Zenodo record. Keep downloaded data and
all derived data outside the public source repository.

## Citation

If you use HiReTest, please cite the corresponding paper and the artifact version used. `CITATION.cff` records the current author, release version, and license. The public repository URL and paper DOI can be added after they are assigned.

## License

HiReTest's original source code and reusable prompt templates are licensed under the MIT License. See `LICENSE`. Third-party tools, dependencies, and externally obtained datasets remain subject to their respective licenses and access conditions.
