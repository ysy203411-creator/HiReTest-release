"""Generate the TDOnly SysY baseline from public task descriptions only."""

from __future__ import annotations

import argparse
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

STAGES = ("1to2", "2to3", "3to4", "4to5", "5to6")
BACKEND_STAGES = {"4to5", "5to6"}
DEFAULT_COUNTS = {"1to2": 213, "2to3": 389, "3to4": 93, "4to5": 240, "5to6": 59}


def extract_frontend(response: str) -> str:
    blocks = re.findall(r"```(?:c|sysy)?\s*(.*?)\s*```", response, re.I | re.S)
    return blocks[-1].strip() if blocks else response.strip()


def extract_backend(response: str) -> tuple[str, str]:
    code = re.search(r"<code>\s*(.*?)\s*</code>", response, re.I | re.S)
    stdin = re.search(r"<input>\s*(.*?)\s*</input>", response, re.I | re.S)
    if code:
        return code.group(1).strip(), stdin.group(1).strip() if stdin else ""
    return extract_frontend(response), ""


def generate_one(client, args: argparse.Namespace, prompt: str, case_id: int) -> tuple[int, str, str]:
    response = client.chat.completions.create(
        model=args.model,
        messages=[
            {"role": "system", "content": "You are a compiler testing expert."},
            {"role": "user", "content": prompt},
        ],
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        top_p=1.0,
        timeout=args.timeout,
    )
    text = response.choices[0].message.content or ""
    code, stdin = extract_backend(text) if args.stage in BACKEND_STAGES else (extract_frontend(text), "")
    return case_id, code, stdin


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument("--prompt-file", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4o"))
    parser.add_argument("--temperature", type=float, default=float(os.environ.get("HIRETEST_TEMPERATURE", "0.4")))
    parser.add_argument("--max-tokens", type=int, default=int(os.environ.get("HIRETEST_MAX_TOKENS", "4096")))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("HIRETEST_TIMEOUT", "100")))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    args.count = args.count or DEFAULT_COUNTS[args.stage]
    args.prompt_file = args.prompt_file or root / "prompt" / f"prompt_{args.stage}.txt"
    return args


def main() -> None:
    args = parse_args()
    from openai import OpenAI
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("API_BASE")
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY")
    if not base_url or not api_key:
        raise RuntimeError("Set OPENAI_BASE_URL and OPENAI_API_KEY before generation.")
    prompt = args.prompt_file.read_text(encoding="utf-8").strip()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pending = [
        case_id
        for case_id in range(args.count)
        if args.overwrite or not (args.output_dir / f"case{case_id}.txt").exists()
    ]
    client = OpenAI(base_url=base_url, api_key=api_key)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(generate_one, client, args, prompt, case_id): case_id for case_id in pending}
        for future in as_completed(futures):
            case_id, code, stdin = future.result()
            (args.output_dir / f"case{case_id}.txt").write_text(code, encoding="utf-8")
            if args.stage in BACKEND_STAGES:
                (args.output_dir / f"input{case_id}.txt").write_text(stdin, encoding="utf-8")
            print(f"saved {args.stage}/case{case_id}.txt")


if __name__ == "__main__":
    main()
