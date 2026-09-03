import os
import re
import shutil
import subprocess
import json
import concurrent.futures
from collections import defaultdict
import pandas as pd
import time
import sys
import signal
from pathlib import Path

index = 1
offset = 0


def _csv_env(name):
    return [value.strip() for value in os.environ.get(name, "").split(",") if value.strip()]


MARS_JAR_PATH = os.environ.get("HIRETEST_MARS_JAR", "")
LLI_PATH = os.environ.get("HIRETEST_LLI", "")
RUNTIME_PATH = os.environ.get("HIRETEST_RUNTIME_LL", str(Path(__file__).with_name("runtime.ll")))
STANDARD_STUDENT_IDS = _csv_env("HIRETEST_REFERENCE_IDS_FRONTEND")
STANDARD_STUDENT_IDS_4 = _csv_env("HIRETEST_REFERENCE_IDS_STAGE4")
STANDARD_STUDENT_IDS_5 = _csv_env("HIRETEST_REFERENCE_IDS_STAGE5")

def remove_folder(path):
    if os.path.exists(path):
        if os.path.isfile(path) or os.path.islink(path):
            os.remove(path)
        else:
            for filename in os.listdir(path):
                remove_folder(os.path.join(path, filename))
            os.rmdir(path)

def kill_process_tree(pid):
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass

def run_with_timeout(cmd, *, cwd=None, stdin=None, timeout=None, check=False, capture_output=False, text=False):
    stdout = subprocess.PIPE if capture_output else None
    stderr = subprocess.PIPE if capture_output else None
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["preexec_fn"] = os.setsid
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        text=text,
        **kwargs,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        kill_process_tree(proc.pid)
        try:
            out, err = proc.communicate(timeout=1)
        except Exception:
            out, err = exc.output, exc.stderr
        raise subprocess.TimeoutExpired(cmd, timeout, output=out, stderr=err)
    result = subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=out, stderr=err)
    return result

def test_standard_students(student_ids, students_dir, assignment_id, test_cases_dir, test_cases, index):
    all_fingerprints = {}
    
    case_still_valid = {case: True for case in test_cases}
    
    for student_id in student_ids:
        student_path = os.path.join(students_dir, student_id)
        if not os.path.isdir(student_path):
            continue
        student_assignment_path = os.path.join(student_path, assignment_id)
        if not os.path.exists(student_assignment_path):
            continue
        target_dir = os.path.join(student_assignment_path, 'last')
        
        # 🔧 只处理尚未被标记为无效的测试用例
        active_cases = [case for case in test_cases if case_still_valid[case]]
        if not active_cases:
            # 所有用例都已失效，提前结束
            continue
            
        try:
            fingerprints = test_single_student(index, target_dir, test_cases_dir, active_cases)
            all_fingerprints[student_id] = fingerprints
            i = 0
            # 🔧 关键：检查当前学生的运行结果，标记失败的用例为无效
            for case in active_cases:
                fp = fingerprints.get(case, None)
                if fp is None:
                    i += 1
                    case_still_valid[case] = False  # 该用例在此学生处失败，后续学生不再处理
            # print(f"student:{student_id},total:{len(active_cases)},bad:{i}")
        except Exception as e:
            all_fingerprints[student_id] = {}
            # 🔧 如果整个学生执行异常，标记所有活跃用例为无效
            for case in active_cases:
                case_still_valid[case] = False
    
    if len(all_fingerprints) == 0:
        return [], {}
    
    valid_cases = []
    common_fingerprints = {}
    
    for case in test_cases:
        # 🔧 跳过已被标记为无效的用例
        if not case_still_valid[case]:
            continue
            
        fingerprints_for_case = []
        for student_id in student_ids:
            if student_id in all_fingerprints:
                fp = all_fingerprints[student_id].get(case, None)
                fingerprints_for_case.append(fp)
            else:
                fingerprints_for_case.append(None)
        
        if all(fp is not None for fp in fingerprints_for_case) and \
           len(set(fingerprints_for_case)) == 1:
            valid_cases.append(case)
            common_fingerprints[case] = fingerprints_for_case[0]
    if len(valid_cases) < 10:
        print(valid_cases)
    return valid_cases, common_fingerprints

