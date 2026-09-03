import os
import time
import re
import glob
import argparse
from openai import OpenAI
from typing import Tuple, Optional
import requests
import pandas as pd
import sys 
from pathlib import Path
# ====== 配置区 ======
RELEASE_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = Path(os.environ.get("HIRETEST_BASE_DIR", RELEASE_ROOT)).resolve()
API_BASE = os.environ.get("OPENAI_BASE_URL") or os.environ.get("API_BASE", "")
API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY", "")
MODEL_NAME = os.environ.get("OPENAI_MODEL") or os.environ.get("MODEL_NAME", "gpt-4o")

TEMPERATURE = float(os.environ.get("HIRETEST_TEMPERATURE", "0.4"))
MAX_TOKENS = int(os.environ.get("HIRETEST_MAX_TOKENS", "4096"))
TOP_P = float(os.environ.get("HIRETEST_TOP_P", "1.0"))
FREQUENCY_PENALTY = float(os.environ.get("HIRETEST_FREQUENCY_PENALTY", "0.0"))
PRESENCE_PENALTY = float(os.environ.get("HIRETEST_PRESENCE_PENALTY", "0.0"))
TIMEOUT = int(os.environ.get("HIRETEST_TIMEOUT", "100"))

STAGES = ["1to2", "2to3", "3to4", "4to5", "5to6"]
PROMPT_ROOT = Path(os.environ.get("HIRETEST_REPAIR_PROMPT_ROOT", BASE_DIR / "data" / "restricted" / "repair_prompts"))
CASE_ROOT = BASE_DIR / "artifacts" / "RQ1" / "development_cases" / "Hiretest_raw"
RESULT_ROOT = BASE_DIR / "artifacts" / "RQ1" / "development_cases" / "Hiretest"
CHECK_PROMPT_ROOT = BASE_DIR / "prompts" / "public_templates"
OVERWRITE = False

index = 1

def _stage_to_index(stage: str) -> int:
    if stage not in STAGES:
        raise ValueError(f"Unsupported stage: {stage}")
    return STAGES.index(stage) + 1

def _make_paths(idx, prompt_root=None, case_root=None, result_root=None, check_prompt_root=None):
    global index, constraint_path, PREFIX_PROMPT_FILE
    global TEST_CASE_PROMPT_DIR, TEST_CASE_DIR, TEST_CASE_FIXED_DIR
    global TEST_CASE_UNFIXED_DIR, RESULT_DIR
    index = idx
    stage = f"{idx}to{idx+1}"
    prompt_root = Path(prompt_root or PROMPT_ROOT)
    case_root = Path(case_root or CASE_ROOT)
    result_root = Path(result_root or RESULT_ROOT)
    check_prompt_root = Path(check_prompt_root or CHECK_PROMPT_ROOT)
    constraint_path    = str(check_prompt_root / f"constraint_{stage}.txt")
    PREFIX_PROMPT_FILE = str(check_prompt_root / f"check_prompt_{stage}.txt")
    TEST_CASE_PROMPT_DIR  = str(prompt_root / stage)
    TEST_CASE_DIR         = str(case_root / stage)
    TEST_CASE_FIXED_DIR   = str(case_root / f"{stage}_fixed")
    TEST_CASE_UNFIXED_DIR = str(case_root / stage)
    RESULT_DIR            = str(result_root / stage)

_make_paths(index)

def extract_last_c_code(response: str) -> str:
    code_blocks = re.findall(r"```(?:[cC]|\s*)\s*\n?(.*?)\s*```", response, re.DOTALL)
    code_blocks_1 = re.findall(r"'''(?:[cC]|\s*)\s*\n?(.*?)\s*'''", response, re.DOTALL)
    if code_blocks:
        return code_blocks[-1].strip()
    elif code_blocks_1:
        return code_blocks_1[-1].strip()
    else:
        return response.strip()
    
