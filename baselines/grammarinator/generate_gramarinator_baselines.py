import argparse
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path


STAGE_COUNTS = {
    "1to2": 213,
    "2to3": 389,
    "3to4": 93,
    "4to5": 240,
    "5to6": 59,
}
STAGE_SEED_OFFSETS = {
    "1to2": 1,
    "2to3": 10001,
    "3to4": 20001,
    "4to5": 30001,
    "5to6": 40001,
}
STAGE_GRAMMAR_FILES = {
    "1to2": "SysY_1to2.g4",
    "2to3": "SysY_2to3.g4",
    "3to4": "SysY_3to4.g4",
    "4to5": "SysY_4to5.g4",
    "5to6": "SysY_5to6.g4",
}
BACKEND_STAGES = {"4to5", "5to6"}
METHODS = ("Grammarinator",)
START_RULE = "compUnit"
TOKEN_RE = re.compile(r'"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|==|!=|<=|>=|&&|\|\||.')
KEYWORDS = {
    "const",
    "int",
    "static",
    "void",
    "main",
    "if",
    "else",
    "for",
    "break",
    "continue",
    "return",
    "printf",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def subprocess_env():
    env = os.environ.copy()
    site_dirs = []
    venv = repo_root() / ".venv"
    site_dirs.extend(sorted((venv / "lib").glob("python*/site-packages")))
    site_dirs.append(venv / "Lib" / "site-packages")
    existing = env.get("PYTHONPATH")
    paths = [str(path) for path in site_dirs if path.is_dir()]
    if existing:
        paths.append(existing)
    if paths:
        env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def run(cmd, cwd, *, quiet=False):
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=subprocess_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        if not quiet:
            print(result.stdout)
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(map(str, cmd))}")
    return result.stdout


def resolve_command(name):
    resolved = shutil.which(name)
    if resolved:
        return [resolved]
    user_scripts = Path(sysconfig.get_path("scripts", scheme=f"{os.name}_user"))
    for suffix in (".exe", ".cmd", ".bat", ""):
        local = user_scripts / f"{name}{suffix}"
        if local.is_file():
            return [str(local)]
    scripts = repo_root() / ".venv" / "Scripts"
    for suffix in (".exe", ".cmd", ".bat", ""):
        local = scripts / f"{name}{suffix}"
        if local.is_file():
            return [str(local)]
    local = repo_root() / ".venv" / "bin" / name
    if local.is_file():
        return [sys.executable, str(local)]
    return None


def require_command(name):
    resolved = resolve_command(name)
    if resolved is None:
        raise RuntimeError(
            f"Missing command `{name}`. Install Grammarinator/ANTLR first; see final instructions."
        )
    return resolved


def load_gmutator(gmutator_root: Path):
    script = gmutator_root / "scripts" / "gmutate.py"
    if not script.is_file():
        raise FileNotFoundError(f"Missing Gmutator script: {script}")
    spec = importlib.util.spec_from_file_location("gmutate", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def prepare_dir(path: Path, overwrite: bool):
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"{path} already exists; pass --overwrite to replace it")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_grammar(grammar: Path, dest_dir: Path):
    dest = dest_dir / grammar.name
    if grammar.resolve() != dest.resolve():
        shutil.copy2(grammar, dest)


def process_grammar(grammar: Path, work_dir: Path, process_cmd: str):
    copy_grammar(grammar, work_dir)
    run([*process_cmd, grammar.name], work_dir, quiet=True)


def generate_one(
    work_dir: Path,
    output_file: Path,
    seed: int,
    max_depth: int,
    generate_cmd: str,
    generator_class: str,
) -> bool:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        run(
            [
                *generate_cmd,
                generator_class,
                "-r",
                START_RULE,
                "-o",
                str(output_file),
                "-d",
                str(max_depth),
                "-n",
                "1",
                "--random-seed",
                str(seed),
                "--sys-path",
                ".",
                "-j=1",
            ],
            work_dir,
            quiet=True,
        )
        return output_file.is_file() and output_file.stat().st_size > 0
    except Exception:
        return False


def read_tokens(tokens_file: Path):
    return json.loads(tokens_file.read_text(encoding="utf-8"))


