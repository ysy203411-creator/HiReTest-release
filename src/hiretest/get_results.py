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
RELEASE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(os.environ.get("HIRETEST_DERIVED_DATA_ROOT", RELEASE_ROOT / "data" / "restricted"))
PROMPT_DIR = PROJECT_ROOT / "prompt"
# mid_data_path = ["", "mid_data_1852_1854", "mid_data_1854_1856", "mid_data_1856_1858","mid_data_1858_1859","mid_data_1859_1860"]
# homework_ids = ["1852","1854","1856","1858","1859","1860"]
mid_data_path = ["", "mid_data_1527_1526", "mid_data_1526_1641", "mid_data_1641_1681","mid_data_1681_1682","mid_data_1682_1705"]
homework_ids = ["1527","1526","1641","1681","1682","1705"]
test_case_ids = ["","1to2","2to3","3to4","4to5","5to6"]
prompt_header = "full_prompt" #prompt


def logical_to_physical_offset(file_path: str, log_start: int, log_end: int) -> Tuple[int, int]:
    """
    将 GumTree TextDiff 的逻辑字符索引映射为原始文件的物理字节偏移。
    
    GumTree TextDiff 规则：
    - \r\n 计为 1 个逻辑字符（归一化为 \n）
    - 其他字符各计为 1
    
    Args:
        file_path: 源代码文件路径
        log_start: TextDiff 输出的起始逻辑位置
        log_end: TextDiff 输出的结束逻辑位置
    
    Returns:
        (phys_start, phys_end): 原始文件中的字节偏移量 [start, end)
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
        
        # \r\n 在逻辑中计为 1 步，物理中占 2 字节
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
    根据 TextDiff 逻辑坐标从源代码文件中提取代码片段。
    
    Args:
        file_path: 源代码文件路径
        log_start: TextDiff 起始位置
        log_end: TextDiff 结束位置
        snap_to_boundary: 是否智能吸附到完整语法边界（解决 ±1 截断问题）
    
    Returns:
        提取的代码字符串
    """
    if log_start == -1 or log_end == -1:
        return ""
    
    phys_start, phys_end = logical_to_physical_offset(file_path, log_start, log_end)
    
    with open(file_path, 'rb') as f:
        raw = f.read()
    
    if snap_to_boundary:
        # 向前扫修饰符
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
        
        # 向后找闭合 }
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
    base_data_dir: str,  # 新增参数：数据根目录，用于查找源文件
    info_type: str
):
    """
    根据预测结果Excel文件，提取每条数据变更前后所在方法的代码，并保存为去重后的txt文件。

    Args:
        excel_path (str): 输入的Excel文件路径
        output_dir (str): 输出目录
        string_template (str): 用于格式化输出的模板字符串
        base_data_dir (str): 数据根目录 (e.g., 'HiReTest/data')
    """
    # 1. 加载Excel数据
    df = pd.read_excel(excel_path)
    print(f"Loaded {len(df)} predicted positive samples from {excel_path}.")

    # --- 关键修改：按 homework_id 分组 ---
    # 2. 按 '课程id' (homework_id) 分组
    grouped = df.groupby('课程id')
    print(f"Found {len(grouped)} unique homework_ids: {list(grouped.groups.keys())}")

    # 3. 遍历每个 homework_id 组
    for homework_id, group_df in grouped:
        homework_id = str(homework_id)
        # if homework_id == '1854':
        #     index = 1
        # elif homework_id == '1856':
        #     index = 2
        # elif homework_id == '1858':
        #     index = 3
        # elif homework_id == '1859':
        #     index = 4
        # elif homework_id == '1860':
        #     index = 5
        if homework_id == '1526':
            index = 1
        elif homework_id == '1641':
            index = 2
        elif homework_id == '1681':
            index = 3
        elif homework_id == '1682':
            index = 4
        elif homework_id == '1705':
            index = 5

        print(f"\nProcessing homework_id: {homework_id} ({len(group_df)} samples)")
        
        # 3.1 为当前 homework_id 创建专属输出目录
        homework_output_dir = os.path.join(output_dir, test_case_ids[index])
        os.makedirs(homework_output_dir, exist_ok=True)

        # 3.2 初始化用于存储 (method_code_pair, formatted_string) 的列表
        results_to_dedup = []

        # 3.3 遍历当前组的每一行
        for idx, row in group_df.iterrows():
            try:
                file_name = row['文件路径']
                student_id = str(row['学生id'])
                # homework_id 已从分组中获取
                old_pos_str = row['代码变更修改前的位置']
                new_pos_str = row['代码变更修改后的位置']
                
                # 解析位置字符串
                old_start, old_end = parse_position_string(old_pos_str)
                new_start, new_end = parse_position_string(new_pos_str)

                # 提取方法代码
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
                # 生成格式化字符串
                with open(PROMPT_DIR / f'prompt_{index}to{index+1}.txt','r',encoding='utf-8') as file:
                    template = file.read()

                if prompt_header == "prompt":
                    with open(PROMPT_DIR / f'constraint_{index}to{index+1}.txt','r',encoding='utf-8') as file:
                        constraint_content = file.read()
                elif prompt_header == "full_prompt":
                    with open(PROMPT_DIR / f'raw_constraint_{index}to{index+1}.txt','r',encoding='utf-8') as file:
                        constraint_content = file.read()
                else:
                    print("error! prompt not found")

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

        # 3.4 对当前 homework_id 的结果去重
        dedup_dict = {}
        for key, formatted_str in results_to_dedup:
            if key not in dedup_dict:
                dedup_dict[key] = formatted_str

        unique_strings = list(dedup_dict.values())
        print(f"  -> Generated {len(results_to_dedup)} strings, {len(unique_strings)} unique.")

        # 3.5 保存到当前 homework_id 的文件夹
        for i, s in enumerate(unique_strings, start=1):
            output_file = os.path.join(homework_output_dir, f"case{i}.txt")
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(s)
        
        print(f"  -> Saved {len(unique_strings)} unique cases to '{homework_output_dir}'.")

    print(f"\nAll processing finished. Results are saved under '{output_dir}'.")