def parse_dual_output(response: str) -> Tuple[str, str]:
    code = ""
    stdin_content = ""

    test_case_section = None
    test_case_match = re.search(r"test\_?case\s*[:：]?\s*(.*)", response, re.DOTALL)
    if test_case_match:
        test_case_section = test_case_match.group(1)

    search_for_code = test_case_section if test_case_section is not None else response

    backtick_blocks = re.findall(r"```[cC]\s*\n?(.*?)\s*```", search_for_code, re.DOTALL)
    single_quote_blocks = re.findall(r"'''[cC]\s*\n?(.*?)\s*'''", search_for_code, re.DOTALL)
    all_code_blocks = backtick_blocks + single_quote_blocks

    if all_code_blocks:
        code = all_code_blocks[-1].strip()

    stdin_section = None
    stdin_match = re.search(r"stdin\s*[:：]?\s*(.*)", response, re.DOTALL)
    if stdin_match:
        stdin_section = stdin_match.group(1)

    if stdin_section is not None:
        stdin_backtick = re.findall(r"```(?:\s*)?\s*\n?(.*?)\s*```", stdin_section, re.DOTALL)
        stdin_single = re.findall(r"'''(?:\s*)?\s*\n?(.*?)\s*'''", stdin_section, re.DOTALL)
        all_stdin_blocks = stdin_backtick + stdin_single
        if all_stdin_blocks:
            stdin_content = all_stdin_blocks[-1].strip()
        else:
            lines = []
            for line in stdin_section.splitlines():
                stripped = line.strip()
                if stripped == "":
                    break
                lines.append(stripped)
            stdin_content = "\n".join(lines).strip()
    else:
        stdin_content = ""

    return code, stdin_content

def parse_fix_response_for_gen(response: str) -> Tuple[bool, str]:
    fix_match = re.search(r"是否是错误修复\s*[:：]\s*(是|否)", response)
    is_fixed = fix_match and fix_match.group(1) == "是"

    test_case_code = ""

    test_case_section = None
    section_match = re.search(r"test\_?case\s*[:：]?\s*(.*)", response, re.DOTALL)
    if section_match:
        test_case_section = section_match.group(1)
    
    search_text = test_case_section if test_case_section is not None else response

    backtick_blocks = re.findall(r"```(?:[cC]|\s*)?\s*\n?(.*?)\s*```", search_text, re.DOTALL)
    single_quote_blocks = re.findall(r"'''(?:[cC]|\s*)?\s*\n?(.*?)\s*'''", search_text, re.DOTALL)
    all_blocks = backtick_blocks + single_quote_blocks

    if all_blocks:
        test_case_code = all_blocks[-1].strip()

    return is_fixed, test_case_code

def generate_test_case(client, user_prompt: str, max_retries=3) -> str:
    for attempt in range(max_retries):
        try:
            completion = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": "You are a program testing expert."},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=TEMPERATURE,
                max_completion_tokens=MAX_TOKENS,
                top_p=TOP_P,
                frequency_penalty=FREQUENCY_PENALTY,
                presence_penalty=PRESENCE_PENALTY,
                timeout=TIMEOUT
            )
            return completion.choices[0].message.content
        except Exception as e:
            time.sleep(5)
    return "ERROR: Failed to generate after retries."


def generate_test_case_claude(client, user_prompt: str, max_retries=3) -> str:
    url = API_BASE.strip()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY.strip()}"
    }

    for attempt in range(max_retries):
        try:
            payload = {
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": "You are a program testing expert."},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": TEMPERATURE,
                "max_tokens": MAX_TOKENS,
                "top_p": TOP_P,
                "frequency_penalty": FREQUENCY_PENALTY,
                "presence_penalty": PRESENCE_PENALTY
            }

            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=TIMEOUT
            )

            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text}")

            return response.json()["choices"][0]["message"]["content"]

        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            pass
            
        time.sleep(5)

    return "ERROR: Failed to generate after retries."


def get_case_files_sorted(test_case_dir: str):
    files = os.listdir(test_case_dir)
    case_pattern = re.compile(r"^case(\d+)\.txt$")
    cases = []
    for f in files:
        match = case_pattern.match(f)
        if match:
            case_id = int(match.group(1))
            cases.append((case_id, f))
    cases.sort(key=lambda x: x[0])
    return [(case_id, os.path.join(test_case_dir, filename)) for case_id, filename in cases]

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def read_text_file(filepath: str, encoding="utf-8") -> Optional[str]:
    try:
        with open(filepath, "r", encoding=encoding) as f:
            return f.read().strip()
    except Exception as e:
        return None


def write_text_file(filepath: str, content: str, encoding="utf-8"):
    try:
        with open(filepath, "w", encoding=encoding) as f:
            f.write(content)
    except Exception as e:
        pass


def require_llm_config():
    missing = []
    if not API_BASE.strip():
        missing.append("OPENAI_BASE_URL or API_BASE")
    if not API_KEY.strip():
        missing.append("OPENAI_API_KEY or API_KEY")
    if missing:
        raise RuntimeError(
            "Missing LLM configuration: "
            + ", ".join(missing)
            + ". Set them in the environment before running generation/check."
        )


