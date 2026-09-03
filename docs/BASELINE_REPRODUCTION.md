# Comparison-method reproduction

## Release policy

This artifact does not redistribute the source code of TDOnly, Fuzz4All, Grammarinator, or
LangGraph. A reproducer installs each upstream implementation separately and uses the small
HiReTest-side wrapper/configuration in this repository. This preserves upstream ownership and
licenses while making our SysY inputs, budget, conversion, validation, and evaluation auditable.


## Common contract

The five stages are `1to2`, `2to3`, `3to4`, `4to5`, and `5to6`, with budgets 213, 389, 93, 240,
and 59. Stages `4to5` and `5to6` require a paired `inputN.txt` for every `caseN.txt`. All methods
are evaluated through the same HiReTest evaluator and result schema. See `configs/baselines.json`.

## TDOnly

TDOnly is the task-description-only baseline adapted from the local ICSE-D15F snapshot for
*Measuring the Influence of Incorrect Code on Test Generation*. 

The release wrapper is `baselines/tdonly/generate.py`. It uses model `gpt-4o`, temperature 0.4,
`top_p=1.0`, maximum 4096 tokens, 100-second request timeout, and eight workers. The provider did
not expose a deterministic seed; report that limitation.

```powershell
python baselines/tdonly/generate.py --stage 1to2 --output-dir <RUN_DIR>/TDOnly/1to2
```

## Fuzz4All

Upstream: [https://github.com/fuzz4all/fuzz4all](https://github.com/fuzz4all/fuzz4all). Use the formal-run commit in an external
checkout, then `baselines/fuzz4all_sysy/sysy.yaml` and the stage-specific public SysY input. The
recorded settings are StarCoderBase, CUDA, batch size 4, maximum length 4096, one-hour fuzzing,
and 30-second oracle timeout. Record the exact Fuzz4All commit and model revision/checksum.

```powershell
python <FUZZ4ALL_CHECKOUT>/Fuzz4All/fuzz.py --config <RELEASE>/baselines/fuzz4all_sysy/sysy.yaml main_with_config --folder <RUN_DIR>
python baselines/fuzz4all_sysy/extract_sysy_cases.py --help
```


## Grammarinator

Upstream: [https://github.com/renatahodovan/grammarinator](https://github.com/renatahodovan/grammarinator). Install the pinned package from
`requirements/grammarinator.txt`; this repository contains only our SysY grammars and
orchestration. Stage seed starts are 1, 10001, 20001, 30001, and 40001, incrementing by three per
attempt. Freeze the formal-run package version and maximum depth before publication.

```powershell
python -m pip install -r requirements/grammarinator.txt
python -m hiretest.generate_tosem_baselines --help
```

## ReActAgent

Framework upstream: [https://github.com/langchain-ai/langgraph](https://github.com/langchain-ai/langgraph); dependencies are in
`requirements/react-agent.txt`. ReActAgent receives only the public constraint prompt, may call
the constraint-review tool at most three times, and receives no student code, repair history,
hidden test, or compiler feedback. Prompts are generated at run time from
`prompts/public_templates/`; the generated prompt corpus is not distributed.

```powershell
python -m pip install -r requirements/react-agent.txt
python -m hiretest.generate_langgraph_react_prompts --stage 1to2 --output-root <RUN_DIR>/prompts/ReActAgent --overwrite
python -m hiretest.langgraph_react_agent_baseline --stage 1to2 --prompt-root <RUN_DIR>/prompts/ReActAgent --output-root <RUN_DIR>/cases/LangGraphReAct
```

Formal settings are model `gpt-4o`, temperature 0.4, maximum 4096 tokens, 100-second timeout,
and at most three tool calls. 

## Verification without data

```powershell
python -m hiretest.reproduce_test --case-root artifacts/cases --rq RQ1 --method Hiretest --stage all --dry-run
```