def mutate_string(text: str, tokens, rng: random.Random) -> str:
    token_list = TOKEN_RE.findall(text)

    def replace_integer(ts):
        candidates = [
            i
            for i, token in enumerate(ts)
            if token.isdigit() and (i == 0 or ts[i - 1] not in {"/", "%"})
        ]
        if not candidates:
            return False
        ts[rng.choice(candidates)] = rng.choice(["0", "1", "2", "3", "5", "8", "13", "21"])
        return True

    def rename_identifier(ts):
        identifiers = sorted(
            {
                token
                for token in ts
                if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", token)
                and token not in KEYWORDS
                and not token.startswith("gm_")
            }
        )
        if not identifiers:
            return False
        old = rng.choice(identifiers)
        new = f"gm_{rng.randrange(100000)}"
        for i, token in enumerate(ts):
            if token == old:
                ts[i] = new
        return True

    def insert_main_decl(source):
        match = re.search(r"\bint\s+main\s*\(\s*\)\s*\{", source)
        if not match:
            return source, False
        decl = f"int gm_{rng.randrange(100000)}={rng.randrange(0, 32)};"
        return source[: match.end()] + decl + source[match.end() :], True

    mutators = [replace_integer, rename_identifier]
    applied = False
    for _ in range(rng.randrange(1, 3)):
        applied = rng.choice(mutators)(token_list) or applied

    mutated = "".join(token_list)
    if rng.random() < 0.5:
        mutated, inserted = insert_main_decl(mutated)
        applied = inserted or applied

    if not applied:
        mutated, inserted = insert_main_decl(text)
        if not inserted:
            mutated = text + "\n"
    return mutated


def generate_grammarinator(
    grammar: Path,
    out_dir: Path,
    work_dir: Path,
    count: int,
    max_depth: int,
    process_cmd: str,
    generate_cmd: str,
    max_attempts: int,
    seed_start: int,
    generator_class: str,
):
    process_grammar(grammar, work_dir, process_cmd)
    generated = 0
    seed = seed_start
    attempts = 0
    used = set()
    while generated < count and attempts < max_attempts:
        candidate = work_dir / "_candidate.txt"
        candidate.unlink(missing_ok=True)
        if generate_one(
            work_dir,
            candidate,
            seed,
            max_depth,
            generate_cmd,
            generator_class,
        ):
            content = candidate.read_bytes()
            if content not in used:
                (out_dir / f"case{generated + 1}.txt").write_bytes(content)
                used.add(content)
                generated += 1
        seed += 3
        attempts += 1
    candidate.unlink(missing_ok=True)
    if generated < count:
        raise RuntimeError(f"Only generated {generated}/{count} cases after {attempts} attempts")
    return generated


def case_id(path: Path) -> int:
    match = re.fullmatch(r"case(\d+)\.txt", path.name)
    return int(match.group(1)) if match else sys.maxsize


def duplicate_case_files(out_dir: Path):
    groups = {}
    for path in sorted(out_dir.glob("case*.txt"), key=case_id):
        groups.setdefault(path.read_bytes(), []).append(path)
    return [path for paths in groups.values() for path in paths[1:]]


def replace_grammarinator_duplicates(
    grammar: Path,
    out_dir: Path,
    work_dir: Path,
    max_depth: int,
    process_cmd: str,
    generate_cmd: str,
    max_attempt_factor: int,
    seed_start: int,
    generator_class: str,
):
    if not out_dir.is_dir():
        raise FileNotFoundError(out_dir)

    process_grammar(grammar, work_dir, process_cmd)
    targets = duplicate_case_files(out_dir)
    used = {path.read_bytes() for path in out_dir.glob("case*.txt")}
    candidate = work_dir / "_replacement.txt"
    seed = seed_start
    attempts = 0
    max_attempts = max(len(targets) * max_attempt_factor, len(targets))

    for target in targets:
        while attempts < max_attempts:
            candidate.unlink(missing_ok=True)
            generated = generate_one(
                work_dir,
                candidate,
                seed,
                max_depth,
                generate_cmd,
                generator_class,
            )
            seed += 3
            attempts += 1
            if not generated:
                continue
            content = candidate.read_bytes()
            if content in used:
                continue
            target.write_bytes(content)
            used.add(content)
            break
        else:
            candidate.unlink(missing_ok=True)
            raise RuntimeError(
                f"Only replaced {len(targets) - len(duplicate_case_files(out_dir))}/"
                f"{len(targets)} duplicates after {attempts} attempts"
            )

    candidate.unlink(missing_ok=True)
    return len(targets), attempts


GETINT_RE = re.compile(r"\bgetint\s*\(")