def validate_stage_paths(mode: str):
    prompt_dir = Path(TEST_CASE_PROMPT_DIR)
    case_dir = Path(TEST_CASE_DIR)
    result_dir = Path(RESULT_DIR)
    check_prompt = Path(PREFIX_PROMPT_FILE)
    constraint = Path(constraint_path)

    if mode in {"generate", "both"}:
        if not prompt_dir.is_dir():
            raise FileNotFoundError(f"Missing prompt directory: {prompt_dir}")
        if not get_case_files_sorted(str(prompt_dir)):
            raise FileNotFoundError(f"No case*.txt prompt files found in: {prompt_dir}")

    if mode in {"check", "both"}:
        if not check_prompt.is_file():
            raise FileNotFoundError(f"Missing check prompt: {check_prompt}")
        if not constraint.is_file():
            raise FileNotFoundError(f"Missing constraint file: {constraint}")
        if mode == "check" and not case_dir.is_dir():
            raise FileNotFoundError(f"Missing generated case directory: {case_dir}")

    return {
        "prompt_dir": prompt_dir,
        "case_dir": case_dir,
        "result_dir": result_dir,
        "check_prompt": check_prompt,
        "constraint": constraint,
    }


def print_stage_summary(stage: str, mode: str):
    paths = validate_stage_paths(mode)
    prompt_count = len(get_case_files_sorted(str(paths["prompt_dir"]))) if paths["prompt_dir"].is_dir() else 0
    generated_count = len(get_sorted_case_files(str(paths["case_dir"]))) if paths["case_dir"].is_dir() else 0
    result_count = len(get_sorted_case_files(str(paths["result_dir"]))) if paths["result_dir"].is_dir() else 0
    print(f"{stage}:")
    print(f"  prompt_dir: {paths['prompt_dir']} (case prompts: {prompt_count})")
    print(f"  case_dir:   {paths['case_dir']} (generated cases: {generated_count})")
    print(f"  result_dir: {paths['result_dir']} (checked cases: {result_count})")
    if mode in {"check", "both"}:
        print(f"  check_prompt: {paths['check_prompt']}")
        print(f"  constraint:   {paths['constraint']}")


def get_sorted_case_files(test_case_dir: str) -> list[Tuple[int, str]]:
    files = os.listdir(test_case_dir)
    case_pattern = re.compile(r"^case(\d+)\.txt$")
    cases = []
    for f in files:
        match = case_pattern.match(f)
        if match:
            case_id = int(match.group(1))
            cases.append((case_id, os.path.join(test_case_dir, f)))
    cases.sort(key=lambda x: x[0])
    return cases


def create_llm_client() -> OpenAI:
    return OpenAI(base_url=API_BASE.strip(), api_key=API_KEY)


def call_llm(client: OpenAI, prompt: str, max_retries=3) -> str:
    for attempt in range(max_retries):
        try:
            completion = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": "You are a compiler testing expert."},
                    {"role": "user", "content": prompt}
                ],
                temperature=TEMPERATURE,
                max_completion_tokens=MAX_TOKENS,
                top_p=TOP_P,
                frequency_penalty=FREQUENCY_PENALTY,
                presence_penalty=PRESENCE_PENALTY,
                timeout=TIMEOUT
            )
            return completion.choices[0].message.content
        except Exception as e:
            time.sleep(5)
    return "ERROR: LLM call failed after retries."


def call_llm_claude(client, prompt: str, max_retries=3) -> str:
    url = API_BASE.strip()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY.strip()}"
    }

    for attempt in range(max_retries):
        try:
            payload = {
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": "You are a compiler testing expert."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": TEMPERATURE,
                "max_tokens": MAX_TOKENS,
                "top_p": TOP_P,
                "frequency_penalty": FREQUENCY_PENALTY,
                "presence_penalty": PRESENCE_PENALTY
            }

            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=TIMEOUT
            )

            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text}")

            return response.json()["choices"][0]["message"]["content"]

        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            pass
            
        time.sleep(5)

    return "ERROR: LLM call failed after retries."


def parse_llm_response(response: str) -> Tuple[bool, str]:
    compliant_match = re.search(r"是否符合\s*[:：]\s*(符合|不符合)", response)
    is_compliant = compliant_match and compliant_match.group(1) == "符合"

    new_test_case = ""
    if not is_compliant:
        test_case_section = None
        test_case_match = re.search(r"test\_?case\s*[:：]?\s*(.*)", response, re.DOTALL)
        if test_case_match:
            test_case_section = test_case_match.group(1)
        
        search_text = test_case_section if test_case_section is not None else response

        backtick_blocks = re.findall(r"```[cC]\s*\n?(.*?)\s*```", search_text, re.DOTALL)
        single_quote_blocks = re.findall(r"'''[cC]\s*\n?(.*?)\s*'''", search_text, re.DOTALL)

        all_blocks = backtick_blocks + single_quote_blocks
        if all_blocks:
            new_test_case = all_blocks[-1].strip()

    return is_compliant, new_test_case


