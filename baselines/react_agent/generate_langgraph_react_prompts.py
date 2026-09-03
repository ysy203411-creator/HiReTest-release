import argparse
from pathlib import Path


STAGES = ["1to2", "2to3", "3to4", "4to5", "5to6"]
STAGE_COUNTS = {"1to2": 213, "2to3": 389, "3to4": 93, "4to5": 240, "5to6": 59}
BACKEND_STAGES = {"4to5", "5to6"}


def build_prompt(stage: str, constraint: str) -> str:
    if stage in BACKEND_STAGES:
        output = """Return exactly two sections:
<code>
one SysY test program
</code>
<input>
complete standard input, or empty if the program does not call getint
</input>"""
        goal = "Generate a legal executable program with deterministic output and complete input."
    else:
        output = """Return exactly one Markdown C code block containing one SysY test program.
Do not return explanations or any text outside the code block."""
        goal = (
            "Generate one test program that covers a publicly specified legal behavior or "
            "a publicly specified error category. Choose the target yourself from the "
            "stage constraints; do not use historical repair information."
        )

    return f"""You are a compiler test-generation agent.

The only task-specific information available to you is the public specification below.
Do not use historical student programs, patches, diffs, repair locations, repair semantics,
hidden tests, or feedback from compiler reproduction.

Stage: {stage}
{goal}
Produce a self-contained SysY test case. Keep all non-target parts legal and avoid undefined
behavior. You may use the public error categories listed in the specification, but do not
assume that any particular student implementation has a particular bug.

Public stage constraints:
{constraint}

{output}
"""


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Generate non-intent LangGraph ReAct prompts.")
    parser.add_argument("--stage", choices=STAGES + ["all"], default="all")
    parser.add_argument("--prompt-dir", default=str(root / "prompts" / "public_templates"))
    parser.add_argument("--output-root", default=str(root / "prompts" / "react_agent"))
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    prompt_dir = Path(args.prompt_dir).resolve()
    output_root = Path(args.output_root).resolve()
    stages = STAGES if args.stage == "all" else [args.stage]
    for stage in stages:
        count = args.count if args.count is not None else STAGE_COUNTS[stage]
        constraint_path = prompt_dir / f"constraint_{stage}.txt"
        constraint = constraint_path.read_text(encoding="utf-8").strip()
        stage_dir = output_root / stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        prompt = build_prompt(stage, constraint)
        for case_id in range(1, count + 1):
            path = stage_dir / f"case{case_id}.txt"
            if args.overwrite or not path.exists():
                path.write_text(prompt, encoding="utf-8")
        print(f"{stage}: prompts={count}, intent_planning=disabled, output={stage_dir}")


if __name__ == "__main__":
    main()