def ensure_backend_inputs(out_dir: Path, count: int):
    for case_id in range(1, count + 1):
        case_file = out_dir / f"case{case_id}.txt"
        input_file = out_dir / f"input{case_id}.txt"
        if not case_file.exists():
            input_file.write_text("", encoding="utf-8")
            continue
        source = case_file.read_text(encoding="utf-8", errors="ignore")
        input_count = len(GETINT_RE.findall(source))
        rng = random.Random(20250600 + case_id)
        values = [str(rng.randint(-10, 20)) for _ in range(input_count)]
        input_file.write_text("\n".join(values) + ("\n" if values else ""), encoding="utf-8")


def generate_gplusm(
    grammar: Path,
    tokens_file: Path,
    out_dir: Path,
    work_dir: Path,
    count: int,
    max_depth: int,
    process_cmd: str,
    generate_cmd: str,
    max_attempts: int,
    seed_start: int,
    generator_class: str,
):
    process_grammar(grammar, work_dir, process_cmd)
    tokens = read_tokens(tokens_file)
    generated = 0
    seed = seed_start
    attempts = 0
    tmp = work_dir / "_raw.in"
    while generated < count and attempts < max_attempts:
        if generate_one(work_dir, tmp, seed, max_depth, generate_cmd, generator_class):
            rng = random.Random(seed)
            text = tmp.read_text(encoding="utf-8", errors="ignore")
            (out_dir / f"case{generated + 1}.txt").write_text(
                mutate_string(text, tokens, rng),
                encoding="utf-8",
            )
            generated += 1
        seed += 3
        attempts += 1
    tmp.unlink(missing_ok=True)
    if generated < count:
        raise RuntimeError(f"Only generated {generated}/{count} cases after {attempts} attempts")
    return generated


def mutate_grammar(gmutate_module, grammar: Path, output_grammar: Path, seed: int):
    rng_state = random.getstate()
    try:
        random.seed(seed)
        mutator = gmutate_module.GrammarMutator(str(grammar))
        mutator.mutate(3)
        output_grammar.write_text(mutator.string, encoding="utf-8")
    finally:
        random.setstate(rng_state)


def generate_gmutator(
    grammar: Path,
    out_dir: Path,
    work_root: Path,
    count: int,
    max_depth: int,
    gmutator_root: Path,
    inputs_per_mutant: int,
    process_cmd: str,
    generate_cmd: str,
    max_attempts: int,
    seed_start: int,
    generator_class: str,
):
    gmutate_module = load_gmutator(gmutator_root)
    generated = 0
    seed = seed_start
    mutant_index = 0
    attempts = 0
    while generated < count and attempts < max_attempts:
        mutant_dir = work_root / f"mutant_{mutant_index}"
        prepare_dir(mutant_dir, overwrite=True)
        mutated = mutant_dir / grammar.name
        mutate_grammar(gmutate_module, grammar, mutated, seed)
        try:
            process_grammar(mutated, mutant_dir, process_cmd)
        except Exception:
            seed += 3
            mutant_index += 1
            continue

        produced_for_mutant = 0
        while generated < count and produced_for_mutant < inputs_per_mutant:
            candidate = out_dir / f"case{generated + 1}.txt"
            if generate_one(mutant_dir, candidate, seed, max_depth, generate_cmd, generator_class):
                generated += 1
                produced_for_mutant += 1
            seed += 3
            attempts += 1
        mutant_index += 1
    if generated < count:
        raise RuntimeError(f"Only generated {generated}/{count} cases after {attempts} attempts")
    return generated


