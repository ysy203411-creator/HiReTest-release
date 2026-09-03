# HiReTest

[中文说明](README.zh-CN.md) | English

HiReTest is a historical repair-guided test-generation method for progressive programming assignments. It mines changes between repaired and inherited code, identifies repair-relevant changes, combines them with assignment constraints, and uses a large language model to generate and review tests. This repository contains the HiReTest implementation, public prompt templates, and the released outputs of the main method on five SysY compiler-assignment transitions.

This is the first stable public release, version `1.0.0`.

## Release scope

The repository releases results produced by **HiReTest itself**. Outputs from comparison methods, ablation studies, and the human evaluation are not included. Small adapters, grammars, configurations, and instructions for the comparison methods are retained only as optional experiment-support material; upstream implementations and model weights are not redistributed.


## Repository layout

```text
.
├── artifacts/                # released HiReTest test cases and result workbooks
├── baselines/                # optional comparison-method adapters and SysY grammars
├── configs/                  # optional comparison-method run metadata
├── docs/                     # comparison-method reproduction notes
├── prompts/public_templates/ # public generation, constraint, and review prompts
├── requirements/             # core and optional dependency lists
├── scripts/                  # artifact-manifest generator
├── src/hiretest/             # HiReTest implementation and evaluator
├── .env.example              # environment-variable template without real secrets
├── CITATION.cff              # citation metadata
├── LICENSE                   # MIT License
└── pyproject.toml            # Python package metadata
```

## Released HiReTest artifacts

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

## HiReTest implementation

The main pipeline is implemented under `src/hiretest/`:

- `compare.py` and `analyse.py` compare adjacent program versions and analyze AST-level changes. Here, “compare” refers to comparing historical program versions, not comparison methods.
- `data_preprocessing.py` converts historical changes and labels into model-ready data.
- `train.py` trains and evaluates the repair-change classifier.
- `export_positive_predictions.py` exports changes predicted to be repair-relevant.
- `get_results.py` extracts source context and constructs history-guided generation prompts.
- `ask_for_llm.py` generates, reviews, and repairs candidate test cases through a configured LLM API.
- `test.py` compiles and executes generated tests and produces result workbooks.
- `reproduce_test.py` provides the command-line entry point for reevaluating released cases.
- `runtime.ll` provides the LLVM-compatible SysY input/output runtime used by backend stages.

The public templates under `prompts/public_templates/` cover generation prompts, processed and raw stage constraints, and test-review prompts for all five transitions.

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

## Inspecting the release

Run a dry check to verify that all released stage directories are visible:

```bash
python -m hiretest.reproduce_test --case-root artifacts/cases --rq RQ1 --method Hiretest --stage all --dry-run
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
  --rq RQ1 `
  --method Hiretest `
  --stage 1to2 `
  --students-dir D:\path\to\authorized\data_2025\data
```

Newly reproduced workbooks are written under `artifacts/reproduced/` by default and do not overwrite the released workbooks.

The evaluator uses the following environment variables when applicable:

- `HIRETEST_DATA_ROOT` and `HIRETEST_DERIVED_DATA_ROOT` point to authorized data outside the repository.
- `HIRETEST_MARS_JAR` points to a locally obtained MARS installation.
- `HIRETEST_LLI` points to LLVM `lli`.
- `HIRETEST_RUNTIME_LL` optionally overrides the included `src/hiretest/runtime.ll`.
- `HIRETEST_REFERENCE_IDS_*` identifies authorized reference implementations using pseudonymous IDs.
- `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `OPENAI_MODEL` configure the LLM API used for test generation.

Never commit a populated `.env` file.

## Optional comparison-method support

No comparison-method outputs are published in `artifacts/`. The following optional support files remain in the repository:

- `baselines/tdonly/`: task-description-only generator wrapper and prompt.
- `baselines/fuzz4all_sysy/`: SysY specifications, Fuzz4All configuration, extraction utility, and validation templates.
- `baselines/grammarinator/`: stage-specific SysY grammars, tokens, and generation wrapper.
- `baselines/react_agent/`: LangGraph ReAct prompt builder, generator, and runner.
- `configs/baselines.json`: recorded comparison-method settings.
- `docs/BASELINE_REPRODUCTION.md`: installation and execution notes for the optional comparison support.

These files do not contain the upstream Fuzz4All, Grammarinator, LangGraph, or model implementations. Third-party software must be obtained separately and remains subject to its own license.

## Data and privacy

The repository publishes generated test artifacts, not the underlying student dataset. 
The dataset is available on Zenodo at the following link:

## Citation

If you use HiReTest, please cite the corresponding paper and the artifact version used. `CITATION.cff` records the current author, release version, and license. The public repository URL and paper DOI can be added after they are assigned.

## License

HiReTest's original source code and released artifacts are licensed under the MIT License. See `LICENSE`. Third-party tools and dependencies remain subject to their respective licenses.
