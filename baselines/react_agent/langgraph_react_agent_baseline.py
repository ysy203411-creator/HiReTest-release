import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

STAGES = ["1to2", "2to3", "3to4", "4to5", "5to6"]
BACKEND_STAGES = {"4to5", "5to6"}
RELEASE_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = RELEASE_ROOT / "src" / "hiretest"
MODEL = os.environ.get("OPENAI_MODEL") or os.environ.get("MODEL_NAME", "gpt-4o")
BASE_URL = os.environ.get("OPENAI_BASE_URL") or os.environ.get("API_BASE", "")
API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY", "")
TEMPERATURE = float(os.environ.get("HIRETEST_TEMPERATURE", "0.4"))
MAX_TOKENS = int(os.environ.get("HIRETEST_MAX_TOKENS", "4096"))
TIMEOUT = int(os.environ.get("HIRETEST_TIMEOUT", "100"))


def extract_code(text: str) -> str:
    blocks = re.findall(r"```(?:c|sysy)?\s*\n?(.*?)\s*```", text, re.I | re.S)
    if blocks:
        return blocks[-1].strip()
    match = re.search(r"<code>\s*(.*?)\s*</code>", text, re.I | re.S)
    return match.group(1).strip() if match else text.strip()


def extract_backend(text: str) -> tuple[str, str]:
    code_match = re.search(r"<code>\s*(.*?)\s*</code>", text, re.I | re.S)
    input_match = re.search(r"<input>\s*(.*?)\s*</input>", text, re.I | re.S)
    if code_match:
        return code_match.group(1).strip(), (input_match.group(1).strip() if input_match else "")
    return extract_code(text), ""


def valid_source(code: str) -> bool:
    return bool(code and re.search(r"\bint\s+main\s*\(", code) and "{" in code and "}" in code)


def make_checker(stage: str, check_prompt_root: Path):
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI

    template = (check_prompt_root / f"check_prompt_{stage}.txt").read_text(encoding="utf-8").strip()
    constraint = (check_prompt_root / f"constraint_{stage}.txt").read_text(encoding="utf-8").strip()
    reviewer_prompt = template.replace("{constraint}", constraint)
    client = ChatOpenAI(
        model=MODEL,
        api_key=API_KEY,
        base_url=BASE_URL or None,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        timeout=TIMEOUT,
    )

    @tool
    def review_test_case(test_case: str, standard_input: str = "") -> str:
        """Review one candidate against the public stage constraints and report actionable feedback."""
        prompt = (
            f"{reviewer_prompt}\n\n# Test case\n{test_case}\n"
            f"# Standard input\n{standard_input}\n\n"
            "Use the required format. If non-compliant, explain only constraint violations "
            "and provide a corrected candidate when possible. Do not use hidden or historical information."
        )
        response = client.invoke([HumanMessage(content=prompt)])
        return str(response.content)

    return review_test_case


def make_agent(stage: str, check_prompt_root: Path):
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    model = ChatOpenAI(
        model=MODEL,
        api_key=API_KEY,
        base_url=BASE_URL or None,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        timeout=TIMEOUT,
    )
    checker = make_checker(stage, check_prompt_root)
    return create_react_agent(
        model,
        tools=[checker],
        prompt=(
            "You are the only autonomous test-generation agent. Use the review_test_case tool "
            "when you need constraint feedback. Generate one candidate, review it, and revise it "
            "when needed. Do not call the tool more than three times. Never use historical code, "
            "patches, diffs, hidden tests, or compiler reproduction feedback. Your final response "
            "must contain only the requested test format."
        ),
    )


def final_message(result: dict[str, Any]) -> str:
    messages = result.get("messages", [])
    for message in reversed(messages):
        if getattr(message, "type", "") == "ai" and getattr(message, "content", ""):
            return str(message.content)
    return ""


def run_case(agent, stage: str, prompt_path: Path, output_path: Path, raw_path: Path, trace_path: Path, max_steps: int) -> None:
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    started = time.time()
    trace: dict[str, Any] = {"stage": stage, "case_id": int(prompt_path.stem[4:]), "tool_calls": 0}
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": prompt}]},
            config={"recursion_limit": max_steps * 2 + 2},
        )
        raw = final_message(result)
        trace["tool_calls"] = sum(
            len(getattr(message, "tool_calls", []) or [])
            for message in result.get("messages", [])
        )
        code, stdin = extract_backend(raw) if stage in BACKEND_STAGES else (extract_code(raw), "")
        if not valid_source(code):
            raise ValueError("ReAct final response did not contain a valid SysY source program")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(code, encoding="utf-8")
        raw_path.write_text(raw, encoding="utf-8")
        if stage in BACKEND_STAGES:
            output_path.with_name(f"input{prompt_path.stem[4:]}.txt").write_text(stdin, encoding="utf-8")
        trace.update({"status": "ok", "elapsed_seconds": time.time() - started, "raw_length": len(raw)})
    except Exception as exc:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(f"/* ERROR: {exc} */\n", encoding="utf-8")
        trace.update({"status": "error", "error": repr(exc), "elapsed_seconds": time.time() - started})
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(trace, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the LangGraph standard ReAct AgentBaseline.")
    parser.add_argument("--stage", choices=STAGES + ["all"], default="all")
    parser.add_argument("--prompt-root", default=str(RELEASE_ROOT / "prompts" / "react_agent"))
    parser.add_argument("--check-prompt-root", default=str(RELEASE_ROOT / "prompts" / "public_templates"))
    parser.add_argument("--raw-root", default=str(RELEASE_ROOT / "artifacts" / "RQ1" / "development_traces" / "LangGraphReAct_raw"))
    parser.add_argument("--output-root", default=str(RELEASE_ROOT / "artifacts" / "RQ1" / "cases" / "LangGraphReAct"))
    parser.add_argument("--trace-root", default=str(RELEASE_ROOT / "artifacts" / "RQ1" / "development_traces" / "LangGraphReAct_trace"))
    parser.add_argument("--max-steps", type=int, default=3)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--stage-count", type=int, default=None)
    args = parser.parse_args()
    if not API_KEY or not BASE_URL:
        raise RuntimeError("Set OPENAI_API_KEY/API_KEY and OPENAI_BASE_URL/API_BASE before running.")

    stages = STAGES if args.stage == "all" else [args.stage]
    for stage in stages:
        prompt_dir = Path(args.prompt_root) / stage
        if not prompt_dir.is_dir():
            raise FileNotFoundError(f"Missing prompt directory: {prompt_dir}. Run generate_langgraph_react_prompts.py first.")
        prompt_files = sorted(prompt_dir.glob("case*.txt"), key=lambda p: int(p.stem[4:]))
        if args.stage_count is not None:
            prompt_files = prompt_files[: args.stage_count]
        agent = make_agent(stage, Path(args.check_prompt_root))
        trace_path = Path(args.trace_root) / stage / "trace.jsonl"
        if args.overwrite and trace_path.exists():
            trace_path.unlink()
        for prompt_path in prompt_files:
            case_id = prompt_path.stem[4:]
            output_path = Path(args.output_root) / stage / f"case{case_id}.txt"
            raw_path = Path(args.raw_root) / stage / f"case{case_id}_raw.txt"
            if output_path.exists() and not args.overwrite:
                continue
            run_case(agent, stage, prompt_path, output_path, raw_path, trace_path, args.max_steps)
        print(f"{stage}: cases={len(prompt_files)}, intent_planning=disabled, output={Path(args.output_root) / stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
