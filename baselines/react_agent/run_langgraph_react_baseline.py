import argparse
import os
import subprocess
import sys
from pathlib import Path


STAGES = ["1to2", "2to3", "3to4", "4to5", "5to6"]


def main() -> int:
    root = Path(__file__).resolve().parent
    release_root = root.parents[1]
    parser = argparse.ArgumentParser(description="Generate and evaluate LangGraph ReAct baseline cases.")
    parser.add_argument("--stage", choices=STAGES + ["all"], default="all")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-generation", action="store_true")
    parser.add_argument("--stage-count", type=int, default=None)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    env = os.environ.copy()
    if not args.skip_generation:
        subprocess.run([sys.executable, str(root / "generate_langgraph_react_prompts.py"), "--stage", args.stage, "--overwrite"], cwd=root, check=True)
        cmd = [sys.executable, str(root / "langgraph_react_agent_baseline.py"), "--stage", args.stage]
        if args.overwrite:
            cmd.append("--overwrite")
        if args.stage_count is not None:
            cmd += ["--stage-count", str(args.stage_count)]
        subprocess.run(cmd, cwd=root, env=env, check=True)
    eval_cmd = [sys.executable, "-m", "hiretest.reproduce_test", "--rq", "RQ1", "--method", "LangGraphReAct", "--stage", args.stage, "--workers", str(args.workers), "--case-root", str(release_root / "artifacts" / "RQ1" / "cases")]
    subprocess.run(eval_cmd, cwd=root, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