def parse_args():
    root = repo_root()
    parser = argparse.ArgumentParser(
        description="Generate TOSEM-style SysY baselines for HiReTest stages 1to2 through 5to6."
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=list(METHODS) + ["all"],
        default=["Grammarinator"],
        help="Default: Grammarinator. Gmutator/GplusM are kept only for old reproduction.",
    )
    parser.add_argument("--stages", nargs="+", choices=list(STAGE_COUNTS), default=list(STAGE_COUNTS))
    parser.add_argument("--count", type=int, default=None, help="Override per-stage case count.")
    parser.add_argument(
        "--grammar",
        default=None,
        help=(
            "Optional grammar used for every selected stage. By default each stage uses "
            "baselines/grammarinator/stage_grammars/SysY_<stage>.g4."
        ),
    )
    parser.add_argument(
        "--grammar-dir",
        default=str(root / "baselines" / "grammarinator" / "stage_grammars"),
        help="Directory containing the default stage-specific grammar files.",
    )
    parser.add_argument("--tokens", default=str(root / "baselines" / "grammarinator" / "tokens.json"))
    parser.add_argument("--output-root", default=str(root / "artifacts" / "RQ1" / "cases"))
    parser.add_argument("--work-root", default=str(root / "artifacts" / ".work"))
    parser.add_argument(
        "--gmutator-root",
        default=str(root.parent / "gmutator-replication-main"),
        help="Path to the author's gmutator-replication-main checkout.",
    )
    parser.add_argument("--max-depth", type=int, default=18)
    parser.add_argument("--inputs-per-mutant", type=int, default=40)
    parser.add_argument(
        "--max-attempt-factor",
        type=int,
        default=20,
        help="Abort if attempts exceed count multiplied by this factor.",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--replace-duplicates",
        action="store_true",
        help="Keep the first exact copy and regenerate only later duplicate case files.",
    )
    parser.add_argument(
        "--replacement-seed-offset",
        type=int,
        default=1_000_000,
        help="Seed offset used by --replace-duplicates (default: 1000000).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    process_cmd = require_command("grammarinator-process")
    generate_cmd = require_command("grammarinator-generate")

    grammar_override = Path(args.grammar).resolve() if args.grammar else None
    grammar_dir = Path(args.grammar_dir).resolve()
    tokens = Path(args.tokens).resolve()
    output_root = Path(args.output_root).resolve()
    work_root = Path(args.work_root).resolve()
    gmutator_root = Path(args.gmutator_root).resolve()

    if grammar_override is not None and not grammar_override.is_file():
        raise FileNotFoundError(grammar_override)
    if not tokens.is_file():
        raise FileNotFoundError(tokens)
    methods = list(METHODS) if "all" in args.methods else args.methods
    if args.replace_duplicates and methods != ["Grammarinator"]:
        raise ValueError("--replace-duplicates only supports --methods Grammarinator")
    if args.replace_duplicates and args.overwrite:
        raise ValueError("--replace-duplicates cannot be combined with --overwrite")

    for method in methods:
        for stage in args.stages:
            grammar = grammar_override or (grammar_dir / STAGE_GRAMMAR_FILES[stage])
            if not grammar.is_file():
                raise FileNotFoundError(
                    f"Missing stage grammar for {stage}: {grammar}"
                )
            generator_class = f"{grammar.stem}Generator.{grammar.stem}Generator"
            count = args.count or STAGE_COUNTS[stage]
            out_dir = output_root / method / stage
            work_dir = work_root / method / stage
            max_attempts = max(count * args.max_attempt_factor, count)
            seed_start = STAGE_SEED_OFFSETS[stage]
            prepare_dir(work_dir, overwrite=True)

            if args.replace_duplicates:
                print(f"Replacing exact duplicates for {method}/{stage}")
                replaced, attempts = replace_grammarinator_duplicates(
                    grammar,
                    out_dir,
                    work_dir,
                    args.max_depth,
                    process_cmd,
                    generate_cmd,
                    args.max_attempt_factor,
                    seed_start + args.replacement_seed_offset,
                    generator_class,
                )
                if stage in BACKEND_STAGES:
                    ensure_backend_inputs(out_dir, len(list(out_dir.glob("case*.txt"))))
                print(
                    f"Done {method}/{stage}: replaced {replaced} duplicates "
                    f"in {attempts} attempts"
                )
                continue

            prepare_dir(out_dir, overwrite=args.overwrite)

            print(f"Generating {count} cases for {method}/{stage} with {grammar.name}")
            if method == "Grammarinator":
                generated = generate_grammarinator(
                    grammar,
                    out_dir,
                    work_dir,
                    count,
                    args.max_depth,
                    process_cmd,
                    generate_cmd,
                    max_attempts,
                    seed_start,
                    generator_class,
                )
            elif method == "GplusM":
                generated = generate_gplusm(
                    grammar,
                    tokens,
                    out_dir,
                    work_dir,
                    count,
                    args.max_depth,
                    process_cmd,
                    generate_cmd,
                    max_attempts,
                    seed_start,
                    generator_class,
                )
            elif method == "Gmutator":
                generated = generate_gmutator(
                    grammar,
                    out_dir,
                    work_dir,
                    count,
                    args.max_depth,
                    gmutator_root,
                    args.inputs_per_mutant,
                    process_cmd,
                    generate_cmd,
                    max_attempts,
                    seed_start,
                    generator_class,
                )
            else:
                raise AssertionError(method)
            if stage in BACKEND_STAGES:
                ensure_backend_inputs(out_dir, generated)
            print(f"Done {method}/{stage}: {generated} cases -> {out_dir}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