def process_single_case(
    client: OpenAI,
    prefix_prompt: str,
    case_id: int,
    input_path: str,
    output_path: str
):
    original = read_text_file(input_path)
    if original is None or original == "":
        error_msg = "/* ERROR: Input file missing or empty */\n"
        write_text_file(output_path, error_msg)
        return

    full_prompt = f"{prefix_prompt}\n#测试用例\n{original}"

    response = call_llm(client, full_prompt)

    is_compliant, new_case = parse_llm_response(response)

    if is_compliant:
        final_content = original
    else:
        if new_case:
            final_content = new_case
        else:
            final_content = response

    write_text_file(output_path, final_content)

def replace_for_int_decl(line):
    match = re.search(r'\bfor\s*\(\s*int\s+([^;]+);([^;]+);([^)]+)\s*\)', line)
    if not match:
        return line

    init_expr = match.group(1).strip()
    condition = match.group(2).strip()
    update = match.group(3).strip()

    indent_match = re.match(r'^(\s*)', line)
    indent = indent_match.group(1) if indent_match else ""

    decl_line = f"{indent}int {init_expr};"

    new_for = f"for ({init_expr}; {condition}; {update})"

    new_line = line[:match.start()] + new_for + line[match.end():]

    return decl_line + "\n" + new_line

def replace_compound_assignments(line):
    IDENTIFIER = r'[a-zA-Z_][a-zA-Z0-9_]*'
    op_map = {
        '+=': '+',
        '-=': '-',
        '*=': '*',
        '/=': '/',
        '%=': '%'
    }

    def replacer(match):
        left_var = match.group(1).strip()
        op_eq = match.group(2)
        right_expr = match.group(3).strip()
        terminator = match.group(4)

        new_op = op_map[op_eq]
        new_expr = f"{left_var} = {left_var} {new_op} {right_expr}"
        if terminator == ';':
            return new_expr + ';'
        else:
            return new_expr

    pattern = rf'\b({IDENTIFIER})\s*(\+=|-=|\*=|/=|%=)\s*(.*?)(;|$)'
    return re.sub(pattern, replacer, line)

def sanitize_c_test_case(code: str) -> str:
    if not code:
        return code

    IDENTIFIER = r'[a-zA-Z_][a-zA-Z0-9_]*'

    lines = code.splitlines()
    new_lines = []

    for line in lines:
        stripped = line.strip()
        if re.match(r'^\s*#\s*include\s*(<[^>]+>|"([^"]+)")', stripped):
            continue
        new_lines.append(line)

    code = '\n'.join(new_lines)
    lines = code.splitlines()

    def replace_inc_dec(text):
        def repl(m):
            var = m.group(1)
            op = m.group(2)
            if op == '++':
                return f"{var} = {var} + 1"
            else:
                return f"{var} = {var} - 1"
        pattern = rf'\b({IDENTIFIER})\s*(\+\+|--)'
        return re.sub(pattern, repl, text)

    def fix_main_signature(line):
        match = re.match(r'^(\s*)int\s+main\s*\([^)]*\)\s*', line)
        if match:
            indent = match.group(1)
            if re.fullmatch(r'\s*int\s+main\s*\(\s*\)\s*', line.strip()):
                return line
            else:
                rest = line[match.end():]
                return f"{indent}int main(){rest}"
        return line
    
    def replace_in_string(match):
        string_content = match.group(0)
        inner = string_content[1:-1]
        cleaned_inner = re.sub(r'\\(?![n])', '', inner)
        return '"' + cleaned_inner + '"'

    processed_lines = []
    for line in lines:
        line = re.sub(r'"[^"]*"', replace_in_string, line)
        line = replace_inc_dec(line)
        line = fix_main_signature(line)
        line = replace_for_int_decl(line)
        processed_lines.extend(line.splitlines())

    final_lines = []
    i = 0
    while i < len(processed_lines):
        line = processed_lines[i]
        stripped = line.strip()

        func_match = re.match(r'^\s*int\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', stripped)
        if func_match:
            func_name = func_match.group(1)
            indent_match = re.match(r'^(\s*)', line)
            indent = indent_match.group(1) if indent_match else ""

            j = i
            while j < len(processed_lines) and '{' not in processed_lines[j]:
                j += 1
            if j >= len(processed_lines):
                final_lines.append(line)
                i += 1
                continue

            brace_count = 0
            k = j
            while k < len(processed_lines):
                l = processed_lines[k]
                for ch in l:
                    if ch == '{':
                        brace_count += 1
                    elif ch == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            break
                if brace_count == 0:
                    break
                k += 1

            if brace_count != 0:
                final_lines.extend(processed_lines[i:k+1])
                i = k + 1
                continue

            last_line_in_body = None
            for idx in range(k - 1, j, -1):
                l_stripped = processed_lines[idx].strip()
                if l_stripped and not l_stripped.startswith('//') and not l_stripped.startswith('/*'):
                    last_line_in_body = l_stripped
                    break

            needs_return = True
            if last_line_in_body and last_line_in_body.startswith('return ') and last_line_in_body.endswith(';'):
                needs_return = False

            final_lines.extend(processed_lines[i:k])

            if needs_return:
                if func_name == 'main':
                    return_stmt = f"{indent}    return 0;"
                else:
                    return_stmt = f"{indent}    return 1;"
                final_lines.append(return_stmt)

            final_lines.append(processed_lines[k])
            i = k + 1
        else:
            final_lines.append(line)
            i += 1
    output_lines = []
    for line in final_lines:
        match = re.search(r'\belse\s+if\s*(\([^)]*\))', line)
        if match:
            else_if_full = match.group(0)
            condition = match.group(1)
            indent_match = re.match(r'^(\s*)', line)
            indent = indent_match.group(1) if indent_match else ""
            new_if_line = f"{indent}if {condition}"
            before = line[:match.start()]
            after = line[match.end():]
            if before.strip():
                output_lines.append(before)
            output_lines.append("")
            output_lines.append(new_if_line + after)
        else:
            output_lines.append(line)
    output_lines = [replace_compound_assignments(line) for line in output_lines]
    return '\n'.join(output_lines)


