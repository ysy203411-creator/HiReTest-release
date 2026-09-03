import argparse
from pathlib import Path

try:
    from . import test
    from .paths import artifacts_root, restricted_data_root, tool_path
except ImportError:  # Support direct execution from src/hiretest.
    import test
    from paths import artifacts_root, restricted_data_root, tool_path


STAGES = ["1to2", "2to3", "3to4", "4to5", "5to6"]
HOMEWORK_IDS = ["1852", "1854", "1856", "1858", "1859", "1860"]
OUTPUT_GROUPS = {
    "RQ1": [
        "Fuzz4All",
        "Hiretest",
        "TDonly",
        "Grammarinator",
        "LangGraphReAct",
    ],
    "RQ2": ["wo_test_review", "wo_constraints", "wo_repairs"]
    
}
METHODS = sorted({method for methods in OUTPUT_GROUPS.values() for method in methods})


def count_files(case_dir):
    cases = list(case_dir.glob("case*.txt"))
    inputs = list(case_dir.glob("input*.txt"))
    return len(cases), len(inputs)


def run_one(case_root, results_root, students_dir, rq, method, stage, workers):
    stage_index = STAGES.index(stage)
    case_dir = case_root / method / stage
    if not case_dir.is_dir():
        raise FileNotFoundError(f"Missing test case directory: {case_dir}")

    method_results_root = results_root / rq / method
    result_dir = method_results_root / stage
    analysis_file = method_results_root / f"analysis_{stage}.xlsx"
    result_dir.mkdir(parents=True, exist_ok=True)
    method_results_root.mkdir(parents=True, exist_ok=True)
    assignment_id = HOMEWORK_IDS[stage_index]

    test.MARS_JAR_PATH = str(tool_path("HIRETEST_MARS_JAR", "MARS.jar"))
    test.LLI_PATH = str(tool_path("HIRETEST_LLI", "llvm-12.0.0/bin/lli"))
    test.RUNTIME_PATH = str(tool_path("HIRETEST_RUNTIME_LL", "runtime.ll"))

    print(f"\n=== {rq} / {method} / {stage} ===")
    print(f"students_dir: {students_dir}")
    print(f"test_cases_dir: {case_dir}")
    print(f"analysis_file: {analysis_file}")

    if stage_index < 3:
        test.test_student_compilers(
            str(students_dir),
            str(case_dir),
            str(result_dir),
            stage_index,
            assignment_id,
            str(analysis_file),
            max_workers=workers,
        )
    else:
        test.test_student_compilers_for_compiler(
            str(students_dir),
            str(case_dir),
            str(result_dir),
            stage_index,
            assignment_id,
            str(analysis_file),
            max_workers=workers,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Run test.py against artifacts/RQ1/cases/{method}/{stage} test cases."
    )
    parser.add_argument(
        "--rq",
        choices=list(OUTPUT_GROUPS) + ["all"],
        default="RQ1",
        help="Which output group to evaluate.",
    )
    parser.add_argument(
        "--case-root",
        type=Path,
        default=artifacts_root() / "RQ1" / "cases",
        help="Root containing <method>/<stage> case directories.",
    )
    parser.add_argument(
        "--results-root",
        type=Path,
        default=artifacts_root() / "reproduced",
        help="Writable root for newly reproduced result workbooks.",
    )
    parser.add_argument(
        "--students-dir",
        type=Path,
        default=None,
        help="Authorized target-cohort submission directory. Defaults to HIRETEST_DATA_ROOT/data_2025/data.",
    )
    parser.add_argument(
        "--method",
        choices=METHODS + ["all"],
        default="Hiretest",
        help="Which generated test-case set to evaluate.",
    )
    parser.add_argument(
        "--stage",
        choices=STAGES + ["all"],
        default="all",
        help="Which assignment transition to evaluate.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Process workers passed to test.py.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print detected case/input counts.",
    )
    args = parser.parse_args()

    case_root = args.case_root.resolve()
    results_root = args.results_root.resolve()
    rqs = list(OUTPUT_GROUPS) if args.rq == "all" else [args.rq]
    stages = STAGES if args.stage == "all" else [args.stage]

    if args.dry_run:
        for rq in rqs:
            methods = OUTPUT_GROUPS[rq] if args.method == "all" else [args.method]
            for method in methods:
                if method not in OUTPUT_GROUPS[rq]:
                    print(f"{rq}/{method}: skipped, method is not configured for {rq}")
                    continue
                for stage in stages:
                    case_dir = case_root / method / stage
                    if case_dir.is_dir():
                        case_count, input_count = count_files(case_dir)
                        print(
                            f"{rq}/{method}/{stage}: cases={case_count}, inputs={input_count}, dir={case_dir}"
                        )
                    else:
                        print(f"{rq}/{method}/{stage}: missing, dir={case_dir}")
        return

    for rq in rqs:
        methods = OUTPUT_GROUPS[rq] if args.method == "all" else [args.method]
        for method in methods:
            if method not in OUTPUT_GROUPS[rq]:
                print(f"{rq}/{method}: skipped, method is not configured for {rq}")
                continue
            for stage in stages:
                students_dir = args.students_dir
                if students_dir is None:
                    students_dir = restricted_data_root() / "data_2025" / "data"
                run_one(case_root, results_root, students_dir.resolve(), rq, method, stage, args.workers)


if __name__ == "__main__":
    main()