def test_standard_students_for_compiler(student_ids, students_dir, assignment_id, 
                                        test_cases_dir, test_cases):
    all_outputs = {}
    case_still_valid = {case: True for case in test_cases}
    
    for student_id in student_ids:
        student_path = os.path.join(students_dir, student_id)
        if not os.path.isdir(student_path):
            continue
        student_assignment_path = os.path.join(student_path, assignment_id)
        if not os.path.exists(student_assignment_path):
            continue
        has_last = os.path.exists(os.path.join(student_assignment_path, 'last_100.0.txt'))
        has_root_last = os.path.exists(os.path.join(student_assignment_path, '100.0.txt'))
        has_first = os.path.exists(os.path.join(student_assignment_path, 'first_100.0.txt'))
        if has_last or has_root_last:
            target_dir = os.path.join(student_assignment_path, 'last')
        elif has_first:
            target_dir = os.path.join(student_assignment_path, 'first')
        else:
            continue
        if not os.path.exists(os.path.join(target_dir, 'Compiler.java')):
            continue

        active_cases = [case for case in test_cases if case_still_valid[case]]
        if not active_cases:

            continue
            
        try:
            print(f"standard student {student_id}: running {len(active_cases)} active cases")
            sys.stdout.flush()
            case_files = [f"case{case[4:-4]}.txt" for case in active_cases]
            outputs = test_single_student_for_comilper(student_id, target_dir, test_cases_dir, case_files)
            all_outputs[student_id] = outputs
            i = 0
            for case in active_cases:
                case_id = case[4:-4]
                out = outputs.get(case_id, None)
                if out is None:
                    i += 1
                    case_still_valid[case] = False  # 该用例在此学生处失败，后续学生不再处理
            # print(f"student:{student_id},total:{len(active_cases)},bad:{i}")
            print(f"standard student {student_id}: invalidated {i}/{len(active_cases)} cases")
            sys.stdout.flush()
        except Exception as e:
            all_outputs[student_id] = {}
            for case in active_cases:
                case_still_valid[case] = False
            print(f"standard student {student_id}: failed, invalidated {len(active_cases)} cases")
            sys.stdout.flush()
    
    if len(all_outputs) == 0:
        return [], {}
    
    valid_case_ids = []
    common_outputs = {}
    
    for case in test_cases:

        if not case_still_valid[case]:
            continue
            
        case_id = case[4:-4]
        outputs_for_case = []
        for student_id in student_ids:
            if student_id in all_outputs:
                out = all_outputs[student_id].get(case_id, None)
                outputs_for_case.append(out)
            else:
                outputs_for_case.append(None)
        
        if any(out is None for out in outputs_for_case):
            continue
        normalized_outputs = [out.strip() if isinstance(out, str) else out for out in outputs_for_case]
        if len(set(normalized_outputs)) == 1:
            valid_case_ids.append(case_id)
            common_outputs[case_id] = outputs_for_case[0]
    
    return valid_case_ids, common_outputs