NON_SOURCE_PHRASES = (
    "无需修改",
    "不需要修改",
    "原测试用例",
    "测试用例保持不变",
    "原因分析",
    "是否符合",
    "符合约束",
    "不符合约束",
)


def looks_like_sysy_source(code: str) -> bool:
    if not code:
        return False
    stripped = code.strip()
    if not stripped:
        return False
    if any(phrase in stripped for phrase in NON_SOURCE_PHRASES) and not re.search(
        r"\bint\s+main\s*\(", stripped
    ):
        return False
    if stripped.startswith(("原因分析", "是否符合", "test_case", "```", "'''")):
        return False
    if not re.search(r"\bint\s+main\s*\(", stripped):
        return False
    if "{" not in stripped or "}" not in stripped:
        return False
    return True


def guarded_case_content(candidate: str, fallback: str) -> str:
    extracted = extract_last_c_code(candidate)
    if looks_like_sysy_source(extracted):
        return extracted
    if looks_like_sysy_source(fallback):
        return fallback
    return extracted

def gen_test_case(use_routing=False, dual_output=False):
    require_llm_config()
    client = OpenAI(
        base_url=API_BASE.strip(),
        api_key=API_KEY,
    )

    case_files = get_case_files_sorted(TEST_CASE_PROMPT_DIR)
    if not case_files:
        raise FileNotFoundError(f"No case*.txt prompt files found in {TEST_CASE_PROMPT_DIR}")

    if use_routing:
        ensure_dir(TEST_CASE_FIXED_DIR)
        ensure_dir(TEST_CASE_UNFIXED_DIR)
    else:
        ensure_dir(TEST_CASE_DIR)

    total = len(case_files)
    print(f"开始生成测试用例，共 {total} 个...")
    sys.stdout.flush()
    
    for completed, (case_id, input_path) in enumerate(case_files, start=1):
        # 更新进度条
        percent = (completed / total) * 100
        bar_len = 40
        filled = int(bar_len * completed / total)
        bar = '█' * filled + '░' * (bar_len - filled)
        sys.stdout.write(f"\r生成进度: [{bar}] {completed}/{total} ({percent:.1f}%)")
        sys.stdout.flush()

        try:
            with open(input_path, "r", encoding="utf-8") as f:
                user_prompt = f.read().strip()
        except Exception as e:
            if dual_output:
                case_path = os.path.join(TEST_CASE_DIR, f"case{case_id}.txt")
                input_path_out = os.path.join(TEST_CASE_DIR, f"input{case_id}.txt")
                write_text_file(case_path, f"/* ERROR: {e} */")
                write_text_file(input_path_out, "")
            elif use_routing:
                write_text_file(os.path.join(TEST_CASE_UNFIXED_DIR, f"case{case_id}.txt"), f"/* ERROR: {e} */")
            else:
                write_text_file(os.path.join(TEST_CASE_DIR, f"case{case_id}.txt"), f"/* ERROR: {e} */")
            continue

        if not user_prompt:
            if dual_output:
                case_path = os.path.join(TEST_CASE_DIR, f"case{case_id}.txt")
                input_path_out = os.path.join(TEST_CASE_DIR, f"input{case_id}.txt")
                write_text_file(case_path, "/* ERROR: Input prompt is empty */")
                write_text_file(input_path_out, "")
            elif use_routing:
                write_text_file(os.path.join(TEST_CASE_UNFIXED_DIR, f"case{case_id}.txt"), "/* ERROR: Input prompt is empty */")
            else:
                write_text_file(os.path.join(TEST_CASE_DIR, f"case{case_id}.txt"), "/* ERROR: Input prompt is empty */")
            continue

        # 已生成则跳过，支持断点续跑
        _skip_path = os.path.join(TEST_CASE_DIR, f"case{case_id}.txt")
        if not OVERWRITE and os.path.exists(_skip_path) and os.path.getsize(_skip_path) > 0:
            continue

        time_count = 0
        while True:
            time_count += 1
            if time_count >= 3:
                break
            raw_response = generate_test_case(client, user_prompt)
            analyse_path = os.path.join(TEST_CASE_DIR, f"case{case_id}_analyse.txt")
            write_text_file(analyse_path, raw_response)
            if dual_output:
                code, stdin = parse_dual_output(raw_response)
                case_path = os.path.join(TEST_CASE_DIR, f"case{case_id}.txt")
                input_path_out = os.path.join(TEST_CASE_DIR, f"input{case_id}.txt")
                
                final_code = code if code else raw_response
                if not code:
                    continue
                write_text_file(case_path, final_code)
                write_text_file(input_path_out, stdin)
            elif use_routing:
                is_fixed, extracted_code = parse_fix_response_for_gen(raw_response)
                final_content = extracted_code if extracted_code else raw_response
                if not extracted_code:
                    continue
                if is_fixed:
                    write_text_file(os.path.join(TEST_CASE_FIXED_DIR, f"case{case_id}.txt"), final_content)
                write_text_file(os.path.join(TEST_CASE_UNFIXED_DIR, f"case{case_id}.txt"), final_content)
            else:
                extracted_code = extract_last_c_code(raw_response)
                if not extracted_code:
                    continue
                output_path = os.path.join(TEST_CASE_DIR, f"case{case_id}.txt")
                write_text_file(output_path, extracted_code)
            break
    print() 