def parse_position_string(pos_str: str) -> Tuple[int, int]:
    """解析位置字符串如 '[123, 456]' 或 '[-1, -1]'，返回 (start, end)。"""
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
    """根据 homework_id 获取在 homework_ids 中的索引。"""
    return homework_ids.index(homework_id)

def _map_to_source_code_path(base_data_dir: str, file_name: str, student_id: str, homework_id: str, version: str) -> str:
    """映射到源代码文件路径。"""
    source_version_dir = 'first' if version == 'old' else 'last'
    return os.path.join(base_data_dir, 'data', student_id, homework_id, source_version_dir, file_name)

def _map_to_ast_path(base_data_dir: str, file_name: str, student_id: str, homework_id: str, mid_data_path: list, homework_ids: list, version: str) -> str:
    """映射到 AST 文件路径。"""
    hw_idx = _get_homework_index(homework_id, homework_ids)
    mid_data_dir_name = mid_data_path[hw_idx]
    ast_version_num = '2' if version == 'old' else '3'
    return os.path.join(base_data_dir, mid_data_dir_name, student_id, homework_id, ast_version_num, file_name + '.txt')

def _extract_method_code(base_data_dir: str, mid_data_path: list, homework_ids: list, 
                         file_name: str, student_id: str, homework_id: str, 
                         start: int, end: int, version: str) -> Tuple[str, str]:
    """
    根据逻辑坐标提取方法代码和方法名（已修复坐标映射）
    Returns:
        (method_code, method_name)
    """
    source_file_path = _map_to_source_code_path(base_data_dir, file_name, student_id, homework_id, version)
    ast_file_path = _map_to_ast_path(base_data_dir, file_name, student_id, homework_id, mid_data_path, homework_ids, version)
    
    if not os.path.exists(source_file_path) or not os.path.exists(ast_file_path):
        return "", ""
    
    try:
        # 1. 加载 AST 查找方法节点（AST 坐标是逻辑坐标，直接使用）
        ast = load_ast_file(ast_file_path)
        method_node, method_name = _find_containing_method_with_name(ast, start, end)
        if not method_node:
            return "", ""
        
        # 2. 使用逻辑坐标 -> 物理偏移映射提取代码
        method_code = extract_code_by_logical_position(
            source_file_path, 
            method_node['start'], 
            method_node['end'],
            snap_to_boundary=True  # 吸附到完整方法边界
        )
        return method_code, method_name
        
    except Exception as e:
        print(f"  [WARN] _extract_method_code error: {e}")
        return "", ""
    
