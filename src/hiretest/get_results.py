import os
import re
import pandas as pd
from typing import Tuple, Optional, Dict, Any
try:
    from .data_preprocessing import load_ast_file
except ImportError:
    from data_preprocessing import load_ast_file
from pathlib import Path
import argparse

try:
    from .paths import data_workspace_root, public_prompt_root
except ImportError:  # Support direct execution from src/hiretest.
    from paths import data_workspace_root, public_prompt_root


PROJECT_ROOT = data_workspace_root()
PROMPT_DIR = public_prompt_root()
mid_data_path = []
homework_ids = []
test_case_ids = ["","1to2","2to3","3to4","4to5","5to6"]


def logical_to_physical_offset(file_path: str, log_start: int, log_end: int) -> Tuple[int, int]:
    """
    Map the logical character indices from GumTree TextDiff to physical byte offsets in the original file.
    
    GumTree TextDiff rules:
    - \r\n is counted as 1 logical character (normalized to \n)
    - All other characters are counted as 1
    
    Args:
        file_path: Source code file path
        log_start: Start logical position from TextDiff output
        log_end: End logical position from TextDiff output
    
    Returns:
        (phys_start, phys_end): Byte offsets in the original file [start, end)
    """
    with open(file_path, 'rb') as f:
        raw = f.read()
    
    phys_start = phys_end = None
    gum_idx = 0
    i = 0
    n = len(raw)
    
    while i < n and gum_idx <= log_end:
        if gum_idx == log_start and phys_start is None:
            phys_start = i
        if gum_idx == log_end and phys_end is None:
            phys_end = i
        if phys_start is not None and phys_end is not None:
            break
        
        # \r\n is counted as 1 step in logic but occupies 2 bytes physically
        if raw[i] == 0x0D and i + 1 < n and raw[i+1] == 0x0A:
            gum_idx += 1
            i += 2
        else:
            gum_idx += 1
            i += 1
    
    if phys_end is None:
        phys_end = i
    return phys_start or 0, min(phys_end, n)


def extract_code_by_logical_position(file_path: str, log_start: int, log_end: int, 
                                     snap_to_boundary: bool = True) -> str:
    """
    Extract code snippets from the source code file based on TextDiff logical coordinates.
    
    Args:
        file_path: Source code file path
        log_start: Start position from TextDiff
        log_end: End position from TextDiff
        snap_to_boundary: Whether to smartly snap to complete syntax boundaries (to solve ±1 truncation issues)
    
    Returns:
        Extracted code string
    """
    if log_start == -1 or log_end == -1:
        return ""
    
    phys_start, phys_end = logical_to_physical_offset(file_path, log_start, log_end)
    
    with open(file_path, 'rb') as f:
        raw = f.read()
    
    if snap_to_boundary:
        # Forward modifier scan
        scan_back = max(0, phys_start - 50)
        window = raw[scan_back:phys_start]
        for kw in [b'public ', b'private ', b'protected ', b'static ', b'class ', b'interface ']:
            idx = window.rfind(kw)
            if idx != -1:
                phys_start = scan_back + idx
                break
        else:
            nl = window.rfind(b'\n')
            if nl != -1:
                phys_start = scan_back + nl + 1
        
        # Backward find closing }
        scan_fwd = min(len(raw), phys_end + 100)
        window_fwd = raw[phys_end:scan_fwd]
        brace = window_fwd.find(b'}')
        if brace != -1:
            phys_end = phys_end + brace + 1
        while phys_end < len(raw) and raw[phys_end:phys_end+1] in b' \t\r\n':
            phys_end += 1
    
    try:
        return raw[phys_start:phys_end].decode('utf-8', errors='ignore')
    except:
        return ""