def batch_sanitize_test_cases(test_case_dir, backup=False):
    if not os.path.isdir(test_case_dir):
        raise ValueError(f"目录不存在: {test_case_dir}")

    pattern = os.path.join(test_case_dir, "case*.txt")
    all_files = glob.glob(pattern)

    case_files = []
    for file_path in all_files:
        filename = os.path.basename(file_path)
        match = re.fullmatch(r'case(\d+)\.txt', filename)
        if match:
            case_id = int(match.group(1))
            case_files.append((case_id, file_path))

    case_files.sort(key=lambda x: x[0])

    if not case_files:
        return {'total': 0, 'modified': 0, 'unchanged': 0}

    total = len(case_files)
    modified = 0
    unchanged = 0

    for case_id, file_path in case_files:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                original_content = f.read()

            fixed_content = sanitize_c_test_case(original_content)

            if fixed_content != original_content:
                modified += 1
                
                if backup:
                    backup_path = file_path + '.bak'
                    with open(backup_path, 'w', encoding='utf-8') as f:
                        f.write(original_content)
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(fixed_content)
            else:
                unchanged += 1

        except Exception as e:
            pass

    return {
        'total': total,
        'modified': modified,
        'unchanged': unchanged
    }


def check_test_case(use_routing=False, dual_output=False, check_times=3):
    require_llm_config()
    test_case_dir = TEST_CASE_DIR
    result_dir = RESULT_DIR
    if use_routing is True:
        test_case_dir_fixed = TEST_CASE_DIR + '_fixed'
        result_dir_fixed = RESULT_DIR + '_fixed'

    ensure_dir(result_dir)
    client = create_llm_client()

    prefix_prompt = read_text_file(PREFIX_PROMPT_FILE)
    constraint = read_text_file(constraint_path)
    if prefix_prompt is None or prefix_prompt == "":
        raise FileNotFoundError(f"Missing or empty check prompt: {PREFIX_PROMPT_FILE}")
    if constraint is None:
        raise FileNotFoundError(f"Missing constraint file: {constraint_path}")
    prefix_prompt = prefix_prompt.replace("{constraint}", constraint)

    case_files = get_sorted_case_files(test_case_dir)
    if not case_files:
        raise FileNotFoundError(f"No generated case*.txt files found in {test_case_dir}")

    excel_data = []

    total = len(case_files)
    print(f"开始检查测试用例，共 {total} 个...")
    sys.stdout.flush()
    
    for completed, (case_id, input_path) in enumerate(case_files, start=1):
        # 更新进度条
        percent = (completed / total) * 100
        bar_len = 40
        filled = int(bar_len * completed / total)
        bar = '█' * filled + '░' * (bar_len - filled)
        sys.stdout.write(f"\r检查进度: [{bar}] {completed}/{total} ({percent:.1f}%)")
        sys.stdout.flush()
        
        # 已校验则跳过，支持断点续跑
        _checked_path = os.path.join(result_dir, f"case{case_id}.txt")
        if not OVERWRITE and os.path.exists(_checked_path) and os.path.getsize(_checked_path) > 0:
            continue

        original = read_text_file(input_path)
        stdin_path = os.path.join(test_case_dir, f"input{case_id}.txt")
        stdin_content = ""
        if os.path.exists(stdin_path):
            stdin_content = read_text_file(stdin_path) or ""
        fixed_save = False
        if use_routing:
            fixed_save = True
            
        if original is None or original == "":
            if dual_output:
                case_path = os.path.join(result_dir, f"case{case_id}.txt")
                input_path_out = os.path.join(result_dir, f"input{case_id}.txt")
                analyse_path = os.path.join(result_dir, f"case{case_id}_analyse.txt")
                write_text_file(case_path, "/* ERROR: Original test case missing */")
                write_text_file(input_path_out, "")
                write_text_file(analyse_path, "/* ERROR: Original test case missing */")
            else:
                case_path = os.path.join(result_dir, f"case{case_id}.txt")
                analyse_path = os.path.join(result_dir, f"case{case_id}_analyse.txt")
                write_text_file(case_path, "/* ERROR: Original test case missing */")
                write_text_file(analyse_path, "/* ERROR: Original test case missing */")
            excel_data.append({
                "case_id": case_id,
                "result": "不符合",
                "iteration_results": ["错误"]
            })
            continue
            
        iteration_results = []
        current_case_content = original
        current_stdin_content = stdin_content
        
        last_valid_case = original
        last_valid_stdin = stdin_content
        
        analyse_content = None
        has_non_compliant = False
        
        for iteration in range(1, check_times+1):
            if dual_output:
                full_prompt = f"{prefix_prompt}\n#测试用例\n{current_case_content}\n#标准输入\n{current_stdin_content}"
            else:
                full_prompt = f"{prefix_prompt}\n#测试用例\n{current_case_content}"
                
            response = call_llm(client, full_prompt)
            if dual_output:
                is_compliant, _ = parse_llm_response(response)
                
                case_path = os.path.join(result_dir, f"case{case_id}.txt")
                input_path_out = os.path.join(result_dir, f"input{case_id}.txt")
                analyse_path = os.path.join(result_dir, f"case{case_id}_analyse.txt")
                
                if fixed_save:
                    case_path = os.path.join(result_dir_fixed, f"case{case_id}.txt")
                    input_path_out = os.path.join(result_dir_fixed, f"input{case_id}.txt")
                    analyse_path = os.path.join(result_dir_fixed, f"case{case_id}_analyse.txt")
                
                if is_compliant:
                    iteration_status = "符合"
                    last_valid_case = current_case_content
                    last_valid_stdin = current_stdin_content
                    if not has_non_compliant:
                        analyse_content = response
                    write_text_file(case_path, current_case_content)
                    write_text_file(input_path_out, current_stdin_content)
                else:
                    code, stdin = parse_dual_output(response)
                    has_non_compliant = True
                    analyse_content = response
                    
                    if code:
                        final_code = guarded_case_content(code, last_valid_case)
                        iteration_status = "不符合"
                        last_valid_case = final_code
                        last_valid_stdin = stdin
                        write_text_file(case_path, final_code)
                        write_text_file(input_path_out, stdin)
                        if iteration < 3:
                            current_case_content = final_code
                            current_stdin_content = stdin
                    else:
                        iteration_status = "不符合 (无新代码)"
                        write_text_file(case_path, last_valid_case)
                        write_text_file(input_path_out, last_valid_stdin)
            else:
                is_compliant, new_case = parse_llm_response(response)
                
                case_path = os.path.join(result_dir, f"case{case_id}.txt")
                analyse_path = os.path.join(result_dir, f"case{case_id}_analyse.txt")
                
                if fixed_save:
                    case_path = os.path.join(result_dir_fixed, f"case{case_id}.txt")
                    analyse_path = os.path.join(result_dir_fixed, f"case{case_id}_analyse.txt")
                
                if is_compliant:
                    iteration_status = "符合"
                    last_valid_case = current_case_content
                    if not has_non_compliant:
                        analyse_content = response
                    write_text_file(case_path, current_case_content)
                else:
                    if new_case:
                        new_case = guarded_case_content(new_case, last_valid_case)
                        iteration_status = "不符合"
                        has_non_compliant = True
                        analyse_content = response
                        last_valid_case = new_case
                        write_text_file(case_path, new_case)
                        if iteration < 3:
                            current_case_content = new_case
                    else:
                        iteration_status = "不符合 (无新代码)"
                        has_non_compliant = True
                        analyse_content = response
                        write_text_file(case_path, last_valid_case)
            
            iteration_results.append(iteration_status)
        
        if analyse_content:
            write_text_file(analyse_path, analyse_content)
        
        final_result = "符合" if all(status == "符合" for status in iteration_results) else "不符合"
        
        excel_data.append({
            "case_id": case_id,
            "result": final_result,
            "iteration_results": iteration_results
        })
    print()  
    batch_sanitize_test_cases(result_dir)
    if excel_data:
        detail_data = []
        for data in excel_data:
            row = {"测试用例编号": data["case_id"]}
            # 动态生成检查次数列（根据实际 check_times）
            for i in range(check_times):
                col_name = f"第{i+1}次检查"
                row[col_name] = data["iteration_results"][i] if len(data["iteration_results"]) > i else "N/A"
            detail_data.append(row)
        
        detail_df = pd.DataFrame(detail_data)
        
        excel_data_dict = {}
        for data in excel_data:
            excel_data_dict[f"Case{data['case_id']}"] = [data['case_id'], data['result']]
        
        summary_df = pd.DataFrame(excel_data_dict)
        
        excel_file_path = os.path.join(result_dir, "test_case_results.xlsx")
        with pd.ExcelWriter(excel_file_path, engine='openpyxl') as writer:
            summary_df.to_excel(writer, sheet_name='汇总结果', index=False, header=False)
            detail_df.to_excel(writer, sheet_name='详细结果', index=False)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate/check HiReTest cases from existing test_case_prompt directories."
    )
    parser.add_argument(
        "--stage",
        choices=STAGES + ["all"],
        default="all",
        help="Assignment transition to process.",
    )
    parser.add_argument(
        "--mode",
        choices=["generate", "check", "both"],
        default="both",
        help="Generate cases, check generated cases, or run both.",
    )
    parser.add_argument(
        "--prompt-root",
        default=str(PROMPT_ROOT),
        help="Root directory containing <stage>/case*.txt prompt files.",
    )
    parser.add_argument(
        "--case-root",
        default=str(CASE_ROOT),
        help="Root directory used for raw generated cases.",
    )
    parser.add_argument(
        "--result-root",
        default=str(RESULT_ROOT),
        help="Root directory used for checked cases.",
    )
    parser.add_argument(
        "--check-prompt-root",
        default=str(CHECK_PROMPT_ROOT),
        help="Directory containing constraint_*.txt and check_prompt_*.txt.",
    )
    parser.add_argument(
        "--model",
        default=MODEL_NAME,
        help="LLM model name. Defaults to OPENAI_MODEL/MODEL_NAME/gpt-4o.",
    )
    parser.add_argument(
        "--check-times",
        type=int,
        default=3,
        help="Number of LLM check/fix iterations.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Regenerate/recheck cases even when output files already exist.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only validate and print paths/counts; do not call the LLM.",
    )
    return parser.parse_args()