def test_student_compilers(students_dir, test_cases_dir, output_dir, index, assignment_id, 
                          analyse_result_file, max_workers=None):
    test_cases = [
        f for f in os.listdir(test_cases_dir)
        if f.startswith('case') and f.endswith('.txt') and f[4:-4].isdigit() and (int(f[4:-4]) >= 0)
    ]
    original_count = len(test_cases)
    remove_folder(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    all_students = []
    for student in os.listdir(students_dir):
        student_path = os.path.join(students_dir, student)
        if not os.path.isdir(student_path):
            continue
        student_assignment_path = os.path.join(student_path, assignment_id)
        if not os.path.exists(student_assignment_path):
            continue
        has_last = os.path.exists(os.path.join(student_assignment_path, 'last_100.0.txt'))
        has_root_last = os.path.exists(os.path.join(student_assignment_path, '100.0.txt'))
        has_first = os.path.exists(os.path.join(student_assignment_path, 'first_100.0.txt'))
        if has_last or has_root_last:
            target_dir = os.path.join(student_assignment_path, 'last')
        elif has_first:
            target_dir = os.path.join(student_assignment_path, 'first')
        else:
            continue
        if not os.path.exists(os.path.join(target_dir, 'Compiler.java')):
            continue
        all_students.append((student, target_dir))

    if not all_students:
        return
    print("正在运行标准程序... ")
    valid_cases, std_fingerprints = test_standard_students(
        STANDARD_STUDENT_IDS, students_dir, assignment_id, test_cases_dir, test_cases, index
    )
    print(f"标准程序验证完成。")
    if not valid_cases:
        print("无有效的测试用例")
        return
    
    test_cases = valid_cases

    case_student_fingerprints = defaultdict(dict)
    sys.stdout.flush()

    completed = 0
    total = len(all_students)
    start_time = time.time()

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(test_single_student, index, target_dir, test_cases_dir, test_cases): student 
            for student, target_dir in all_students
        }

        for future in concurrent.futures.as_completed(futures):
            student = futures[future]
            try:
                fingerprints = future.result()
                for case, fp in fingerprints.items():
                    case_student_fingerprints[case][student] = fp
            except Exception as e:
                print(f"\n学生 {student} 测试异常：{e}")
                sys.stdout.flush()
                for case in test_cases:
                    case_student_fingerprints[case][student] = None

            completed += 1
            percent = (completed / total) * 100
            elapsed = time.time() - start_time
            sys.stdout.write(f"\r测试进度: {completed}/{total} ({percent:.1f}%) | 已用时: {elapsed:.1f}s")
            sys.stdout.flush()
            
    print() 

    students = [s for s, _ in all_students]
    test_cases_sorted = sorted(test_cases, key=lambda x: int(x[4:-4]))
    initial_case_count = original_count
    version_map = defaultdict(dict)
    for case in test_cases_sorted:
        std_fp = std_fingerprints.get(case, None)
        fingerprint_to_version = {}
        current_version = 2 
        
        fingerprint_to_version[std_fp] = 1
        version_map[case][STANDARD_STUDENT_IDS[0]] = 1

        for student in students:
            if student in STANDARD_STUDENT_IDS:
                version_map[case][student] = 1
                continue
            
            fp = case_student_fingerprints[case].get(student, None)
            if fp is None:
                version_map[case][student] = 0
                continue

            if fp not in fingerprint_to_version:
                fingerprint_to_version[fp] = current_version
                current_version += 1
            
            version_map[case][student] = fingerprint_to_version[fp]
    filtered_cases = []
    for case in test_cases_sorted:
        total_students = len(students)
        if total_students == 0:
            continue
        match_count = sum(1 for s in students if version_map[case].get(s) == 1)
        pass_rate = match_count / total_students
        unique_versions = len(set(version_map[case].get(s) for s in students))
        # if index == 0 or ( index != 0 and unique_versions <= 12 and pass_rate >= 0.85):
        filtered_cases.append(case)
    final_case_count = len(filtered_cases)
    case_efficiency = (final_case_count / initial_case_count * 100) if initial_case_count > 0 else 0.0
    print(f"测试用例统计: 初始={initial_case_count}, 最终={final_case_count}, 有效率={case_efficiency:.2f}%")
   
    test_cases_sorted = filtered_cases

    data_rows = []
    case_cols = test_cases_sorted  
    
    for student in students:
        row = {'学生': student}
        for case in case_cols:
            row[case] = version_map[case].get(student, 0)
        data_rows.append(row)

    df = pd.DataFrame(data_rows, columns=['学生'] + case_cols)

    with pd.ExcelWriter(analyse_result_file) as writer:
        df.to_excel(writer, index=False, sheet_name='版本报告')

    student_pass_rates = {}
    for student in students:
        pass_count = sum(1 for c in test_cases_sorted if version_map[c].get(student) == 1)
        student_pass_rates[student] = pass_count / len(test_cases_sorted) if test_cases_sorted else 0
    
    # 统计各区间人数
    ranges = [(1.0, "100%"), (0.9, "90-100%"), (0.8, "80-90%"), (0.7, "70-80%"), (0.0, "<70%")]
    counts = {label: 0 for _, label in ranges}
    for student, rate in student_pass_rates.items():
        for threshold, label in ranges:
            if rate >= threshold:
                counts[label] += 1
                break

    total_valid = sum(counts.values())
    output_parts = []
    for _, label in ranges:
        count = counts[label]
        pct = (count / total_valid * 100) if total_valid > 0 else 0.0
        output_parts.append(f"{label}={count} ({pct:.2f}%)")

    print(f"学生通过率分布: {', '.join(output_parts)}")
    print(f"结果保存到{analyse_result_file}")