def extract_and_save_method_contexts(
    excel_path: str,
    output_dir: str,
    base_data_dir: str,  # New parameter: data root directory, used to locate source files
    info_type: str
):
    """
    Extract code before and after each data change in methods from the predicted result Excel file, and save them as a deduplicated txt file.

    Args:
        excel_path (str): Input Excel file path
        output_dir (str): Output directory
        string_template (str): Template string for formatting output
        base_data_dir (s): Data root directory (e.g., 'HiReTest/data')
    """
    # 1. Load Excel data
    df = pd.read_excel(excel_path)
    print(f"Loaded {len(df)} predicted positive samples from {excel_path}.")

    # --- Key modification: group by homework_id ---
    # 2. Group by 'course id' (homework_id)
    grouped = df.groupby('Assignment ID')
    print(f"Found {len(grouped)} unique homework_ids: {list(grouped.groups.keys())}")

    # 3. Traverse each homework_id group
    for homework_id, group_df in grouped:
        homework_id = str(homework_id)
        try:
            index = homework_ids.index(homework_id)
        except ValueError as exc:
            raise ValueError(
                f"Assignment ID {homework_id!r} is not present in --assignment-ids"
            ) from exc
        if index == 0:
            raise ValueError(
                "Positive predictions must refer to a target assignment, not the first source assignment"
            )

        print(f"\nProcessing homework_id: {homework_id} ({len(group_df)} samples)")
        
        # 3.1 Create a dedicated output directory for the current homework_id
        homework_output_dir = os.path.join(output_dir, test_case_ids[index])
        os.makedirs(homework_output_dir, exist_ok=True)

        #3.2 Initialize a list to store (method_code_pair, formatted_string)
        results_to_dedup = []

        #3.3 Iterate through each line of the current group
        for idx, row in group_df.iterrows():
            try:
                file_name = row['File Path']
                student_id = str(row['Student ID'])
                #homework_id has been retrieved from the group
                old_pos_str = row['Old Change Position']
                new_pos_str = row['New Change Position']
                
                #Parse the position string
                old_start, old_end = parse_position_string(old_pos_str)
                new_start, new_end = parse_position_string(new_pos_str)

                #Extract the method code
                old_method_code = ""
                new_method_code = ""
                if old_start != -1 and new_start != -1:
                    old_method_code, _ = _extract_method_code(
                            base_data_dir, mid_data_path, homework_ids, file_name, student_id, homework_id, old_start, old_end, version='old'
                        )
                    new_method_code, _ = _extract_method_code(
                            base_data_dir, mid_data_path, homework_ids, file_name, student_id, homework_id, new_start, new_end, version='new'
                        )
                elif old_start != -1 and new_start == -1:
                    old_method_code, method_name = _extract_method_code(
                            base_data_dir, mid_data_path, homework_ids, file_name, student_id, homework_id, old_start, old_end, version='old'
                        )
                    if old_method_code and method_name:
                        new_method_code = _find_method_in_version(
                                    base_data_dir, mid_data_path, homework_ids, file_name, student_id, homework_id, method_name, version='new'
                                )
                elif old_start == -1 and new_start != -1:
                    new_method_code, method_name = _extract_method_code(
                            base_data_dir, mid_data_path, homework_ids, file_name, student_id, homework_id, new_start, new_end, version='new'
                        )
                    if new_method_code and method_name:
                            old_method_code = _find_method_in_version(
                                    base_data_dir, mid_data_path, homework_ids, file_name, student_id, homework_id, method_name, version='old'
                                )                 
                else:
                    continue
                if info_type == "piece":
                    if old_start != -1 and new_start != -1:
                        old_change_code, _ = _extract_change_code(
                            base_data_dir, mid_data_path, homework_ids, file_name, student_id, homework_id, old_start, old_end, version='old'
                        )
                        new_change_code, _ = _extract_change_code(
                            base_data_dir, mid_data_path, homework_ids, file_name, student_id, homework_id, new_start, new_end, version='new'
                        )
                    elif old_start != -1 and new_start == -1:
                        old_change_code, method_name = _extract_change_code(
                            base_data_dir, mid_data_path, homework_ids, file_name, student_id, homework_id, old_start, old_end, version='old'
                        )
                        if old_method_code and method_name:
                            new_change_code = _find_method_in_version(
                                    base_data_dir, mid_data_path, homework_ids, file_name, student_id, homework_id, method_name, version='new'
                                )
                    elif old_start == -1 and new_start != -1:
                        new_change_code, method_name = _extract_change_code(
                            base_data_dir, mid_data_path, homework_ids, file_name, student_id, homework_id, new_start, new_end, version='new'
                        )
                        if new_method_code and method_name:
                            old_change_code = _find_method_in_version(
                                    base_data_dir, mid_data_path, homework_ids, file_name, student_id, homework_id, method_name, version='old'
                                )                 
                    else:
                        continue                    
                #Generate the formatted string
                with open(PROMPT_DIR / 'prompt.txt','r',encoding='utf-8') as file:
                    template = file.read()

                with open(PROMPT_DIR / 'raw_constraint.txt','r',encoding='utf-8') as file:
                    constraint_content = file.read()

                if info_type == "total":
                    formatted_str = template.format(
                        constraint=constraint_content,
                        filename=file_name,
                        old_method_code=old_method_code,
                        new_method_code=new_method_code
                    )                    
                elif info_type == "piece":
                    formatted_str = template.format(
                        constraint=constraint_content,
                        filename=file_name,
                        old_method_code=old_change_code,
                        new_method_code=new_change_code
                    )                       
                if old_method_code == "" and new_method_code == "":
                    continue
                method_pair_key = (student_id, file_name, old_method_code, new_method_code)
                results_to_dedup.append((method_pair_key, formatted_str))

            except Exception as e:
                print(f"Error processing row (homework_id={homework_id}, idx={idx}): {e}")
                continue

        #3.4 Deduplicate the results for the current homework_id
        dedup_dict = {}
        for key, formatted_str in results_to_dedup:
            if key not in dedup_dict:
                dedup_dict[key] = formatted_str

        unique_strings = list(dedup_dict.values())
        print(f"  -> Generated {len(results_to_dedup)} strings, {len(unique_strings)} unique.")

        #3.5 Save to the folder for the current homework_id
        for i, s in enumerate(unique_strings, start=1):
            output_file = os.path.join(homework_output_dir, f"case{i}.txt")
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(s)
        
        print(f"  -> Saved {len(unique_strings)} unique cases to '{homework_output_dir}'.")

    print(f"\nAll processing finished. Results are saved under '{output_dir}'.")