def main():
    global MODEL_NAME, OVERWRITE

    args = parse_args()
    MODEL_NAME = args.model
    OVERWRITE = args.overwrite

    stages = STAGES if args.stage == "all" else [args.stage]
    for stage in stages:
        run_index = _stage_to_index(stage)
        _make_paths(
            run_index,
            prompt_root=args.prompt_root,
            case_root=args.case_root,
            result_root=args.result_root,
            check_prompt_root=args.check_prompt_root,
        )
        use_routing = False
        dual = run_index > 3
        os.makedirs(TEST_CASE_DIR, exist_ok=True)
        if args.mode in {"check", "both"}:
            os.makedirs(RESULT_DIR, exist_ok=True)

        print(f"\n{'='*60}")
        print(f"处理阶段 {stage}")
        print(f"  mode:       {args.mode}")
        print(f"  model:      {MODEL_NAME}")
        print(f"  dual_output:{dual}")
        print(f"{'='*60}")
        print_stage_summary(stage, args.mode)
        if args.dry_run:
            continue

        if args.mode in {"generate", "both"}:
            gen_test_case(use_routing=use_routing, dual_output=dual)
        if args.mode in {"check", "both"}:
            check_test_case(
                use_routing=use_routing,
                dual_output=dual,
                check_times=args.check_times,
            )


if __name__ == "__main__":
    main()