def test_student_compilers_for_compiler(students_dir, test_cases_dir, output_dir, index,
                                        assignment_id, analyse_result_file, max_workers=None):
    test_cases = [
        f for f in os.listdir(test_cases_dir)
        if f.startswith('case') and f.endswith('.txt') and f[4:-4].isdigit() and (int(f[4:-4]) >= 0)
    ]
    original_count = len(test_cases) 
    for case in test_cases:
        case_id = case[4:-4]
        input_path = os.path.join(test_cases_dir, f"input{case_id}.txt")
        if not os.path.exists(input_path):
            open(input_path, 'w').close()

    all_students = []
    for student in os.listdir(students_dir):
        student_path = os.path.join(students_dir, student)
        if not os.path.isdir(student_path):
            continue
        student_assignment_path = os.path.join(student_path, assignment_id)
        if not os.path.exists(student_assignment_path):
            continue
        has_last = os.path.exists(os.path.join(student_assignment_path, 'last_100.0.txt'))
        has_root_last = os.path.exists(os.path.join(student_assignment_path, '100.0.txt'))
        has_first = os.path.exists(os.path.join(student_assignment_path, 'first_100.0.txt'))
        if has_last or has_root_last:
            target_dir = os.path.join(student_assignment_path, 'last')
        elif has_first:
            target_dir = os.path.join(student_assignment_path, 'first')
        else:
            continue
        if not os.path.exists(os.path.join(target_dir, 'Compiler.java')):
            continue
        all_students.append((student, target_dir))

    if not all_students:
        return
    print("正在运行标准程序... ")  
    if index == 3: 
        valid_case_ids, std_outputs = test_standard_students_for_compiler(
            STANDARD_STUDENT_IDS_4, students_dir, assignment_id, test_cases_dir, test_cases
        )
    else:
        valid_case_ids, std_outputs = test_standard_students_for_compiler(
            STANDARD_STUDENT_IDS_5, students_dir, assignment_id, test_cases_dir, test_cases
        )        
    if not valid_case_ids:
        print("无有效的测试用例")
        return
    print(f"标准程序验证完成。")
    test_cases = [f"case{cid}.txt" for cid in valid_case_ids]

    case_student_outputs = defaultdict(dict)
    sys.stdout.flush()

    completed = 0
    total = len(all_students)
    start_time = time.time()

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(test_single_student_for_comilper, student, target_dir, test_cases_dir, test_cases): student 
            for student, target_dir in all_students
        }

        for future in concurrent.futures.as_completed(futures):
            student = futures[future]
            try:
                outputs = future.result()
                for case_id, out in outputs.items():
                    case_student_outputs[case_id][student] = out
            except Exception as e:
                print(f"\n学生 {student} 测试异常：{e}")
                sys.stdout.flush()
                for case in test_cases:
                    case_id = case[4:-4]
                    case_student_outputs[case_id][student] = None

            completed += 1
            percent = (completed / total) * 100
            elapsed = time.time() - start_time
            sys.stdout.write(f"\r编译器测试进度: {completed}/{total} ({percent:.1f}%) | 已用时: {elapsed:.1f}s")
            sys.stdout.flush()
            
    print()

    students = [s for s, _ in all_students]
    case_ids_sorted = sorted(valid_case_ids, key=int)
    initial_case_count = original_count 
    version_map = defaultdict(dict)

    for case_id in case_ids_sorted:
        case_name = f"case{case_id}"
        std_output = std_outputs.get(case_id, None)
        output_to_version = {}
        current_version = 2
        
        fingerprint = std_output.strip() if isinstance(std_output, str) else ""
        output_to_version[fingerprint] = 1
        version_map[case_name][STANDARD_STUDENT_IDS[0]] = 1

        for student in students:
            if student in STANDARD_STUDENT_IDS:
                version_map[case_name][student] = 1
                continue

            output = case_student_outputs[case_id].get(student, None)
            if output is None:
                version_map[case_name][student] = 0
                continue

            fingerprint = output.strip() if isinstance(output, str) else ""
            if fingerprint not in output_to_version:
                output_to_version[fingerprint] = current_version
                current_version += 1
            
            version_map[case_name][student] = output_to_version[fingerprint]

    filtered_case_ids = []
    for case_id in case_ids_sorted:
        case_name = f"case{case_id}"
        total_students = len(students)
        if total_students == 0:
            continue
        match_count = sum(1 for s in students if version_map[case_name].get(s) == 1)
        pass_rate = match_count / total_students
        unique_versions = len(set(version_map[case_name].get(s) for s in students))
        # if pass_rate >= 0.88 and unique_versions <= 10:
        filtered_case_ids.append(case_id)
    final_case_count = len(filtered_case_ids)
    case_efficiency = (final_case_count / initial_case_count * 100) if initial_case_count > 0 else 0.0
    print(f"测试用例统计: 初始={initial_case_count}, 最终={final_case_count}, 有效率={case_efficiency:.2f}%")
    
    case_ids_sorted = filtered_case_ids

    data_rows = []
    case_cols = [f"case{cid}" for cid in case_ids_sorted]
    
    for student in students:
        row = {'学生': student}
        for cid in case_ids_sorted:
            row[f"case{cid}"] = version_map[f"case{cid}"].get(student, 0)
        data_rows.append(row)

    df = pd.DataFrame(data_rows, columns=['学生'] + case_cols)

    with pd.ExcelWriter(analyse_result_file) as writer:
        df.to_excel(writer, index=False, sheet_name='版本报告')

    student_pass_rates = {}
    for student in students:
        pass_count = sum(1 for c in case_ids_sorted if version_map[f"case{c}"].get(student) == 1)
        student_pass_rates[student] = pass_count / len(case_ids_sorted) if case_ids_sorted else 0
    
    ranges = [(1.0, "100%"), (0.9, "90-100%"), (0.8, "80-90%"), (0.7, "70-80%"), (0.0, "<70%")]
    counts = {label: 0 for _, label in ranges}
    for student, rate in student_pass_rates.items():
        for threshold, label in ranges:
            if rate >= threshold:
                counts[label] += 1
                break

    total_valid = sum(counts.values())
    output_parts = []
    for _, label in ranges:
        count = counts[label]
        pct = (count / total_valid * 100) if total_valid > 0 else 0.0
        output_parts.append(f"{label}={count} ({pct:.2f}%)")

    print(f"学生通过率分布: {', '.join(output_parts)}")
    print(f"结果保存到{analyse_result_file}")