def parse_position_string(pos_str: str) -> Tuple[int, int]:
    """Parse the position string like '[123, 456]' or '[-1, -1]', return (start, end)."""
    if pos_str == "N/A" or not isinstance(pos_str, str):
        return (-1, -1)
    try:
        clean_str = pos_str.strip('[]')
        parts = clean_str.split(',')
        start = int(parts[0].strip())
        end = int(parts[1].strip())
        return (start, end)
    except (ValueError, IndexError):
        return (-1, -1)

def _get_homework_index(homework_id: str, homework_ids: list) -> int:
    """Get the index of homework_id in homework_ids."""
    return homework_ids.index(homework_id)

def _map_to_source_code_path(base_data_dir: str, file_name: str, student_id: str, homework_id: str, version: str) -> str:
    """Map to the source code file path."""
    source_version_dir = 'first' if version == 'old' else 'last'
    return os.path.join(base_data_dir, 'data', student_id, homework_id, source_version_dir, file_name)

def _map_to_ast_path(base_data_dir: str, file_name: str, student_id: str, homework_id: str, mid_data_path: list, homework_ids: list, version: str) -> str:
    """Map to the AST file path."""
    hw_idx = _get_homework_index(homework_id, homework_ids)
    mid_data_dir_name = mid_data_path[hw_idx]
    ast_version_num = '2' if version == 'old' else '3'
    return os.path.join(base_data_dir, mid_data_dir_name, student_id, homework_id, ast_version_num, file_name + '.txt')

def _extract_method_code(base_data_dir: str, mid_data_path: list, homework_ids: list, 
                         file_name: str, student_id: str, homework_id: str, 
                         start: int, end: int, version: str) -> Tuple[str, str]:
    """
    Extract method code and method name based on logical coordinates (fixed coordinate mapping)
    Returns:
        (method_code, method_name)
    """
    source_file_path = _map_to_source_code_path(base_data_dir, file_name, student_id, homework_id, version)
    ast_file_path = _map_to_ast_path(base_data_dir, file_name, student_id, homework_id, mid_data_path, homework_ids, version)
    
    if not os.path.exists(source_file_path) or not os.path.exists(ast_file_path):
        return "", ""
    
    try:
        # 1. Load AST to find method node (AST coordinates are logical coordinates, used directly)
        ast = load_ast_file(ast_file_path)
        method_node, method_name = _find_containing_method_with_name(ast, start, end)
        if not method_node:
            return "", ""
        
        # 2. Extract code using logical coordinate -> physical offset mapping
        method_code = extract_code_by_logical_position(
            source_file_path, 
            method_node['start'], 
            method_node['end'],
            snap_to_boundary=True  # Stick to full method boundaries
        )
        return method_code, method_name
        
    except Exception as e:
        print(f"  [WARN] _extract_method_code error: {e}")
        return "", ""
    