def _extract_change_code(base_data_dir: str, mid_data_path: list, homework_ids: list, 
                         file_name: str, student_id: str, homework_id: str, 
                         start: int, end: int, version: str) -> Tuple[str, str]:
    """
    根据逻辑坐标提取变更代码片段（已修复坐标映射）
    Returns:
        (change_code, method_name)  # 第二个返回值保留兼容，实际为 None
    """
    source_file_path = _map_to_source_code_path(base_data_dir, file_name, student_id, homework_id, version)
    ast_file_path = _map_to_ast_path(base_data_dir, file_name, student_id, homework_id, mid_data_path, homework_ids, version)
    
    if not os.path.exists(source_file_path) or not os.path.exists(ast_file_path):
        return "", None
    
    try:
        # 1. 加载 AST 查找包含变更的方法节点（用于返回方法名）
        ast = load_ast_file(ast_file_path)
        method_node, method_name = _find_containing_method_with_name(ast, start, end)
        
        # 2. 使用逻辑坐标 -> 物理偏移映射提取变更片段
        change_code = extract_code_by_logical_position(
            source_file_path, 
            start, 
            end,
            snap_to_boundary=False  # 变更片段不需要吸附到方法边界
        )
        return change_code, method_name
        
    except Exception as e:
        print(f"  [WARN] _extract_change_code error: {e}")
        return "", None