def test_single_student(index, target_dir, test_cases_dir, test_cases):
    try:
        run_with_timeout(
            ['javac', 'Compiler.java'],
            cwd=target_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=30
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {case: None for case in test_cases}

    result_fingerprints = {}

    for case in test_cases:
        case_id = case[4:-4]
        case_path = os.path.join(test_cases_dir, case)
        testfile = os.path.join(target_dir, "testfile.txt")
        shutil.copy(case_path, testfile)
        out_files = ['lexer.txt', 'parser.txt', 'symbol.txt', 'error.txt']
        for f in out_files:
            p = os.path.join(target_dir, f)
            if os.path.exists(p):
                os.remove(p)
        try:
            run_with_timeout(
                ['java', 'Compiler'],
                cwd=target_dir,
                check=True,
                timeout=3,
                capture_output=True,
                text=True
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            # print(f"{case_id},timeout")
            pass

        non_empty_files = []
        error_content = None
        for fname in out_files:
            i = out_files.index(fname)
            if i < 3 and i != index:
                continue
            fpath = os.path.join(target_dir, fname)
            if not os.path.exists(fpath):
                continue
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read().strip()
                if content:
                    non_empty_files.append((fname, content))
                    if fname == 'error.txt':
                        error_content = content
            except Exception:
                pass
            finally:
                if os.path.exists(fpath):
                    os.remove(fpath)
        if os.path.exists(testfile):
            os.remove(testfile)
        if not non_empty_files:
            fingerprint = None
        elif error_content is not None:
            fingerprint = ("error", error_content)
        else:
            non_empty_files.sort()
            fingerprint = ("normal", tuple(non_empty_files))
        result_fingerprints[case] = fingerprint

    clean_class_files(target_dir)
    return result_fingerprints

def test_single_student_for_comilper(student, target_dir, test_cases_dir, test_cases):
    config_path = os.path.join(target_dir, "config.json")
    if not os.path.exists(config_path):
        return {case[4:-4]: None for case in test_cases}
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        lang = config.get("programming language")
        target = config.get("object code")
        if lang != "java" or target not in ["pcode", "llvm", "mips"]:
            return {case[4:-4]: None for case in test_cases}
    except Exception:
        return {case[4:-4]: None for case in test_cases}

    try:
        run_with_timeout(
            ['javac', 'Compiler.java'],
            cwd=target_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=30
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # print(f"{student} error")
        return {case[4:-4]: None for case in test_cases}

    result_outputs = {}
    for case in test_cases:
        case_id = case[4:-4]
        case_path = os.path.join(test_cases_dir, case)
        input_path = os.path.join(test_cases_dir, f"input{case_id}.txt")
        testfile = os.path.join(target_dir, "testfile.txt")
        shutil.copy(case_path, testfile)
        for f in ["pcoderesult.txt", "llvm_ir.txt", "mips.txt"]:
            p = os.path.join(target_dir, f)
            if os.path.exists(p):
                os.remove(p)
        try:
            if target == "pcode":
                with open(input_path, 'r') as inp:
                    run_with_timeout(
                        ['java', 'Compiler'],
                        cwd=target_dir,
                        stdin=inp,
                        check=True,
                        timeout=2,
                        capture_output=True,
                        text=True
                    )
            else:
                run_with_timeout(
                    ['java', 'Compiler'],
                    cwd=target_dir,
                    check=True,
                    timeout=2,
                    capture_output=True,
                    text=True
                )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

        output_content = None
        try:
            if target == "pcode":
                res_file = os.path.join(target_dir, "pcoderesult.txt")
                if os.path.exists(res_file):
                    with open(res_file, 'r', encoding='utf-8', errors='ignore') as f:
                        output_content = f.read()
            elif target == "llvm":
                ir_file = os.path.join(target_dir, "llvm_ir.txt")
                if not os.path.exists(ir_file):
                    output_content = ""
                else:
                    runtime_path = RUNTIME_PATH
                    if not os.path.exists(runtime_path):
                        output_content = ""
                    else:
                        with open(ir_file, 'r', encoding='utf-8', errors='ignore') as f:
                            student_lines = f.readlines()
                        filtered_lines = []
                        for line in student_lines:
                            if 'declare' in line and any(func in line for func in [
                                '@getint', '@getchar', '@putint', '@putch', '@putstr'
                            ]):
                                continue
                            filtered_lines.append(line)
                        merged_ir = os.path.join(target_dir, "merged.ll")
                        with open(merged_ir, 'w', encoding='utf-8') as f:
                            f.writelines(filtered_lines)
                            f.write('\n')
                            with open(runtime_path, 'r', encoding='utf-8') as rt_f:
                                f.write(rt_f.read())
                        with open(input_path, 'r') as inp:
                            result = run_with_timeout(
                                [LLI_PATH, merged_ir],
                                stdin=inp,
                                capture_output=True,
                                text=True,
                                timeout=2,
                                cwd=target_dir
                            )
                        output_content = result.stdout
                        if os.path.exists(merged_ir):
                            os.remove(merged_ir)
            elif target == "mips":
                mips_file = os.path.join(target_dir, "mips.txt")
                if os.path.exists(mips_file):
                    with open(input_path, 'r') as inp:
                        result = run_with_timeout(
                            ['java', '-jar', MARS_JAR_PATH, 'nc', mips_file],
                            stdin=inp,
                            capture_output=True,
                            text=True,
                            timeout=2,
                            cwd=target_dir
                        )
                    output_content = result.stdout
        except Exception:
            output_content = None
        finally:
            for tmp in ["pcoderesult.txt", "llvm_ir.txt", "mips.txt", "merged.ll", testfile]:
                p = os.path.join(target_dir, tmp)
                if os.path.exists(p):
                    os.remove(p)
        result_outputs[case_id] = output_content

    clean_class_files(target_dir)
    return result_outputs

def clean_class_files(directory):
    for root, _, files in os.walk(directory):
        for f in files:
            if f.endswith('.class'):
                try:
                    os.remove(os.path.join(root, f))
                except OSError:
                    pass

def save_version_content(base_dir, case_name, version_id, content):
    if version_id == 0:
        return
    case_dir = os.path.join(base_dir, case_name)
    os.makedirs(case_dir, exist_ok=True)
    filename = f"version{version_id}.txt"
    filepath = os.path.join(case_dir, filename)
    content_str = ""
    if isinstance(content, tuple):
        type_flag, data = content
        content_str += f"Type: {type_flag}\n"
        content_str += "=" * 50 + "\n"
        if type_flag == "error":
            content_str += str(data)
        else:
            for fname, fcontent in data:
                content_str += f"--- {fname} ---\n{fcontent}\n\n"
    else:
        content_str = str(content) if content is not None else ""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content_str)

def is_valid_case_filename(filename):
    if not (filename.startswith('case') and filename.endswith('.txt')):
        return False
    num_part = filename[4:-4]
    return num_part.isdigit()

def analyze_test_results(output_dir='test_results', excel_path='versions_report.xlsx'):
    students = [d for d in os.listdir(output_dir) if os.path.isdir(os.path.join(output_dir, d))]
    if not students:
        return
    all_case_dirs = set()
    for student in students:
        student_dir = os.path.join(output_dir, student)
        if not os.path.isdir(student_dir):
            continue
        for item in os.listdir(student_dir):
            if os.path.isdir(os.path.join(student_dir, item)):
                if re.fullmatch(r'case\d+', item):
                    all_case_dirs.add(item)
    test_cases = sorted(all_case_dirs, key=lambda x: int(x[4:]))
    version_map = defaultdict(dict)
    for case in test_cases:
        fingerprint_to_version = {}
        current_version = 1
        for student in students:
            case_dir = os.path.join(output_dir, student, case)
            if not os.path.exists(case_dir):
                version_map[case][student] = 0
                continue
            non_empty_files = []
            for fname in os.listdir(case_dir):
                fpath = os.path.join(case_dir, fname)
                if not os.path.isfile(fpath):
                    continue
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read().strip()
                    if content:
                        non_empty_files.append((fname, content))
                except Exception:
                    continue
            if not non_empty_files:
                version_map[case][student] = 0
                continue
            error_content = None
            for fname, content in non_empty_files:
                if fname == "error.txt":
                    error_content = content
                    break
            if error_content is not None:
                fingerprint = ("error", error_content)
            else:
                non_empty_files.sort()
                fingerprint = ("normal", tuple(non_empty_files))
            if fingerprint not in fingerprint_to_version:
                fingerprint_to_version[fingerprint] = current_version
                current_version += 1
            version_map[case][student] = fingerprint_to_version[fingerprint]
    df = pd.DataFrame(columns=['学生'] + test_cases)
    for student in students:
        row = {'学生': student}
        for case in test_cases:
            row[case] = version_map[case].get(student, 0)
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    with pd.ExcelWriter(excel_path) as writer:
        df.to_excel(writer, index=False, sheet_name='版本报告')

if __name__ == "__main__":
    raise SystemExit(
        "Use `python -m hiretest.reproduce_test`; test.py is the evaluation engine, "
        "not a standalone path-configured entry point."
    )
