import argparse
import os
import re
from pathlib import Path


BACKEND_STAGES = {"4to5", "5to6"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def tcase_root() -> Path:
    return repo_root().parent / "HiReTest"


def extract_tag(content: str, tag: str) -> str:
    match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", content, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def extract_code_from_fuzz(content: str) -> str:
    tagged = extract_tag(content, "code")
    if tagged:
        return tagged

    for lang in ("c", "sysy"):
        match = re.search(rf"```{lang}\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

    match = re.search(r"```(?:c|sysy)?\s*(.*)", content, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    return content.strip()


def extract_input_from_fuzz(content: str, code: str) -> str:
    tagged = extract_tag(content, "input")
    if tagged:
        return tagged

    stdin_match = re.search(
        r"(?:stdin|standard input|input)\s*[:：]\s*(?:```)?\s*(.*?)(?:```|\n\s*\n|$)",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if stdin_match:
        return stdin_match.group(1).strip()

    return extract_numbers_from_trailing_comment(code)


def extract_numbers_from_trailing_comment(content: str) -> str:
    content = content.rstrip()
    numbers = []

    multiline_match = re.search(r"/\*([\s\S]*?)\*/\s*$", content)
    if multiline_match:
        comment = multiline_match.group(1)
        for line in comment.splitlines():
            stripped = line.strip()
            if re.fullmatch(r"-?\d+", stripped):
                numbers.append(stripped)
        return "\n".join(numbers)

    comment_lines = []
    for line in reversed(content.splitlines()):
        stripped = line.strip()
        if stripped.startswith("//"):
            comment_lines.insert(0, stripped[2:].strip())
        elif stripped == "":
            continue
        else:
            break

    for line in comment_lines:
        if re.fullmatch(r"-?\d+", line):
            numbers.append(line)
    return "\n".join(numbers)


def process_fuzz_folder(fuzz_folder: Path, output_folder: Path, stage: str, overwrite: bool):
    if not fuzz_folder.is_dir():
        raise NotADirectoryError(f".fuzz folder does not exist: {fuzz_folder}")

    output_folder.mkdir(parents=True, exist_ok=True)
    dual_output = stage in BACKEND_STAGES

    print(f"input:  {fuzz_folder}")
    print(f"output: {output_folder}")
    print(f"stage:  {stage} (dual_output={dual_output})")

    processed_count = 0
    for fuzz_path in sorted(fuzz_folder.glob("*.fuzz"), key=lambda path: int(path.stem) if path.stem.isdigit() else 10**12):
        if not fuzz_path.stem.isdigit():
            continue
        case_id = int(fuzz_path.stem)
        case_path = output_folder / f"case{case_id}.txt"
        input_path = output_folder / f"input{case_id}.txt"
        if case_path.exists() and not overwrite:
            continue

        content = fuzz_path.read_text(encoding="utf-8", errors="ignore")
        code = extract_code_from_fuzz(content)
        stdin = extract_input_from_fuzz(content, code) if dual_output else ""

        case_path.write_text(code, encoding="utf-8")
        if dual_output:
            input_path.write_text(stdin, encoding="utf-8")
        processed_count += 1

    print(f"processed cases: {processed_count}")


def parse_args():
    parser = argparse.ArgumentParser(description="Extract SysY case/input files from Fuzz4All .fuzz outputs.")
    parser.add_argument(
        "--fuzz-folder",
        default=str(repo_root() / "outputs" / "sysy_run"),
        help="Directory containing numeric .fuzz files.",
    )
    parser.add_argument(
        "--stage",
        choices=["1to2", "2to3", "3to4", "4to5", "5to6"],
        required=True,
        help="Target assignment transition. 4to5 and 5to6 also emit inputN.txt.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory. Defaults to ../HiReTest/output/RQ1/Fuzz4All/<stage>.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing case/input files.")
    return parser.parse_args()


def main():
    args = parse_args()
    output = Path(args.output) if args.output else tcase_root() / "output" / "RQ1" / "Fuzz4All" / args.stage
    process_fuzz_folder(Path(args.fuzz_folder), output, args.stage, args.overwrite)


if __name__ == "__main__":
    main()