def _find_method_in_version(base_data_dir: str, mid_data_path: list, homework_ids: list, 
                            file_name: str, student_id: str, homework_id: str, 
                            method_name: str, version: str) -> str:
    """
    在指定版本中，根据方法名查找方法代码（已修复坐标映射）
    """
    source_file_path = _map_to_source_code_path(base_data_dir, file_name, student_id, homework_id, version)
    ast_file_path = _map_to_ast_path(base_data_dir, file_name, student_id, homework_id, mid_data_path, homework_ids, version)
    
    if not os.path.exists(source_file_path) or not os.path.exists(ast_file_path):
        return ""
    try:
        # 1. 加载 AST 查找方法节点
        ast = load_ast_file(ast_file_path)
        method_node = _find_method_by_name(ast, method_name)
        if not method_node:
            print(f"  -> Method '{method_name}' not found in AST of {ast_file_path}")
            return ""
        
        # 2. 使用逻辑坐标 -> 物理偏移映射提取代码
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
    在 AST 中查找包含 [target_start, target_end] 范围的 MethodDeclaration 节点，并返回其方法名。
    Returns:
        (method_node, method_name)
    """
    # 检查当前节点是否是 MethodDeclaration 且包含目标范围
    if (ast_node.get('node_type') == 'MethodDeclaration' and 
        ast_node['start'] <= target_start and target_end <= ast_node['end']):
        # --- 关键修正：正确解析 SimpleName ---
        method_name = ""
        for child in ast_node.get('children', []):
            if child.get('node_type') == 'SimpleName':
                # 方法名在 SimpleName 节点的 'content' 字段中
                raw_content = child.get('content', '').strip()
                # 尝试两种格式：
                # 格式1: "Lexer" -> 直接使用
                # 格式2: "SimpleName: Lexer" -> 分割后取第二部分
                if raw_content.startswith('SimpleName:'):
                    method_name = raw_content.split(':', 1)[1].strip()
                else:
                    method_name = raw_content
                break
        return ast_node, method_name

    # 递归检查子节点
    for child in ast_node.get('children', []):
        result_node, result_name = _find_containing_method_with_name(child, target_start, target_end)
        if result_node:
            return result_node, result_name

    return None, ""


def _find_method_by_name(ast_node: Dict[str, Any], target_method_name: str) -> Optional[Dict[str, Any]]:
    """
    在 AST 中查找指定名称的 MethodDeclaration 节点。
    """
    if ast_node.get('node_type') == 'MethodDeclaration':
        # --- 关键修正：使用相同的逻辑提取方法名 ---
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
    """
    批量处理 txt 文件：
    - 以 'case' 开头的文件：替换 '#文法规范' 与 '##代码修改' 之间的内容
    - 其他文件：直接原样复制到目标文件夹
    """
    # 1. 读取替换内容
    repl_path = Path(replacement_file)
    if not repl_path.is_file():
        raise FileNotFoundError(f"❌ 替换文件未找到: {replacement_file}")
    new_content = repl_path.read_text(encoding='utf-8').strip()

    # 2. 确保目标文件夹存在
    dest_path = Path(dest_dir)
    dest_path.mkdir(parents=True, exist_ok=True)

    # 3. 编译正则
    pattern = re.compile(r'(#文法规范).*?(##代码修改)', re.DOTALL)
    source_path = Path(source_dir)
    if not source_path.is_dir():
        raise NotADirectoryError(f"❌ 源文件夹不存在: {source_dir}")

    modified_count = 0
    copied_count = 0

    # 替换回调函数：保留首尾标记，中间插入新内容
    def repl_func(match):
        return f"{match.group(1)}\n{new_content}\n{match.group(2)}"

    for txt_file in source_path.glob('*.txt'):
        try:
            content = txt_file.read_text(encoding='utf-8')
            dest_file = dest_path / txt_file.name

            if txt_file.name.startswith('case'):
                # 仅对 case 开头的文件尝试替换
                if pattern.search(content):
                    modified_content = pattern.sub(repl_func, content)
                    print(f"✅ 已替换: {txt_file.name}")
                else:
                    modified_content = content
                    print(f"⚠️ 未找到标记，已原样保存: {txt_file.name}")
                
                dest_file.write_text(modified_content, encoding='utf-8')
                modified_count += 1
            else:
                # 其他文件直接复制
                dest_file.write_text(content, encoding='utf-8')
                print(f"📄 已复制: {txt_file.name}")
                copied_count += 1

        except UnicodeDecodeError:
            print(f"❌ 编码错误 {txt_file.name}: 请确保文件为 UTF-8 编码")
        except Exception as e:
            print(f"❌ 处理 {txt_file.name} 时发生异常: {e}")

    print(f"\n🎉 处理完成！替换: {modified_count} 个 | 复制: {copied_count} 个")


def parse_args():
    parser = argparse.ArgumentParser(description="Generate HiReTest LLM prompts from positive prediction Excel.")
    parser.add_argument("--excel", default=str(PROJECT_ROOT / "positive_predictions1.xlsx"))
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "test_case_prompt_regenerated"),
        help="Output prompt root. Defaults to a regenerated directory to avoid overwriting test_case_prompt/.",
    )
    parser.add_argument("--data-root", default=str(PROJECT_ROOT / "data"))
    parser.add_argument("--prompt-dir", default=str(PROMPT_DIR))
    parser.add_argument("--info-type", choices=["total", "piece"], default="total")
    parser.add_argument("--constraint-mode", choices=["prompt", "full_prompt"], default=prompt_header)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    PROMPT_DIR = Path(args.prompt_dir).resolve()
    prompt_header = args.constraint_mode
    extract_and_save_method_contexts(args.excel, args.output, args.data_root, args.info_type)

    # 替换测试用例约束（原来的记录识别结果的excel文件好像被覆盖了，想要用那一版的结果只能这样了
    # SOURCE_FOLDER = str(PROJECT_ROOT / "test_case_prompt" / "5to6")
    # DEST_FOLDER   = str(PROJECT_ROOT / "test_case_prompt_regenerated" / "5to6")
    # REPLACEMENT_FILE = str(PROJECT_ROOT / "prompt" / "raw_constraint_5to6.txt")
    # batch_process_txt(SOURCE_FOLDER, DEST_FOLDER, REPLACEMENT_FILE)
