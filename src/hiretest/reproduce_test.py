import argparse
import os
from pathlib import Path

try:
    from . import test
    from .paths import artifacts_root, restricted_data_root
except ImportError:  # Support direct execution from src/hiretest.
    import test
    from paths import artifacts_root, restricted_data_root


STAGES = ["1to2", "2to3", "3to4", "4to5", "5to6"]
METHOD = "Hiretest"


def count_files(case_dir):
    cases = list(case_dir.glob("case*.txt"))
    inputs = list(case_dir.glob("input*.txt"))
    return len(cases), len(inputs)


def run_one(case_root, results_root, students_dir, stage, assignment_ids, workers):
    stage_index = STAGES.index(stage)
    case_dir = case_root / METHOD / stage
    if not case_dir.is_dir():
        raise FileNotFoundError(f"Missing test case directory: {case_dir}")

    method_results_root = results_root / METHOD
    result_dir = method_results_root / stage
    analysis_file = method_results_root / f"analysis_{stage}.xlsx"
    result_dir.mkdir(parents=True, exist_ok=True)
    method_results_root.mkdir(parents=True, exist_ok=True)
    assignment_id = assignment_ids[stage_index]

    print(f"\n=== HiReTest / {stage} ===")
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
        description="Evaluate the released HiReTest cases for one or all assignment transitions."
    )
    parser.add_argument(
        "--case-root",
        type=Path,
        default=artifacts_root() / "cases",
        help="Root containing Hiretest/<stage> case directories.",
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
        help="Authorized target-cohort directory. Defaults to HIRETEST_DATA_ROOT.",
    )
    parser.add_argument(
        "--assignment-ids",
        default=os.environ.get("HIRETEST_TARGET_ASSIGNMENT_IDS"),
        help="Comma-separated target assignment IDs in 1to2,...,5to6 order.",
    )
    parser.add_argument(
        "--stage",
        choices=STAGES + ["all"],
        default="all",
        help="Assignment transition to evaluate.",
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
    stages = STAGES if args.stage == "all" else [args.stage]

    if args.dry_run:
        for stage in stages:
            case_dir = case_root / METHOD / stage
            if case_dir.is_dir():
                case_count, input_count = count_files(case_dir)
                print(
                    f"HiReTest/{stage}: cases={case_count}, inputs={input_count}, dir={case_dir}"
                )
            else:
                print(f"HiReTest/{stage}: missing, dir={case_dir}")
        return

    students_dir = args.students_dir
    if students_dir is None:
        students_dir = restricted_data_root()

    if not args.assignment_ids:
        raise RuntimeError(
            "Provide --assignment-ids or set HIRETEST_TARGET_ASSIGNMENT_IDS as described in README.md."
        )
    assignment_ids = [item.strip() for item in args.assignment_ids.split(",") if item.strip()]
    if len(assignment_ids) != len(STAGES):
        raise ValueError("--assignment-ids must contain five IDs in 1to2,...,5to6 order")

    for stage in stages:
        run_one(
            case_root,
            results_root,
            students_dir.resolve(),
            stage,
            assignment_ids,
            args.workers,
        )


if __name__ == "__main__":
    main()