def _extract_change_code(base_data_dir: str, mid_data_path: list, homework_ids: list, 
                         file_name: str, student_id: str, homework_id: str, 
                         start: int, end: int, version: str) -> Tuple[str, str]:
    """
    Extract changed code snippet based on logical coordinates (fixed coordinate mapping)
    Returns:
        (change_code, method_name)  # The second return value is retained for compatibility, actual value is None
    """
    source_file_path = _map_to_source_code_path(base_data_dir, file_name, student_id, homework_id, version)
    ast_file_path = _map_to_ast_path(base_data_dir, file_name, student_id, homework_id, mid_data_path, homework_ids, version)
    
    if not os.path.exists(source_file_path) or not os.path.exists(ast_file_path):
        return "", None
    
    try:
        # 1. Load AST to find method node containing the change (used for returning method name)
        ast = load_ast_file(ast_file_path)
        method_node, method_name = _find_containing_method_with_name(ast, start, end)
        
        # 2. Extract change snippet using logical coordinate -> physical offset mapping
        change_code = extract_code_by_logical_position(
            source_file_path, 
            start, 
            end,
            snap_to_boundary=False  # The change snippet does not need to stick to method boundaries
        )
        return change_code, method_name
        
    except Exception as e:
        print(f"  [WARN] _extract_change_code error: {e}")
        return "", None

def _find_method_in_version(base_data_dir: str, mid_data_path: list, homework_ids: list, 
                            file_name: str, student_id: str, homework_id: str, 
                            method_name: str, version: str) -> str:
    """
    In the specified version, find method code based on method name (fixed coordinate mapping)
    """
    source_file_path = _map_to_source_code_path(base_data_dir, file_name, student_id, homework_id, version)
    ast_file_path = _map_to_ast_path(base_data_dir, file_name, student_id, homework_id, mid_data_path, homework_ids, version)
    
    if not os.path.exists(source_file_path) or not os.path.exists(ast_file_path):
        return ""
    try:
        # 1. Load AST to find method node
        ast = load_ast_file(ast_file_path)
        method_node = _find_method_by_name(ast, method_name)
        if not method_node:
            print(f"  -> Method '{method_name}' not found in AST of {ast_file_path}")
            return ""
        
        # 2. Extract code using logical coordinate -> physical offset mapping
        method_code = extract_code_by_logical_position(
            source_file_path,
            method_node['start'],
            method_node['end'],
            snap_to_boundary=True
        )
        return method_code
        
    except Exception as e:
        print(f"  -> Error finding method '{method_name}' in {ast_file_path}: {e}")
        return ""

def _find_containing_method_with_name(ast_node: Dict[str, Any], target_start: int, target_end: int) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Find MethodDeclaration node in AST that contains [target_start, target_end] range, and return its method name.
    Returns:
        (method_node, method_name)
    """
    #Check if current node is MethodDeclaration and contains target range
    if (ast_node.get('node_type') == 'MethodDeclaration' and 
        ast_node['start'] <= target_start and target_end <= ast_node['end']):
        # --- Key Fix: Correctly parse SimpleName ---
        method_name = ""
        for child in ast_node.get('children', []):
            if child.get('node_type') == 'SimpleName':
                # Method name is in the 'content' field of SimpleName node
                raw_content = child.get('content', '').strip()
                # Try two formats:
                # Format1: "Lexer" -> Use directly
                # Format2: "SimpleName: Lexer" -> Take the second part after splitting
                if raw_content.startswith('SimpleName:'):
                    method_name = raw_content.split(':', 1)[1].strip()
                else:
                    method_name = raw_content
                break
        return ast_node, method_name

    # Recursively check child nodes
    for child in ast_node.get('children', []):
        result_node, result_name = _find_containing_method_with_name(child, target_start, target_end)
        if result_node:
            return result_node, result_name

    return None, ""


def _find_method_by_name(ast_node: Dict[str, Any], target_method_name: str) -> Optional[Dict[str, Any]]:
    """
    Find MethodDeclaration node with specified name in AST.
    """
    if ast_node.get('node_type') == 'MethodDeclaration':
        # --- Key Fix: Use the same logic to extract method name ---
        for child in ast_node.get('children', []):
            if child.get('node_type') == 'SimpleName':
                raw_content = child.get('content', '').strip()
                if raw_content.startswith('SimpleName:'):
                    extracted_name = raw_content.split(':', 1)[1].strip()
                else:
                    extracted_name = raw_content
                
                if extracted_name == target_method_name:
                    return ast_node
                break
    
    for child in ast_node.get('children', []):
        result = _find_method_by_name(child, target_method_name)
        if result:
            return result
    
    return None

def batch_process_txt(source_dir: str, dest_dir: str, replacement_file: str):
    """Batch process txt files:
- Files starting with 'case': replace the content between '# Grammar Specification' and '## Code Modification'
- Other files: copy directly to the target folder"""
    # 1. Read replacement content
    repl_path = Path(replacement_file)
    if not repl_path.is_file():
        raise FileNotFoundError(f"❌ Replacement file not found: {replacement_file}")
    new_content = repl_path.read_text(encoding='utf-8').strip()

    # 2. Ensure target folder exists
    dest_path = Path(dest_dir)
    dest_path.mkdir(parents=True, exist_ok=True)

    # 3. Compile regex
    pattern = re.compile(
        r'(#\s*Grammar Specification).*?(##\s*Code Modification)',
        re.DOTALL | re.IGNORECASE,
    )
    source_path = Path(source_dir)
    if not source_path.is_dir():
        raise NotADirectoryError(f"❌ Source folder does not exist: {source_dir}")

    modified_count = 0
    copied_count = 0

    # Replace callback function: keep start and end markers, insert new content in between
    def repl_func(match):
        return f"{match.group(1)}\n{new_content}\n{match.group(2)}"

    for txt_file in source_path.glob('*.txt'):
        try:
            content = txt_file.read_text(encoding='utf-8')
            dest_file = dest_path / txt_file.name

            if txt_file.name.startswith('case'):
                # Only attempt replacement for files starting with case
                if pattern.search(content):
                    modified_content = pattern.sub(repl_func, content)
                    print(f"✅ Replaced: {txt_file.name}")
                else:
                    modified_content = content
                    print(f"⚠️ Markers not found, saved as is: {txt_file.name}")
                
                dest_file.write_text(modified_content, encoding='utf-8')
                modified_count += 1
            else:
                # Other files are copied directly
                dest_file.write_text(content, encoding='utf-8')
                print(f"📄 Copied: {txt_file.name}")
                copied_count += 1

        except UnicodeDecodeError:
            print(f"❌ Encoding error {txt_file.name}: Please ensure file is UTF-8 encoded")
        except Exception as e:
            print(f"❌ Error processing {txt_file.name} occurred: {e}")

    print(f"\n🎉 Processing complete! Replaced: {modified_count} items | Copied: {copied_count} item")


def parse_args():
    parser = argparse.ArgumentParser(description="Generate HiReTest LLM prompts from positive prediction Excel.")
    parser.add_argument("--excel", default=str(PROJECT_ROOT / "outputs" / "positive_predictions.xlsx"))
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "repair_prompts"),
        help="Output prompt root used by ask_for_llm.py.",
    )
    parser.add_argument("--data-root", default=str(PROJECT_ROOT))
    parser.add_argument("--prompt-dir", default=str(PROMPT_DIR))
    parser.add_argument(
        "--assignment-ids",
        default=os.environ.get("HIRETEST_ASSIGNMENT_SEQUENCE"),
        required=not bool(os.environ.get("HIRETEST_ASSIGNMENT_SEQUENCE")),
        help="Comma-separated ordered assignment IDs.",
    )
    parser.add_argument(
        "--transition-dirs",
        default=os.environ.get("HIRETEST_TRANSITION_DIRS"),
        required=not bool(os.environ.get("HIRETEST_TRANSITION_DIRS")),
        help="Comma-separated diff directories for the five transitions.",
    )
    parser.add_argument("--info-type", choices=["total", "piece"], default="total")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    PROMPT_DIR = Path(args.prompt_dir).resolve()
    homework_ids = [item.strip() for item in args.assignment_ids.split(",") if item.strip()]
    transition_dirs = [item.strip() for item in args.transition_dirs.split(",") if item.strip()]
    mid_data_path = [""] + transition_dirs
    if len(homework_ids) != len(test_case_ids):
        raise ValueError("--assignment-ids must contain six ordered IDs for five transitions")
    if len(transition_dirs) != len(test_case_ids) - 1:
        raise ValueError("--transition-dirs must contain five directories")
    extract_and_save_method_contexts(args.excel, args.output, args.data_root, args.info_type)
