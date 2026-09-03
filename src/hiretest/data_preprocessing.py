import os
from typing import List, Dict, Tuple, Set, Optional
import re
import pickle
import pandas as pd
from collections import defaultdict
import argparse
from pathlib import Path

# 全局变量
PROJECT_ROOT = Path(__file__).resolve().parent
root_path = str(PROJECT_ROOT)
mid_data_path = ["", "mid_data_1527_1526","mid_data_1526_1641","mid_data_1641_1681","mid_data_1681_1682","mid_data_1682_1705"]  # 存放mid文件夹路径
excel_name = ["","1to2_new","2to3","3to4","4to5","5to6"]
homework_ids = ["1527","1526","1641","1681","1682","1705"]   # 存放作业id
#mid_data_path = ["", "mid_data_1852_1854", "mid_data_1854_1856","mid_data_1856_1858","mid_data_1858_1859","mid_data_1859_1860"]
#homework_ids = ["1852","1854","1856","1858","1859","1860"]
folder_name = "data"
DATA_ROOT = PROJECT_ROOT / folder_name

# 声明类型列表
declaration_names = ["VariableDeclarationFragment", "FieldDeclaration", "VariableDeclarationStatement",
                    "MethodDeclaration", "decl_stmt", "function_decl", "function", "struct", "typedef",
                    "SingleVariableDeclaration", "TypeDeclaration"]

# 存储所有变更数据的列表
all_change_data = []

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
        # 记录命中位置
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
    
    # 边界兜底
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
    
    # 1. 逻辑坐标 -> 物理偏移
    phys_start, phys_end = logical_to_physical_offset(file_path, log_start, log_end)
    
    # 2. 读取原始文件（二进制模式保留 \r\n）
    with open(file_path, 'rb') as f:
        raw = f.read()
    
    # 3. 智能边界吸附（可选，解决 GumTree 区间开闭惯例导致的 ±1 误差）
    if snap_to_boundary:
        # 向前最多扫 50 字节，找 public/private/protected/class 等修饰符
        scan_back = max(0, phys_start - 50)
        window = raw[scan_back:phys_start]
        for kw in [b'public ', b'private ', b'protected ', b'static ', b'class ', b'interface ']:
            idx = window.rfind(kw)
            if idx != -1:
                phys_start = scan_back + idx
                break
        else:
            # 没找到修饰符，回退到上一行行首
            nl = window.rfind(b'\n')
            if nl != -1:
                phys_start = scan_back + nl + 1
        
        # 向后找闭合 } 并清理尾部空白
        scan_fwd = min(len(raw), phys_end + 100)
        window_fwd = raw[phys_end:scan_fwd]
        brace = window_fwd.find(b'}')
        if brace != -1:
            phys_end = phys_end + brace + 1
        # 跳过末尾连续空白
        while phys_end < len(raw) and raw[phys_end:phys_end+1] in b' \t\r\n':
            phys_end += 1
    
    # 4. 提取并解码
    try:
        return raw[phys_start:phys_end].decode('utf-8', errors='ignore')
    except:
        return ""

def load_ast_file(file_path: str) -> Dict:
    """
    解析 AST 文件（缩进格式）为嵌套字典树
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # 构建 (行内容, 缩进层级) 列表
    nodes = []
    for line in lines:
        if not line.strip():
            continue
        # 计算缩进层级（每4个空格为一级）
        indent = len(line) - len(line.lstrip(' '))
        level = indent // 4
        content = line.strip()
        nodes.append((content, level))
    
    # 递归构建树
    def build_tree(nodes, start_idx, current_level):
        if start_idx >= len(nodes):
            return None, start_idx
        
        content, level = nodes[start_idx]
        if level != current_level:
            return None, start_idx
        
        # 解析当前节点
        node = parse_ast_node_line(content)
        children = []
        next_idx = start_idx + 1
        
        # 收集所有子节点
        while next_idx < len(nodes):
            child, next_idx = build_tree(nodes, next_idx, current_level + 1)
            if child is None:
                break
            children.append(child)
        
        node['children'] = children
        return node, next_idx
    
    root, _ = build_tree(nodes, 0, 0)
    return root

def parse_ast_node_line(line: str) -> Dict:
    line = line.strip()
    match = re.match(r'^(\S+)(?::\s*(.*?))?\s*\[([0-9]+),([0-9]+)\]\s*$', line)
    if not match:
        # 无法解析时，安全回退
        return {'node_type': line, 'content': '', 'start': -1, 'end': -1}
    
    node_type = match.group(1)
    content = (match.group(2) or '').strip()  # group(2) 可能是 None
    start = int(match.group(3))
    end = int(match.group(4))
    
    return {
        'node_type': node_type,
        'content': content,
        'start': start,
        'end': end
    }

def find_parent_in_ast(ast_root: Dict, target_start: int, target_end: int) -> Optional[Dict]:
    """
    在 AST 中查找包含 [target_start, target_end] 的最小父节点
    """
    def dfs(node):
        if node is None:
            return None
        
        # 检查当前节点是否包含目标范围
        if node['start'] <= target_start and target_end <= node['end']:
            # 检查子节点是否也包含（找最小的）
            for child in node.get('children', []):
                if child['start'] <= target_start and target_end <= child['end']:
                    result = dfs(child)
                    if result:
                        return result
            return node
        return None
    
    return dfs(ast_root)

def merge_adjacent_changes(changes: List[Dict]) -> List[Dict]:
    """
    合并相邻的代码变更
    """
    # 简化实现：将所有变更视为一个整体进行处理
    if not changes:
        return []
    
    # 实际的合并逻辑需要根据AST结构来判断哪些变更是相邻的
    # 这里返回原列表，实际合并需要更复杂的AST分析
    return changes

def filter_changes(new_changes: List[Dict], old_changes: List[Dict], 
                  student_id: str, homework_id: str, file_name: str) -> List[Dict]:
    """
    根据过滤规则过滤变更
    """
    filtered_changes = []
    for change in new_changes:
        # 规则1: 过滤掉在旧旧→旧变更中新增的节点
        filtered_change = remove_newly_added_nodes(change, old_changes)
        
        if filtered_change is None:  # 如果根节点被删除了
            continue
            
        # 规则2: 如果所有变更节点类型都是声明类型，排除（不考虑根节点）
        if is_declaration_only_change(filtered_change):
            continue
            
        # 规则3: 如果涉及行数超过50行，排除
        if get_line_count(filtered_change, student_id, homework_id, file_name) > 50:
            continue
            
        filtered_changes.append(filtered_change)
    
    return filtered_changes

def remove_newly_added_nodes(change: Dict, old_changes: List[Dict]) -> Dict:
    """
    移除在旧旧→旧变更中新增的节点，保留其他节点
    """
    def filter_node_recursive(node: Dict) -> Dict:
        # 检查当前节点是否是新增的
        if is_newly_added_node_single(node, old_changes):
            return None  # 删除这个节点
        
        # 递归过滤子节点
        filtered_children = []
        for child in node['children']:
            filtered_child = filter_node_recursive(child)
            if filtered_child is not None:
                filtered_children.append(filtered_child)
        
        # 如果节点不是新增的，但所有子节点都被删除了，且子节点的变更类型都是新增，也要删除该节点
        if filtered_children:
            # 有保留的子节点，保留当前节点
            node_copy = node.copy()
            node_copy['children'] = filtered_children
            return node_copy
        else:
            # 没有保留的子节点，检查是否需要删除当前节点
            # 如果原节点有子节点，但现在没有了，说明所有子节点都是新增的
            if node['children']:  # 原来有子节点，现在都没了
                return None
            else:
                # 原来就没有子节点，保留当前节点
                node_copy = node.copy()
                node_copy['children'] = []
                return node_copy
    
    return filter_node_recursive(change)

def is_newly_added_node_single(node: Dict, old_changes: List[Dict]) -> bool:
    """
    检查单个节点是否在旧旧→旧的变更中是新增的
    """
    for old_change in old_changes:
        if old_change.get('change_type') == 'insert':
            # 如果旧旧→旧中有插入操作，检查当前节点是否是这些插入的节点之一
            if is_overlapping_position_node(node, old_change):
                return True
    return False

def is_overlapping_position_node(node: Dict, change_info: Dict) -> bool:
    """
    检查节点位置与变更信息位置是否重叠
    """
    # 检查位置范围是否重叠
    return not (node['old_start'] > change_info['old_end'] or 
                node['old_end'] < change_info['old_start'])

def is_declaration_only_change(change: Dict) -> bool:
    """
    检查变更是否只涉及声明类型的节点（不考虑根节点）
    """
    def check_node_types(node: Dict) -> bool:
        # 检查当前节点类型是否是声明类型
        if node['node_type'] in declaration_names:
            # 检查子节点是否也都是声明类型
            if node['children']:
                return all(check_node_types(child) for child in node['children'])
            else:
                return True
        return False
    
    # 不检查根节点，只检查子节点
    if change['children']:
        return all(check_node_types(child) for child in change['children'])
    return False

def get_line_count(change: Dict, student_id: str, homework_id: str, file_name: str) -> int:
    """
    计算变更涉及的行数
    """
    # 需要读取源代码文件来计算行数
    # 构建源代码路径（新版本代码）
    code_path = DATA_ROOT / "data" / student_id / homework_id / "last" / file_name.replace('.txt', '')
    
    code_file = str(code_path)
    
    if not os.path.exists(code_file):
        return 0  # 如果找不到源代码，返回0
    
    try:
        with open(code_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 计算变更涉及的行数范围
        start_line = get_line_number_from_position(lines, change['start_pos'])
        end_line = get_line_number_from_position(lines, change['end_pos'])
        
        if start_line != -1 and end_line != -1:
            return end_line - start_line + 1
        else:
            return 0
    except:
        return 0

def get_line_number_from_position(lines: List[str], position: int) -> int:
    """
    根据字符位置获取行号（基于文本模式读取的行列表）
    
    注意：此函数假设 lines 是通过 read_code_file() 读取的，
    每行已包含原始换行符，位置计算基于原始文件字节偏移。
    """
    if position == -1:  # 删除的节点
        return -1
    
    current_pos = 0
    for i, line in enumerate(lines):
        line_length = len(line)  # 直接使用原始长度，不再 +1
        if current_pos <= position < current_pos + line_length:
            return i + 1
        current_pos += line_length
    
    return -1

def is_overlapping_position(change1: Dict, change2: Dict) -> bool:
    """
    检查两个变更的位置是否有重叠
    """
    # 检查位置范围是否重叠
    return not (change1['start_pos'] > change2['end_pos'] or 
                change1['end_pos'] < change2['start_pos'])

def read_code_file(file_path: str) -> List[str]:
    """
    读取代码文件（文本模式，用于行数统计等不依赖精确位置的场景）
    """
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.readlines()
        except:
            print(f"read {file_path} error")
    else:
        print(f"{file_path} not exist")
    return []


def read_code_file_raw(file_path: str) -> bytes:
    """
    [新增] 以二进制模式读取源代码，保留原始 \r\n 换行符
    用于需要精确字符位置映射的场景（如 GumTree TextDiff 坐标提取）
    """
    if os.path.exists(file_path):
        try:
            with open(file_path, 'rb') as f:
                return f.read()
        except:
            print(f"read {file_path} error")
    else:
        print(f"{file_path} not exist")
    return b""

def calculate_change_lines(change: Dict, old_code_lines: List[str], new_code_lines: List[str]) -> int:
    """
    计算变更涉及的行数（新旧版本取高者），基于子节点范围计算
    """
    # 获取所有子节点涉及的行数
    old_lines_set = set()
    new_lines_set = set()
    
    def collect_lines_recursive(node: Dict):
        # 收集当前节点的行号
        old_start_line = get_line_number_from_position(old_code_lines, node['old_start'])
        old_end_line = get_line_number_from_position(old_code_lines, node['old_end'])
        new_start_line = get_line_number_from_position(new_code_lines, node['start_pos'])
        new_end_line = get_line_number_from_position(new_code_lines, node['end_pos'])
        
        # 添加旧版本涉及的行号
        if old_start_line != -1 and old_end_line != -1:
            for line_num in range(old_start_line, old_end_line + 1):
                old_lines_set.add(line_num)
        
        # 添加新版本涉及的行号  
        if new_start_line != -1 and new_end_line != -1:
            for line_num in range(new_start_line, new_end_line + 1):
                new_lines_set.add(line_num)
        
        # 递归处理子节点
        for child in node['children']:
            collect_lines_recursive(child)
    
    # 从根节点开始收集所有涉及的行号
    collect_lines_recursive(change)
    
    # 计算行数（取新旧版本涉及行数的最大值）
    old_lines_count = len(old_lines_set)
    new_lines_count = len(new_lines_set)
    
    return max(old_lines_count, new_lines_count)

def get_function_class_length(change: Dict, old_code_lines: List[str], new_code_lines: List[str]) -> int:
    """
    获取所在函数/类的长度（新旧版本取高者）
    """
    # 这里需要根据AST结构找到包含当前变更的函数或类的范围
    # 简化实现：返回整个文件的长度作为示例
    return max(len(old_code_lines), len(new_code_lines))

def get_avg_change_lines_in_scope(change: Dict, old_code_lines: List[str], new_code_lines: List[str]) -> float:
    """
    计算所在域变更的平均行数
    """
    # 这里需要找到同一函数/类内的所有变更并计算平均值
    # 简化实现：返回当前变更的行数
    return calculate_change_lines(change, old_code_lines, new_code_lines)

def determine_change_type(change: Dict) -> str:
    """
    确定变更类型：插入/删除/更新/修改
    """
    # 统计各种变更类型的数量
    insert_count = 0
    delete_count = 0
    update_count = 0
    other_count = 0
    
    def count_change_types(node: Dict):
        nonlocal insert_count, delete_count, update_count, other_count
        
        if node['change_type'] == 'insert':
            insert_count += 1
        elif node['change_type'] == 'delete':
            delete_count += 1
        elif node['change_type'] == 'update':
            update_count += 1
        else:
            other_count += 1
        
        for child in node['children']:
            count_change_types(child)
    
    count_change_types(change)
    
    total_changes = insert_count + delete_count + update_count + other_count
    
    if total_changes == 0:
        return '修改'
    
    # 只有插入
    if insert_count > 0 and delete_count == 0 and update_count == 0 and other_count == 0:
        return '插入'
    
    # 只有删除
    if delete_count > 0 and insert_count == 0 and update_count == 0 and other_count == 0:
        return '删除'
    
    # 只有更新
    if update_count > 0 and insert_count == 0 and delete_count == 0 and other_count == 0:
        return '更新'
    
    # 其他情况
    return '修改'

def get_syntax_structures(change: Dict) -> List[str]:
    """
    获取变更涉及的语法结构（根节点和子节点类型）
    """
    structures = [change['node_type']]
    
    # 添加子节点类型
    for child in change['children']:
        structures.append(child['node_type'])
    
    return structures

def check_method_signature_change(change: Dict, old_code_lines: List[str], new_code_lines: List[str]) -> Dict:
    """
    检查方法签名的变更
    """
    # 检查是否涉及方法或类的名称和参数变更
    method_changed = False
    class_changed = False
    
    def check_node_for_signature_change(node: Dict):
        nonlocal method_changed, class_changed
        
        if node['node_type'] in ['MethodDeclaration', 'function_decl', 'function']:
            # 检查方法名称和参数是否变更
            method_changed = True
        elif node['node_type'] in ['TypeDeclaration', 'struct', 'class']:
            # 检查类名称是否变更
            class_changed = True
        
        for child in node['children']:
            check_node_for_signature_change(child)
    
    check_node_for_signature_change(change)
    
    return {
        'method_name_or_params_changed': method_changed,
        'class_name_changed': class_changed
    }



def save_filtered_changes(changes: List[Dict], student_id: str, homework_id: str, file_name: str):
    """
    保存过滤后的变更到全局列表
    """
    # 读取新旧版本代码文件
    old_code_path = DATA_ROOT / "data" / student_id / homework_id / "first" / file_name.replace('.txt', '')
    new_code_path = DATA_ROOT / "data" / student_id / homework_id / "last" / file_name.replace('.txt', '')
    
    old_code_lines = read_code_file(str(old_code_path))
    new_code_lines = read_code_file(str(new_code_path))
    
    for change in changes:
        # 计算变更行数
        change_lines = calculate_change_lines(change, old_code_lines, new_code_lines)
        
        # 计算所在函数/类的长度和变更比例
        function_class_length = get_function_class_length(change, old_code_lines, new_code_lines)
        change_ratio = change_lines / max(function_class_length, 1)  # 避免除零
        
        # 计算所在域变更的平均行数
        avg_change_lines_in_scope = get_avg_change_lines_in_scope(change, old_code_lines, new_code_lines)
        
        # 确定变更类型
        change_type = determine_change_type(change)
        
        # 获取变更涉及的语法结构
        syntax_structures = get_syntax_structures(change)
        
        # 判断方法签名变更
        method_signature_changed = check_method_signature_change(change, old_code_lines, new_code_lines)
        
        record = {
            'student_id': student_id,
            'homework_id': homework_id,
            'file_path': file_name.replace('.txt', ''),
            'change_data': change,
            'change_lines': change_lines,
            'function_class_length': function_class_length,
            'change_ratio': change_ratio,
            'avg_change_lines_in_scope': avg_change_lines_in_scope,
            'change_type': change_type,
            'syntax_structures': syntax_structures,
            'method_signature_changed': method_signature_changed
        }
        all_change_data.append(record)
    # print(f"Saved {len(changes)} filtered changes for {student_id}/{homework_id}/{file_name}")

def extract_code_changes(change_path: str) -> List[Dict]:
    """
    提取代码变更
    """
    parser = ASTDiffParser(change_path)
    return parser.extract_code_change_trees()


class CodeChangeNode:
    def __init__(self, node_type: str, content: str, start_pos: int, end_pos: int,
                 old_start: int, old_end: int, change_type: str,
                 old_relative_pos: int = None, new_relative_pos: int = None,
                 children: List['CodeChangeNode'] = None):
        self.node_type = node_type
        self.content = content
        self.start_pos = start_pos  # 新版本位置
        self.end_pos = end_pos      # 新版本位置
        self.old_start = old_start  # 旧版本位置
        self.old_end = old_end      # 旧版本位置
        self.change_type = change_type
        self.old_relative_pos = old_relative_pos
        self.new_relative_pos = new_relative_pos
        self.children = children if children is not None else []
        self.lable = False
        
    def add_child(self, child: 'CodeChangeNode'):
        self.children.append(child)
        
    def to_dict(self):
        return {
            'node_type': self.node_type,
            'content': self.content,
            'start_pos': self.start_pos,
            'end_pos': self.end_pos,
            'old_start': self.old_start,
            'old_end': self.old_end,
            'change_type': self.change_type,
            'old_relative_pos': self.old_relative_pos,
            'new_relative_pos': self.new_relative_pos,
            'children': [child.to_dict() for child in self.children]
        }

class ASTDiffParser:
    def __init__(self, diff_file_path: str):
        self.diff_file_path = diff_file_path
        self._infer_ast_paths()
        self.matches = {}  # 旧字符位置 -> 新字符位置
        self.match_ranges_old_to_new = {} # (old_start, old_end) -> (new_start, new_end)
        self.changes = []
        self.changes_by_new_range = {}
        self._parse_diff_file()
        
    def _infer_ast_paths(self):
        """从 diff 文件路径推导旧/新版本 AST 文件路径"""
        diff_path = os.path.abspath(self.diff_file_path)
        parts = diff_path.split(os.sep)
        diff_type = parts[-2]
        homework_idx = -1
        for i in range(len(parts) - 1, -1, -1):
            if parts[i].isdigit():
                homework_idx = i
                break
        if homework_idx == -1:
            raise ValueError(f"Cannot find homework_id in path: {diff_path}")
        student_id = parts[homework_idx - 1]
        homework_id = parts[homework_idx]
        idx = homework_ids.index(homework_id)
        mid_path = mid_data_path[idx]
        # 找到 A/B 的位置
        next_part = parts[homework_idx + 1]
        if next_part in ('A', 'B'):
            relative_parts = parts[homework_idx + 2:]  # 跳过 A/B
        else:
            relative_parts = parts[homework_idx + 1:]
        # 构造相对路径（去掉 .txt）
        relative_path = os.path.join(*relative_parts)
        # 基础目录
        base_dir = os.path.join(*parts[:homework_idx])
        if diff_type == 'A':
            self.old_ast_path = str(DATA_ROOT / mid_path / student_id / homework_id / "1" / relative_path)
            if not os.path.exists(self.old_ast_path):
                self.old_ast_path = str(DATA_ROOT / mid_data_path[idx - 1] / student_id / homework_ids[idx - 1] / "3" / relative_path)
            self.new_ast_path = str(DATA_ROOT / mid_path / student_id / homework_id / "2" / relative_path)
        elif diff_type == 'B':
            self.old_ast_path = str(DATA_ROOT / mid_path / student_id / homework_id / "2" / relative_path)
            self.new_ast_path = str(DATA_ROOT / mid_path / student_id / homework_id / "3" / relative_path)

    def _parse_diff_file(self):
        with open(self.diff_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        sections = [s.strip() for s in content.split('===\n') if s.strip()]
        for section in sections:
            lines = section.strip().split('\n')
            if not lines: continue
            change_type = lines[0].strip()
            if change_type == 'match':
                self._parse_match_section(lines[2:])
            elif change_type in ['update-node', 'move-tree', 'insert-tree', 'insert-node', 'delete-node', 'delete-tree']:
                self._parse_change_section(change_type, lines[1:])

    def _parse_change_section(self, change_type: str, lines: List[str]):
        i = 0
        # 外层循环：寻找 '---' 分隔符，代表一个新的变更块开始
        while i < len(lines):
            line = lines[i].strip()
            if line == '---':
                # 找到了 '---'，核心变更节点在下一行
                i += 1 # 移动到下一行
                if i >= len(lines):
                    # '---' 后面没有内容了
                    break

                core_line = lines[i].strip()
                if not core_line:
                    # '---' 后是空行
                    i += 1
                    continue

                # 解析核心变更节点
                node_match = re.search(r'([a-zA-Z_][a-zA-Z0-9_]*)(?::\s*([a-zA-Z_][a-zA-Z0-9_]*))?\s*\[([0-9]+),([0-9]+)\](?:\s+(.*))?', core_line)
                if node_match:
                    node_type = node_match.group(1)                     # 提取类型（如 SimpleName）
                    identifier = node_match.group(2)                    # 提取冒号后的标识符（如 errorOutputPath）
                    raw_start = int(node_match.group(3))               # 提取起始位置
                    raw_end = int(node_match.group(4))                 # 提取结束位置
                    extra_content = node_match.group(5) or ""          # 提取额外内容
                    content = identifier if identifier else extra_content
                    # 这里 change_type 是函数参数，表示当前处理的这个变更块的整体类型（如 'delete-tree'）
                    actual_change_type = self._map_change_type(change_type)

                    # --- 初始化 ---
                    old_start_CN, old_end_CN = -1, -1
                    new_start_CN, new_end_CN = -1, -1
                    parent_info = None

                    # --- 根据变更类型解析核心变更节点 (CN) 和其父节点 (PN) 信息 ---
                    # 注意：现在我们只为核心变更节点（即 core_line 定义的节点）查找 parent_info
                    if actual_change_type in ('insert', 'Insert'):
                        # --- INSERT LOGIC ---
                        new_start_CN, new_end_CN = raw_start, raw_end
                        # ... (INSERT parent_info logic here, similar to before but only for core_line) ...
                        # 解析 'to' 部分 (目标父节点信息)
                        potential_parent_old_start = -1
                        potential_parent_old_end = -1
                        j = i + 1 # 从核心节点行的下一行开始查找
                        while j < len(lines) and not lines[j].strip().lower().startswith('to'):
                            j += 1
                        if j < len(lines) and lines[j].strip().lower().startswith('to'):
                            j += 1 # 跳过 'to'
                            if j < len(lines):
                                parent_line = lines[j].strip()
                                parent_match = re.search(r'([a-zA-Z_][a-zA-Z0-9_:]*)\s*\[([0-9]+),([0-9]+)\]', parent_line)
                                if parent_match:
                                    potential_parent_old_start = int(parent_match.group(2))
                                    potential_parent_old_end = int(parent_match.group(3))

                                    # 1. 在旧版本 AST 中查找
                                    found_in_old = False
                                    pn_old_start, pn_old_end = -1, -1
                                    pn_new_start, pn_new_end = -1, -1
                                    found_node_in_old = None
                                    found_node_in_new = None
                                    if os.path.exists(self.old_ast_path):
                                        try:
                                            old_ast = load_ast_file(self.old_ast_path)
                                            found_node_in_old = find_parent_in_ast(old_ast, potential_parent_old_start, potential_parent_old_end)
                                            if found_node_in_old and found_node_in_old['start'] <= potential_parent_old_start and potential_parent_old_end <= found_node_in_old['end']:
                                                pn_old_start = found_node_in_old['start']
                                                pn_old_end = found_node_in_old['end']
                                                # 2. 尝试通过 match 找新位置
                                                pn_new_range_from_match = self.match_ranges_old_to_new.get((pn_old_start, pn_old_end), None)
                                                if pn_new_range_from_match:
                                                    pn_new_start, pn_new_end = pn_new_range_from_match
                                                    found_in_old = True
                                                else:
                                                    pass
                                                    #print(f"Debug: Insert parent [{pn_old_start}, {pn_old_end}] found in old AST, but no match range. Parent might have been changed (e.g., insert).")
                                        except Exception as e:
                                            print(f"Warning: Failed to load/parse old AST for insert parent lookup in {self.diff_file_path}: {e}")

                                    if not found_in_old:
                                        # 3. 如果旧版本没找到，可能 'to' 指向的是新版本范围 (父节点也是插入的)
                                        if os.path.exists(self.new_ast_path):
                                            new_ast = load_ast_file(self.new_ast_path)
                                            found_node_in_new = find_parent_in_ast(new_ast, potential_parent_old_start, potential_parent_old_end)
                                            if found_node_in_new and found_node_in_new['start'] <= potential_parent_old_start and potential_parent_old_end <= found_node_in_new['end']:
                                                # 4. 在新版本 AST 中找到了，说明父节点也是新插入的
                                                pn_new_start = found_node_in_new['start']
                                                pn_new_end = found_node_in_new['end']
                                                # 父节点在旧版本不存在
                                                pn_old_start, pn_old_end = -1, -1

                                    # 构建 parent_info (仅为核心节点)
                                    if pn_old_start != -1 or pn_new_start != -1:
                                        parent_info = {
                                            'node_type': (found_node_in_old or found_node_in_new)['node_type'],
                                            'old_start': pn_old_start,
                                            'old_end': pn_old_end,
                                            'new_start': pn_new_start,
                                            'new_end': pn_new_end
                                        }
                                    elif not self.diff_file_path.endswith("cpp.txt") and not self.diff_file_path.endswith("c.txt") and self.diff_file_path.endswith("h.txt"):
                                        # print(f"Debug: Could not determine parent info for insert node [{new_start_CN}, {new_end_CN}] in {self.diff_file_path}")
                                        pass
                        # else: # 没有 'to' 行
                        #     print(f"Debug: Expected 'to' line for insert in {self.diff_file_path}")


                    elif actual_change_type in ('update', 'Update'):
                        # --- UPDATE LOGIC ---
                        old_start_CN, old_end_CN = raw_start, raw_end
                        new_start_CN = self.matches.get(raw_start, -1)
                        new_end_CN = self.matches.get(raw_end, -1)
                        # ... (UPDATE parent_info logic here) ...
                        # (使用之前提供的 UPDATE parent_info 逻辑)
                        pn_old_start, pn_old_end = -1, -1
                        pn_new_start, pn_new_end = -1, -1

                        if old_start_CN != -1 and old_end_CN != -1 and os.path.exists(self.old_ast_path):
                            try:
                                old_ast = load_ast_file(self.old_ast_path)
                                target_node_old = find_parent_in_ast(old_ast, old_start_CN, old_end_CN)
                                if target_node_old:
                                    if target_node_old['start'] != old_ast.get('start', -1) or target_node_old['end'] != old_ast.get('end', -1):
                                        parent_node_old = find_parent_in_ast(old_ast, target_node_old['start'], target_node_old['end'])
                                        if parent_node_old:
                                            pn_old_start = parent_node_old['start']
                                            pn_old_end = parent_node_old['end']
                                            pn_new_range_from_match = self.match_ranges_old_to_new.get((pn_old_start, pn_old_end), None)
                                            if pn_new_range_from_match:
                                                pn_new_start, pn_new_end = pn_new_range_from_match
                            except Exception as e:
                                print(f"Warning: Failed to load/parse old AST for update parent lookup in {self.diff_file_path}: {e}")

                        if new_start_CN != -1 and new_end_CN != -1 and os.path.exists(self.new_ast_path):
                            try:
                                new_ast = load_ast_file(self.new_ast_path)
                                target_node_new = find_parent_in_ast(new_ast, new_start_CN, new_end_CN)
                                if target_node_new:
                                    if target_node_new['start'] != new_ast.get('start', -1) or target_node_new['end'] != new_ast.get('end', -1):
                                        parent_node_new = find_parent_in_ast(new_ast, target_node_new['start'], target_node_new['end'])
                                        if parent_node_new:
                                            if pn_new_start == -1:
                                                pn_new_start = parent_node_new['start']
                                                pn_new_end = parent_node_new['end']
                                                for (old_s, old_e), (new_s, new_e) in self.match_ranges_old_to_new.items():
                                                    if new_s == pn_new_start and new_e == pn_new_end:
                                                        pn_old_start, pn_old_end = old_s, old_e
                                                        break
                            except Exception as e:
                                print(f"Warning: Failed to load/parse new AST for update parent lookup in {self.diff_file_path}: {e}")

                        if pn_old_start != -1 or pn_new_start != -1:
                            node_type_for_parent = None
                            if pn_old_start != -1:
                                parent_node = find_parent_in_ast(load_ast_file(self.old_ast_path), pn_old_start, pn_old_end)
                                if parent_node is not None:
                                    node_type_for_parent = parent_node['node_type']
                                else:
                                    # print(f"Warning: Parent node not found in old AST for range [{pn_old_start}, {pn_old_end}] in {self.diff_file_path}")
                                    pass

                            if node_type_for_parent is None and pn_new_start != -1:
                                parent_node = find_parent_in_ast(load_ast_file(self.new_ast_path), pn_new_start, pn_new_end)
                                if parent_node is not None:
                                    node_type_for_parent = parent_node['node_type']
                                else:
                                    # print(f"Warning: Parent node not found in new AST for range [{pn_new_start}, {pn_new_end}] in {self.diff_file_path}")
                                    pass

                            parent_info = {
                                'node_type': node_type_for_parent,
                                'old_start': pn_old_start,
                                'old_end': pn_old_end,
                                'new_start': pn_new_start,
                                'new_end': pn_new_end
                            }
                        else:
                            # print(f"Debug: Could not determine parent info for update node [{old_start_CN}, {old_end_CN}] -> [{new_start_CN}, {new_end_CN}] in {self.diff_file_path}")
                            pass

                    elif actual_change_type in ('move', 'Move'):
                        # --- MOVE LOGIC ---
                        old_start_CN, old_end_CN = raw_start, raw_end
                        new_start_CN = self.matches.get(raw_start, -1)
                        new_end_CN = self.matches.get(raw_end, -1)
                        # ... (MOVE parent_info logic here) ...
                        # (使用之前提供的 MOVE parent_info 逻辑)
                        potential_parent_old_start = -1
                        potential_parent_old_end = -1
                        j = i + 1
                        while j < len(lines) and not lines[j].strip().lower().startswith('to'):
                            j += 1
                        if j < len(lines) and lines[j].strip().lower().startswith('to'):
                            j += 1 # 跳过 'to'
                            if j < len(lines):
                                parent_line = lines[j].strip()
                                parent_match = re.search(r'([a-zA-Z_][a-zA-Z0-9_:]*)\s*\[([0-9]+),([0-9]+)\]', parent_line)
                                if parent_match:
                                    potential_parent_old_start = int(parent_match.group(2))
                                    potential_parent_old_end = int(parent_match.group(3))

                                    found_in_old = False
                                    pn_old_start, pn_old_end = -1, -1
                                    pn_new_start, pn_new_end = -1, -1
                                    found_node_in_old = None
                                    found_node_in_new = None
                                    if os.path.exists(self.old_ast_path):
                                        try:
                                            old_ast = load_ast_file(self.old_ast_path)
                                            found_node_in_old = find_parent_in_ast(old_ast, potential_parent_old_start, potential_parent_old_end)
                                            if found_node_in_old and found_node_in_old['start'] <= potential_parent_old_start and potential_parent_old_end <= found_node_in_old['end']:
                                                pn_old_start = found_node_in_old['start']
                                                pn_old_end = found_node_in_old['end']
                                                pn_new_range_from_match = self.match_ranges_old_to_new.get((pn_old_start, pn_old_end), None)
                                                if pn_new_range_from_match:
                                                    pn_new_start, pn_new_end = pn_new_range_from_match
                                                    found_in_old = True
                                                else:
                                                    #print(f"Debug: Move target parent [{pn_old_start}, {pn_old_end}] found in old AST, but no match range. Parent might have been changed (e.g., insert).")
                                                    pass
                                        except Exception as e:
                                            print(f"Warning: Failed to load/parse old AST for move parent lookup in {self.diff_file_path}: {e}")

                                    if not found_in_old:
                                        if os.path.exists(self.new_ast_path):
                                            try:
                                                new_ast = load_ast_file(self.new_ast_path)
                                                found_node_in_new = find_parent_in_ast(new_ast, potential_parent_old_start, potential_parent_old_end)
                                                if found_node_in_new and found_node_in_new['start'] <= potential_parent_old_start and potential_parent_old_end <= found_node_in_new['end']:
                                                    pn_new_start = found_node_in_new['start']
                                                    pn_new_end = found_node_in_new['end']
                                                    pn_old_start, pn_old_end = -1, -1
                                                elif not self.diff_file_path.endswith("cpp.txt") and not self.diff_file_path.endswith("c.txt") and self.diff_file_path.endswith("h.txt"):
                                                    #print(f"Debug: Move target parent range [{potential_parent_old_start}, {potential_parent_old_end}] not found in old or new AST for move in {self.diff_file_path}")
                                                    pass
                                            except Exception as e:
                                                print(f"Warning: Failed to load/parse new AST for move parent lookup in {self.diff_file_path}: {e}")
                                        else:
                                            # print(f"Debug: New AST path does not exist for move parent lookup: {self.new_ast_path}")
                                            pass

                                    if pn_old_start != -1 or pn_new_start != -1:
                                        parent_info = {
                                                'node_type': (found_node_in_old or found_node_in_new)['node_type'],
                                                'old_start': pn_old_start,
                                                'old_end': pn_old_end,
                                                'new_start': pn_new_start,
                                                'new_end': pn_new_end
                                            }
                                    else:
                                        # print(f"Debug: Could not determine parent info for move node [{old_start_CN}, {old_end_CN}] -> [{new_start_CN}, {new_end_CN}] in {self.diff_file_path}")
                                        pass

                                else:
                                    # print(f"Debug: Could not parse parent line '{parent_line}' for move in {self.diff_file_path}")
                                    pass
                        # else: # 没有 'to' 行
                        #     print(f"Debug: Expected 'to' line for move in {self.diff_file_path}")


                    elif actual_change_type in ('delete', 'Delete'):
                        # --- DELETE LOGIC (CORRECTED AGAIN) ---
                        old_start_CN, old_end_CN = raw_start, raw_end
                        # new_start_CN, new_end_CN 保持 (-1, -1)

                        # CN 父节点 (PN) 信息 (仅查找 *核心变更节点* 的父节点)
                        pn_old_start, pn_old_end = -1, -1
                        pn_new_start, pn_new_end = -1, -1

                        if old_start_CN != -1 and old_end_CN != -1 and os.path.exists(self.old_ast_path):
                            try:
                                old_ast = load_ast_file(self.old_ast_path)
                                # 查找 *核心变更节点* (即 core_line 定义的节点) 本身
                                # 使用精确查找函数
                                target_node_old = self._find_node_in_ast_by_range(old_ast, old_start_CN, old_end_CN)
                                # 如果精确查找失败，回退到包含查找
                                if not target_node_old:
                                    target_node_old = find_parent_in_ast(old_ast, old_start_CN, old_end_CN)

                                if target_node_old and target_node_old['start'] == old_start_CN and target_node_old['end'] == old_end_CN:
                                    # 确认找到了精确匹配的节点
                                    # 检查 *核心变更节点* 是否是根节点
                                    if target_node_old['start'] != old_ast.get('start', -1) or target_node_old['end'] != old_ast.get('end', -1):
                                        # --- 关键修改：使用 _find_parent_by_child_range 查找父节点 ---
                                        parent_node_old = self._find_parent_by_child_range(old_ast, target_node_old['start'], target_node_old['end'])
                                        if parent_node_old:
                                            pn_old_start = parent_node_old['start']
                                            pn_old_end = parent_node_old['end']
                                            # 尝试通过 match 找父节点的新位置
                                            pn_new_range_from_match = self.match_ranges_old_to_new.get((pn_old_start, pn_old_end), None)
                                            if pn_new_range_from_match:
                                                pn_new_start, pn_new_end = pn_new_range_from_match
                                            else:
                                                # 这里是父节点也发生了变化（删除或更新)，但现在没有查找变更后的位置
                                                #print(f"Debug:[{old_start_CN},{old_end_CN}] Delete parent [{pn_old_start}, {pn_old_end}] has no match range. New location unknown or parent also changed.")
                                                pass
                                        else:
                                            # 如果 target_node_old 是根节点，它没有父节点
                                            # 或者在 AST 中找不到其父节点（理论上不应该发生，除非 AST 结构异常）
                                            pass
                                    else:
                                        # *核心变更节点* 是根节点，没有父节点
                                        pass
                                else:
                                    # 没有找到精确匹配的节点，或者 find_parent_in_ast 返回的不是精确匹配
                                    # print(f"Debug: Could not find exact core delete node [{old_start_CN}, {old_end_CN}] in old AST.")
                                    pass
                            except Exception as e:
                                print(f"Warning: Failed to load/parse old AST for delete *core node's* parent lookup in {self.diff_file_path}: {e}")
                        else:
                            print(f"Debug: Old AST path does not exist or delete *core node* [{old_start_CN}, {old_end_CN}] has invalid range for parent lookup: {self.old_ast_path}")

                        # 构建 parent_info (仅为核心节点)
                        if pn_old_start != -1:
                            parent_info = {
                                'node_type': find_parent_in_ast(load_ast_file(self.old_ast_path), pn_old_start, pn_old_end)['node_type'], # 再次查找节点类型
                                'old_start': pn_old_start,
                                'old_end': pn_old_end,
                                'new_start': pn_new_start,
                                'new_end': pn_new_end
                            }
                        # else: # If no old parent found (e.g., core node is root), parent_info remains None


                    else: # unknown
                        print(f"Warning: Unknown change type '{actual_change_type}' for node {node_type} [{raw_start}, {raw_end}] in {self.diff_file_path}.")
                        old_start_CN, old_end_CN = raw_start, raw_end
                        new_start_CN = self.matches.get(raw_start, -1)
                        new_end_CN = self.matches.get(raw_end, -1)
                        # parent_info remains None

                    # --- 存储变更信息 (仅为核心变更节点) ---
                    change_info = {
                        'type': actual_change_type,
                        'node_type': node_type,
                        'old_start': old_start_CN,
                        'old_end': old_end_CN,
                        'new_start': new_start_CN,
                        'new_end': new_end_CN,
                        'content': content,
                        'parent_info': parent_info,
                        'new_parent_range_for_move_op': None, # Will be filled if needed later
                        'move_index': -1 # Will be filled if needed later
                    }
                    # --- 解析 'to' 和 'at' (如果需要存储 - 仅 move/insert) ---
                    if actual_change_type in ('move', 'Move', 'insert', 'Insert'):
                        j = i + 1
                        while j < len(lines) and not lines[j].strip().lower().startswith('to'):
                            j += 1
                        if j < len(lines) and lines[j].strip().lower().startswith('to'):
                            j += 1 # Skip 'to'
                            if j < len(lines):
                                parent_line = lines[j].strip()
                                parent_match = re.search(r'([a-zA-Z_][a-zA-Z0-9_:]*)\s*\[([0-9]+),([0-9]+)\]', parent_line)
                                if parent_match:
                                    change_info['new_parent_range_for_move_op'] = (int(parent_match.group(2)), int(parent_match.group(3)))
                                j += 1 # Skip parent node line
                                if j < len(lines) and lines[j].strip().lower().startswith('at'):
                                    at_match = re.search(r'at\s+([0-9]+)', lines[j].strip())
                                    if at_match:
                                        change_info['move_index'] = int(at_match.group(1))

                    self.changes.append(change_info)
                    if new_start_CN != -1 and new_end_CN != -1:
                        self.changes_by_new_range[(new_start_CN, new_end_CN)] = change_info

                    # --- 跳过子节点行 ---
                    # 核心节点行是 i，现在从 i+1 开始查找下一个独立变更行
                    j = i + 1
                    # 查找下一个非缩进行（独立变更行、'to'/'at' 行或文件结尾）
                    # 一种方法是计算核心节点行的缩进
                    initial_indent = len(lines[i]) - len(lines[i].lstrip(' '))
                    while j < len(lines):
                        current_line_stripped = lines[j].strip()
                        if not current_line_stripped:
                            j += 1
                            continue
                        current_indent = len(lines[j]) - len(lines[j].lstrip(' '))
                        # 如果当前行的缩进小于或等于初始核心节点行的缩进，
                        # 或者是 'to'/'at' 这种不属于当前核心节点子结构的行
                        if current_indent <= initial_indent or lines[j].strip().lower() in ['to', 'at']:
                            # 找到了下一个独立行或 'to'/'at' 行，停止跳过
                            break
                        # 否则，当前行是子节点，继续
                        j += 1
                    # 将 i 指向下一个独立行，准备下一轮外层循环
                    i = j
                    # 外层循环继续，因为 i 已经更新
                    continue # Explicitly continue outer loop after skipping sub-nodes

                else:
                    # '---' 后面不是有效的节点行，跳过
                    i += 1
                    continue
            else:
                # 当前行不是 '---'，跳过
                i += 1
                continue

    def _find_node_in_ast_by_range(self, ast_node: Dict, target_start: int, target_end: int) -> Optional[Dict]:
        """
        在 AST 中查找精确匹配 [target_start, target_end] 范围的节点。
        如果找到，返回节点字典；否则返回 None。
        """
        if ast_node['start'] == target_start and ast_node['end'] == target_end:
            return ast_node

        # 递归检查子节点
        for child in ast_node.get('children', []):
            result = self._find_node_in_ast_by_range(child, target_start, target_end)
            if result:
                return result

        return None

    def _find_parent_by_child_range(self, ast_root: Dict, child_start: int, child_end: int) -> Optional[Dict]:
        """
        在 AST 根节点中，根据子节点的 [start, end] 范围，找到该子节点的父节点。
        如果子节点是根节点本身，则返回 None。
        如果找到，返回父节点字典；否则返回 None。
        """
        # 检查是否是根节点
        if ast_root['start'] == child_start and ast_root['end'] == child_end:
            # print(f"Debug: Node [{child_start}, {child_end}] is the root node, has no parent.")
            return None # 根节点没有父节点

        def dfs(node, parent=None):
            if node['start'] <= child_start and child_end <= node['end']:
                # 检查当前节点是否就是目标子节点
                if node['start'] == child_start and node['end'] == child_end:
                    return parent # 返回其父节点
                # 否则，继续在子节点中查找
                for child in node.get('children', []):
                    result = dfs(child, node)
                    if result:
                        return result
            return None

        return dfs(ast_root)

    def _find_corresponding_node_in_other_ast(self, other_ast_root: Dict, node_info: Dict) -> Optional[Dict]:
        """
        尝试在 other_ast_root 中找到与 node_info 相对应的节点。
        node_info: 包含 'node_type', 'start', 'end' 等信息的字典。
        返回找到的对应节点，或 None。
        策略：优先精确位置匹配，回退到类型和结构匹配。
        """
        target_type = node_info['node_type']
        target_start = node_info['start']
        target_end = node_info['end']

        # 策略 1: 尝试精确位置匹配
        corresponding_node = self._find_node_in_ast_by_range(other_ast_root, target_start, target_end)
        if corresponding_node:
            # print(f"Found corresponding node by exact range [{target_start}, {target_end}] in other AST.")
            return corresponding_node

        # 策略 2: 尝试类型和结构匹配 (更复杂，这里简化为查找相同类型的节点并检查范围是否接近)
        def search_by_type_and_proximity(node):
            if node['node_type'] == target_type:
                # 检查范围是否足够接近 (例如，起始位置差小于 10)
                if abs(node['start'] - target_start) <= 10 and abs(node['end'] - target_end) <= 10:
                    # print(f"Found corresponding node by type and proximity [{node['start']}, {node['end']}] in other AST.")
                    return node
            for child in node.get('children', []):
                result = search_by_type_and_proximity(child)
                if result:
                    return result
            return None

        return search_by_type_and_proximity(other_ast_root)

    def _find_moved_node_in_new_ast(self, new_ast_root: Dict, move_change_info: Dict) -> Tuple[int, int]:
        """
        根据 move 操作的 GumTree 信息（旧版本的 new_parent_info 和 move_index (新位置索引)），
        在新版本 AST 中查找被移动节点的新位置。
        move_change_info['new_parent_range_for_move'] 包含的是目标父节点在 *新版本* AST 中的范围。
        move_change_info['move_index'] 是被移动节点在 *新版本* 父节点子节点列表中的索引。
        move_change_info['old_start/end'] 是被移动节点在 *旧版本* 中的范围。
        返回 (new_start, new_end) 或 (-1, -1)。
        """
        new_parent_range_for_move = move_change_info.get('new_parent_range_for_move')
        move_index = move_change_info.get('move_index', -1)
        original_old_start = move_change_info.get('old_start', -1)
        original_old_end = move_change_info.get('old_end', -1)

        print(f"Debug: _find_moved_node_in_new_ast called. move_index={move_index}, new_parent_range_for_move={new_parent_range_for_move}, original_old_range=[{original_old_start}, {original_old_end}]")

        if not new_parent_range_for_move or move_index == -1:
            print(f"Debug: Missing new_parent_range_for_move or move_index for move in {self.diff_file_path}")
            return -1, -1

        new_parent_start, new_parent_end = new_parent_range_for_move

        # 步骤1: 在新版本 AST 中找到新版本的父节点
        new_parent_node_in_new_ast = find_parent_in_ast(new_ast_root, new_parent_start, new_parent_end)
        if not new_parent_node_in_new_ast or not (new_parent_node_in_new_ast['start'] == new_parent_start and new_parent_node_in_new_ast['end'] == new_parent_end):
            # print(f"Debug: Could not find or match new parent node [{new_parent_start}, {new_parent_end}] in new AST for move in {self.diff_file_path}. Found: {new_parent_node_in_new_ast}")
            return -1, -1

        # 步骤2: 获取新版本父节点的子节点列表，并根据 move_index (新版本索引) 找到目标位置
        new_parent_children = new_parent_node_in_new_ast.get('children', [])
        if move_index >= len(new_parent_children):
            # print(f"Warning: move_index {move_index} is invalid (new parent has {len(new_parent_children)} children) for move in {self.diff_file_path}. Attempting fallback.")
            # Fallback: 尝试根据旧版本被移动节点的原始位置 [original_old_start, original_old_end] 在旧版本 AST 中查找
            # 然后通过 match 映射找到新位置
            old_ast_path_for_lookup = self.old_ast_path
            if os.path.exists(old_ast_path_for_lookup):
                try:
                    old_ast_for_lookup = load_ast_file(old_ast_path_for_lookup)
                    original_old_node_in_old_ast = self._find_node_in_ast_by_range(old_ast_for_lookup, original_old_start, original_old_end)
                    if not original_old_node_in_old_ast:
                        original_old_node_in_old_ast = find_parent_in_ast(old_ast_for_lookup, original_old_start, original_old_end)
                        if original_old_node_in_old_ast and not (original_old_node_in_old_ast['start'] == original_old_start and original_old_node_in_old_ast['end'] == original_old_end):
                            original_old_node_in_old_ast = None

                    if original_old_node_in_old_ast:
                        # 尝试通过 match 映射找到新位置
                        new_start_from_match = self.matches.get(original_old_node_in_old_ast['start'], -1)
                        new_end_from_match = self.matches.get(original_old_node_in_old_ast['end'], -1)
                        if new_start_from_match != -1 and new_end_from_match != -1:
                            return new_start_from_match, new_end_from_match

                        # Fallback: 尝试在新版本 AST 中进行结构/类型匹配 (在新父节点内)
                        # print(f"Warning: Match mapping failed for fallback node [{original_old_start}, {original_old_end}] in {self.diff_file_path}. Attempting structural fallback within new parent.")
                        original_node_type = original_old_node_in_old_ast['node_type']
                        best_match = None
                        min_distance = float('inf')
                        for child in new_parent_node_in_new_ast.get('children', []):
                            if child['node_type'] == original_node_type:
                                distance = abs(child['start'] - original_old_start)
                                if distance < min_distance:
                                    min_distance = distance
                                    if min_distance <= 10: # 容忍小的位置偏移
                                        best_match = child

                        if best_match:
                            # print(f"Fallback resolved move child (within new parent) [{original_old_start}, {original_old_end}] -> [{best_match['start']}, {best_match['end']}] in {self.diff_file_path}")
                            return best_match['start'], best_match['end']

                except Exception as e:
                    print(f"Warning: Failed to load or parse old AST for fallback in {self.diff_file_path}: {e}")

            return -1, -1

        # 如果 move_index 有效，理论上我们已经知道被移动节点的新位置是 [new_start_from_match, new_end_from_match]
        # 或者需要通过其他方式（如结构匹配）找到它。
        # 关键还是在于通过 `original_old_range` 和 `self.matches` 找到新位置。

        # 重新尝试通过 match 映射找到原始被移动节点的新位置
        old_ast_path_for_lookup = self.old_ast_path
        if os.path.exists(old_ast_path_for_lookup):
            try:
                old_ast_for_lookup = load_ast_file(old_ast_path_for_lookup)
                original_old_node_in_old_ast = self._find_node_in_ast_by_range(old_ast_for_lookup, original_old_start, original_old_end)
                if not original_old_node_in_old_ast:
                    original_old_node_in_old_ast = find_parent_in_ast(old_ast_for_lookup, original_old_start, original_old_end)
                    if original_old_node_in_old_ast and not (original_old_node_in_old_ast['start'] == original_old_start and original_old_node_in_old_ast['end'] == original_old_end):
                        original_old_node_in_old_ast = None

                if original_old_node_in_old_ast:
                    new_start_from_match = self.matches.get(original_old_node_in_old_ast['start'], -1)
                    new_end_from_match = self.matches.get(original_old_node_in_old_ast['end'], -1)
                    if new_start_from_match != -1 and new_end_from_match != -1:
                        # print(f"Resolved move node [{original_old_start}, {original_old_end}] -> [{new_start_from_match}, {new_end_from_match}] using match mapping in {self.diff_file_path}")
                        return new_start_from_match, new_end_from_match
            except Exception as e:
                print(f"Warning: Failed to load or parse old AST for main lookup in {self.diff_file_path}: {e}")

        # 如果 match 映射失败，尝试结构匹配 (在新父节点内)
        print(f"Warning: Match mapping failed for move child [{original_old_start}, {original_old_end}] in {self.diff_file_path}. Attempting structural fallback within new parent.")
        original_node_type = original_old_node_in_old_ast['node_type'] if original_old_node_in_old_ast else ''
        best_match = None
        min_distance = float('inf')
        for child in new_parent_node_in_new_ast.get('children', []):
            if child['node_type'] == original_node_type:
                distance = abs(child['start'] - original_old_start) # 使用旧位置作为参考
                if distance < min_distance:
                    min_distance = distance
                    if min_distance <= 10: # 容忍小的位置偏移
                        best_match = child

        if best_match:
            # print(f"Fallback resolved move child (within new parent) [{original_old_start}, {original_old_end}] -> [{best_match['start']}, {best_match['end']}] in {self.diff_file_path}")
            return best_match['start'], best_match['end']

        print(f"Debug: Fallback search within new parent also failed for move child [{original_old_start}, {original_old_end}] in {self.diff_file_path}")
        return -1, -1

    def _parse_match_section(self, lines: List[str]):
        """
        解析 match 行，建立字符位置映射和节点范围映射
        """
        i = 0
        while i < len(lines) - 1: # 处理成对的行
            old_line = lines[i].strip()
            new_line = lines[i + 1].strip()

            old_match = re.search(r'\[([0-9]+),([0-9]+)\]', old_line)
            new_match = re.search(r'\[([0-9]+),([0-9]+)\]', new_line)

            if old_match and new_match:
                old_start, old_end = int(old_match.group(1)), int(old_match.group(2))
                new_start, new_end = int(new_match.group(1)), int(new_match.group(2))

                # 存储节点范围映射
                self.match_ranges_old_to_new[(old_start, old_end)] = (new_start, new_end)

                # 存储字符位置映射 (保持原有逻辑)
                for pos in range(old_start, old_end + 1):
                    self.matches[pos] = new_start + (pos - old_start)

            i += 2
    
    
    def _build_change_type_map(self, changes: List[Dict]) -> Dict[Tuple[int, int], str]:
        """
        构建 (start, end) -> change_type 的映射，包含：
        - 显式变更节点
        - match 中的节点（标记为 'unchanged'）
        """
        mapping = {}

        # 1. 显式变更节点
        for ch in changes:
            key = (ch['old_start'], ch['old_end'])
            if key != (-1, -1):
                mapping[key] = ch['type']
            key_new = (ch['new_start'], ch['new_end'])
            if key_new != (-1, -1):
                mapping[key_new] = ch['type']

        # 2. match 节点（未变更）
        for pos_old, pos_new in self.matches.items():
            # 简化：只记录单点，实际应记录范围
            # 更精确的做法是解析 match 节点的完整 [start,end]
            # 此处假设 match 范围已在 self.matches_ranges 中（可扩展）
            mapping[(pos_old, pos_old)] = 'unchanged'
            mapping[(pos_new, pos_new)] = 'unchanged'

        return mapping

    def _map_change_type(self, raw_type: str) -> str:
        mapping = {
            'update-node': 'update',
            'move-tree': 'move',
            'insert-tree': 'insert',
            'insert-node': 'insert',
            'delete-node': 'delete',
            'delete-tree': 'delete'
        }
        return mapping.get(raw_type, raw_type) 
    
    def extract_code_change_trees(self) -> List[Dict]:
        if not self.changes:
            return []

        # 按 parent_info 分组，使用新版本的父节点位置进行分组
        # 确保同一父节点（在新版本中）的变更在一起
        grouped = {}
        for ch in self.changes:
            key = None
            parent_info = ch['parent_info']
            
            if parent_info:
                # 使用新版本的父节点位置进行分组
                key = (parent_info['node_type'], parent_info['new_start'], parent_info['new_end'])
            else:
                key = 'orphan'
                
            # 确保 key 不为 None，避免字典键错误
            if key is None:
                key = 'orphan_with_none_key' # 或者其他合适的默认值，但理论上不应该出现 None
                
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(ch)

        trees = []
        for parent_key, changes in grouped.items():
            tree = self._build_change_tree(changes)
            if tree:
                trees.append(tree.to_dict())
        return trees
    
    def _group_adjacent_changes(self) -> List[List[Dict]]:
        """
        根据 parent_info 分组变更，使用新版本的父节点位置进行分组。
        """
        parent_groups = {}

        for change in self.changes:
            parent_key = None
            parent_info = change['parent_info']

            if parent_info:
                # 使用新版本的父节点位置进行分组
                parent_key = (parent_info['node_type'], parent_info['new_start'], parent_info['new_end'])
            else:
                parent_key = 'orphan'

            if parent_key not in parent_groups:
                parent_groups[parent_key] = []
            parent_groups[parent_key].append(change)

        return list(parent_groups.values())
    
    def _build_from_changes_only(self, changes: List[Dict]) -> Optional['CodeChangeNode']:
        """
        回退方案：仅用 GumTree 报告的变更节点构建树（无 AST 上下文）
        """
        if not changes:
            return None

        # 构建 change_info 查找字典，用于 _build_full_tree_recursive
        change_info_lookup = {}
        for ch in changes:
            if ch['old_start'] != -1:
                change_info_lookup[(ch['old_start'], ch['old_end'])] = ch
            if ch['new_start'] != -1:
                change_info_lookup[(ch['new_start'], ch['new_end'])] = ch

        # 尝试使用共同父节点（来自变更文件中的 'to' 信息，现在包含新旧位置）
        parent_info = changes[0]['parent_info']
        if parent_info:
            root = CodeChangeNode(
                node_type=parent_info['node_type'],
                content=parent_info['content'],
                start_pos=parent_info['new_start'],
                end_pos=parent_info['new_end'],
                old_start=parent_info['old_start'],
                old_end=parent_info['old_end'],
                change_type='container'
            )
        else:
            # 无父节点：创建虚拟根
            # 过滤掉 -1 的值再计算范围
            valid_new = [c for c in changes if c['new_start'] != -1 and c['new_end'] != -1]
            valid_old = [c for c in changes if c['old_start'] != -1 and c['old_end'] != -1]

            if valid_new:
                new_start = min(c['new_start'] for c in valid_new)
                new_end = max(c['new_end'] for c in valid_new)
            else:
                new_start, new_end = 0, 0

            if valid_old:
                old_start = min(c['old_start'] for c in valid_old)
                old_end = max(c['old_end'] for c in valid_old)
            else:
                old_start, old_end = 0, 0

            root = CodeChangeNode(
                node_type="fallback_root",
                content="",
                start_pos=new_start,
                end_pos=new_end,
                old_start=old_start,
                old_end=old_end,
                change_type='fallback'
            )

        # 添加显式变更节点作为子节点
        # 此处不再直接创建子节点，而是尝试构建一个最小的 AST 片段来调用 _build_full_tree_recursive
        # 或者，直接为每个 change 创建一个叶子节点
        # 为了与新的 _build_full_tree_recursive 保持一致，我们可以为每个 change 创建一个虚拟的 old_node/new_node，
        # 然后调用 _build_full_tree_recursive，但这会很复杂。
        # 更简单的方式是：只构建根节点，子节点就是 changes 本身。

        # 简化实现：为每个 change 创建一个子节点
        for ch in changes:
            child = CodeChangeNode(
                node_type=ch['node_type'],
                content=ch['content'],
                start_pos=ch['new_start'],
                end_pos=ch['new_end'],
                old_start=ch['old_start'],
                old_end=ch['old_end'],
                change_type=ch['type']
            )
            root.add_child(child)

        return root

    def _build_change_tree(self, changes: List[Dict]) -> Optional['CodeChangeNode']:
        """
        使用双版本 AST 构建完整变更树，包含变更节点和上下文节点。
        """
        if not changes:
            return None

        # 构建 change_info 查找字典，用于 _build_full_tree_recursive
        change_info_lookup = {}
        for ch in changes:
            if ch['old_start'] != -1:
                change_info_lookup[(ch['old_start'], ch['old_end'])] = ch
            if ch['new_start'] != -1:
                change_info_lookup[(ch['new_start'], ch['new_end'])] = ch

        # 步骤 1: 确定变更的根节点范围（来自 GumTree changes 或其父节点）
        common_parent_info = changes[0]['parent_info']
        if not common_parent_info:
            # print(f"Warning: No parent_info found for changes in {self.diff_file_path}. Using fallback.")
            return self._build_from_changes_only(changes)

        # 步骤 2: 加载旧版本和新版本的 AST
        try:
            old_ast_root = load_ast_file(self.old_ast_path) if os.path.exists(self.old_ast_path) else None
            new_ast_root = load_ast_file(self.new_ast_path) if os.path.exists(self.new_ast_path) else None
        except Exception as e:
            # print(f"Warning: Failed to load AST files for {self.diff_file_path}: {e}")
            return self._build_from_changes_only(changes)

        if not old_ast_root and not new_ast_root:
            # print(f"Warning: No AST files available for {self.diff_file_path}")
            return self._build_from_changes_only(changes)

        # 步骤 3: 在旧版本和新版本 AST 中找到变更的根节点
        old_root_node = find_parent_in_ast(old_ast_root, common_parent_info['old_start'], common_parent_info['old_end']) if old_ast_root else None
        new_root_node = find_parent_in_ast(new_ast_root, common_parent_info['new_start'], common_parent_info['new_end']) if new_ast_root else None

        if not old_root_node and not new_root_node:
            # print(f"Warning: Could not find root node in ASTs for {self.diff_file_path} using parent_info range.")
            all_old_ranges = [(c['old_start'], c['old_end']) for c in changes if c['old_start'] != -1]
            all_new_ranges = [(c['new_start'], c['new_end']) for c in changes if c['new_start'] != -1]

            fallback_old_start = min([r[0] for r in all_old_ranges]) if all_old_ranges else -1
            fallback_old_end = max([r[1] for r in all_old_ranges]) if all_old_ranges else -1
            fallback_new_start = min([r[0] for r in all_new_ranges]) if all_new_ranges else -1
            fallback_new_end = max([r[1] for r in all_new_ranges]) if all_new_ranges else -1

            if fallback_old_start != -1 and fallback_old_end != -1 and old_ast_root:
                old_root_node = find_parent_in_ast(old_ast_root, fallback_old_start, fallback_old_end)
            if fallback_new_start != -1 and fallback_new_end != -1 and new_ast_root:
                new_root_node = find_parent_in_ast(new_ast_root, fallback_new_start, fallback_new_end)

            if not old_root_node and not new_root_node:
                # print(f"Error: Fallback root node search also failed for {self.diff_file_path}. Returning None.")
                return None

        # 步骤 4: 构建变更类型映射 (start, end) -> change_type
        change_type_map = self._build_change_type_map(changes)

        # 步骤 5: 递归构建包含上下文的完整变更树
        root_node = self._build_full_tree_recursive(
            old_root_node, new_root_node, change_type_map, default_change_type='unchanged',
            change_info_lookup=change_info_lookup
        )

        return root_node

    def _build_full_tree_recursive(self, old_node: Optional[Dict], new_node: Optional[Dict],
                                change_type_map: Dict, default_change_type: str,
                                change_info_lookup: Dict = None,
                                is_sub_node_of_core_change: bool = False) -> Optional['CodeChangeNode']:
        """
        递归构建变更树，old_node 和 new_node 是同一逻辑节点在不同版本的表示。
        change_info_lookup: 一个字典，key为 (old_start, old_end) 或 (new_start, new_end)，value为 GumTree 解析出的 *核心* change_info。
                            用于查找 move 等操作的额外信息。
        is_sub_node_of_core_change: 标识当前处理的节点是否为核心变更节点的子节点。
                                    仅当为 False 时，才为核心节点执行特殊逻辑（如查找 parent_info, 调用 _find_moved_node_in_new_ast）。
        """
        if not old_node and not new_node:
            return None

        # 确定当前节点的位置
        old_start = old_node['start'] if old_node else -1
        old_end = old_node['end'] if old_node else -1
        new_start = new_node['start'] if new_node else -1
        new_end = new_node['end'] if new_node else -1

        # 确定当前节点的变更类型
        change_type = default_change_type
        current_change_info = None

        # --- 仅为核心节点查找 change_info ---
        if not is_sub_node_of_core_change and change_info_lookup:
            current_change_info = (change_info_lookup.get((old_start, old_end)) or
                                change_info_lookup.get((new_start, new_end)))
            if current_change_info:
                change_type = current_change_info['type']

                # --- 仅为核心节点处理复杂逻辑 ---
                # 如果是 move 且新位置为 -1，需要去新 AST 中查找真实位置
                if change_type == 'move' and new_start == -1 and new_end == -1:
                    new_parent_range_for_move_op = current_change_info.get('new_parent_range_for_move_op')
                    move_index = current_change_info.get('move_index', -1)

                    if new_parent_range_for_move_op and move_index != -1:
                        if hasattr(self, 'new_ast_path') and os.path.exists(self.new_ast_path):
                            new_ast = load_ast_file(self.new_ast_path)
                            resolved_new_start, resolved_new_end = self._find_moved_node_in_new_ast(
                                    new_ast, current_change_info
                            )
                            if resolved_new_start != -1 and resolved_new_end != -1:
                                new_start = resolved_new_start
                                new_end = resolved_new_end
                                # print(f"Resolved move node [{old_start}, {old_end}] -> [{new_start}, {new_end}] in {self.diff_file_path}")


        if not current_change_info:
            if (new_start, new_end) in change_type_map:
                change_type = change_type_map[(new_start, new_end)]
            elif (old_start, old_end) in change_type_map:
                change_type = change_type_map[(old_start, old_end)]
            elif not old_node and new_node:
                change_type = 'insert'
            elif old_node and not new_node:
                change_type = 'delete'
            elif old_node and new_node and old_node['node_type'] == new_node['node_type']:
                change_type = 'unchanged'
            else:
                # inherit from parent or default
                change_type = default_change_type
        # --- 非核心节点处理结束 ---

        # 创建当前 CodeChangeNode
        node = CodeChangeNode(
            node_type=(new_node or old_node)['node_type'],
            content=(new_node or old_node)['content'],
            start_pos=new_start,
            end_pos=new_end,
            old_start=old_start,
            old_end=old_end,
            change_type=change_type
        )

        # 递归处理子节点
        old_children = old_node.get('children', []) if old_node else []
        new_children = new_node.get('children', []) if new_node else []

        # --- 子节点对齐逻辑 (Simplified) ---
        old_child_map = {(c['start'], c['end']): c for c in old_children}
        new_child_map = {(c['start'], c['end']): c for c in new_children}

        for new_child_key, new_child_node in new_child_map.items():
            old_child_node = old_child_map.get(new_child_key)
            if old_child_node:
                # 递归处理子节点，标记为子节点
                child_change_node = self._build_full_tree_recursive(old_child_node, new_child_node, change_type_map, change_type, change_info_lookup, is_sub_node_of_core_change=True)
                if child_change_node:
                    node.add_child(child_change_node)
                del old_child_map[new_child_key]

        for old_child_node in old_child_map.values():
            # 递归处理子节点，标记为子节点
            child_change_node = self._build_full_tree_recursive(old_child_node, None, change_type_map, change_type, change_info_lookup, is_sub_node_of_core_change=True)
            if child_change_node:
                node.add_child(child_change_node)

        for new_child_key, new_child_node in new_child_map.items():
            old_corresponding = None
            # 递归处理子节点，标记为子节点
            child_change_node = self._build_full_tree_recursive(old_corresponding, new_child_node, change_type_map, change_type, change_info_lookup, is_sub_node_of_core_change=True)
            if child_change_node:
                node.add_child(child_change_node)

        return node

def parse_range(range_str):
    """
    解析范围字符串
    """
    if pd.isna(range_str) or range_str is None or str(range_str).strip() == "":
        return None, None
    
    range_str = str(range_str).strip()
    if not (range_str.startswith('[') and range_str.endswith(']')):
        return None, None
    
    # 提取中间部分
    inner = range_str[1:-1].strip()
    if not inner or inner.lower() == 'nan':
        return None, None
    
    parts = inner.split(',')
    if len(parts) != 2:
        return None, None
    
    try:
        start = int(parts[0].strip())
        end = int(parts[1].strip())
        return start, end
    except (ValueError, TypeError):
        return None, None

def is_overlap_with_labeled_range(change_data, labeled_old_start, labeled_old_end, labeled_new_start, labeled_new_end):
    """
    检查变更数据是否与标记的范围重叠
    """
    # 检查新版本位置是否重叠
    change_new_start = change_data['start_pos']
    change_new_end = change_data['end_pos']
    
    new_overlap = not (change_new_start > labeled_new_end or change_new_end < labeled_new_start)
    
    # 检查旧版本位置是否重叠
    change_old_start = change_data['old_start']
    change_old_end = change_data['old_end']
    
    old_overlap = not (change_old_start > labeled_old_end or change_old_end < labeled_old_start)
    
    return new_overlap and old_overlap

def ranges_overlap(start1, end1, start2, end2):
    """判断两个 [start, end] 范围是否重叠，[-1,-1] 视为无效"""
    if start1 == -1 and end1 == -1:
        return False
    return not (end1 < start2 or start1 > end2)


def load_and_label_changes(xlsx_file_path: str):
    """
    读取 xlsx 文件并为提取的 changes 打标。
    - 先按 homework_id 分组加速匹配
    - 要求 student_id、homework_id、file_name 完全一致
    - 只要 old 或 new 范围有重合即标记为 True
    """
    # 读取 xlsx 文件的所有工作表
    excel_file = pd.ExcelFile(xlsx_file_path)
    
    # 构建按 homework_id 分组的标注映射
    # label_by_hw[hw_id] = {(student_id, file_name): [(old_start, old_end, new_start, new_end), ...]}
    label_by_hw = defaultdict(lambda: defaultdict(list))
    
    # 遍历所有工作表
    for sheet_name in excel_file.sheet_names:
        if sheet_name in excel_name:
            # 找到对应的 homework_id
            try:
                idx = excel_name.index(sheet_name)
                homework_id = str(homework_ids[idx])
            except ValueError:
                continue  # 跳过无关工作表
            
            # 读取当前工作表
            df_sheet = pd.read_excel(xlsx_file_path, sheet_name=sheet_name)
            
            for _, row in df_sheet.iterrows():
                student_id = str(row['student_id'])
                file_name = str(row['file_name']) 
                old_range = row['old']
                new_range = row['new']
                
                # 解析 [start, end] 格式
                try:
                    old_start, old_end = parse_range(old_range)
                    new_start, new_end = parse_range(new_range)
                except:
                    continue  # 跳过格式错误的行
                
                # 存入按 homework_id 分组的字典
                key = (student_id, file_name)
                label_by_hw[homework_id][key].append((old_start, old_end, new_start, new_end))
    
    # 为所有变更数据打标
    labeled_data = []
    true_num = 0
    for record in all_change_data:
        student_id = str(record['student_id'])
        homework_id = str(record['homework_id'])
        file_path = record['file_path']
        
        # 从完整路径中提取纯文件名（去掉目录和 .txt）
        extracted_file_name = os.path.basename(file_path)
        if extracted_file_name.endswith('.txt'):
            extracted_file_name = extracted_file_name[:-4]
        
        # 构建匹配键
        match_key = (student_id, extracted_file_name)
        
        # 只在当前 homework_id 下查找
        is_labeled = False
        if homework_id in label_by_hw and match_key in label_by_hw[homework_id]:
            change_data = record['change_data']
            for child in change_data.get('children', []):
                child_old_start = child['old_start']
                child_old_end = child['old_end']
                child_new_start = child['start_pos']
                child_new_end = child['end_pos']

                # 判断子节点的有效性
                old_valid = not (child_old_start == -1 and child_old_end == -1)
                new_valid = not (child_new_start == -1 and child_new_end == -1)

                # 与当前 homework_id 下所有标注项比对
                for old_start, old_end, new_start, new_end in label_by_hw[homework_id][match_key]:
                    # 旧版本重叠检查（若有效）
                    old_match = (not old_valid) or ranges_overlap(child_old_start, child_old_end, old_start, old_end)
                    # 新版本重叠检查（若有效）
                    new_match = (not new_valid) or ranges_overlap(child_new_start, child_new_end, new_start, new_end)

                    if old_match or new_match:
                        is_labeled = True
                        true_num += 1
                        break  # 找到一个重叠子节点即可
                if is_labeled:
                    break  # 跳出子节点循环
        record['label'] = is_labeled
        labeled_data.append(record)
    
    print(f"{true_num} changes is labeled as true")
    return labeled_data

def process_all_data():
    """
    遍历处理所有数据，处理旧版本到新版本的变更，并用旧旧到旧的变更进行过滤
    """
    changes = {}
    for i in range(len(homework_ids)-1, 0, -1):
        homework_id = homework_ids[i]
        mid_path = mid_data_path[i]
    
        mid_path = str(DATA_ROOT / mid_path)
        print(f"Processing homework {homework_id} at {mid_path}")
        
        if not os.path.exists(mid_path):
            print(f"Path does not exist: {mid_path}")
            continue
            
        students = os.listdir(mid_path)
        for index, student_id in enumerate(students):
            student_path = os.path.join(mid_path, student_id)
            if not os.path.isdir(student_path):
                continue
                
            print(f"Processing student {student_id} in {mid_path}, {index}/{len(students)}")
            
            # 获取当前作业路径
            current_hw_path = os.path.join(student_path, str(homework_id))

            if not os.path.exists(current_hw_path):
                continue
            
            # 存储需要的变更信息
            old_to_new_changes = {} 
            old_to_old_changes = {}  
            
            # 遍历当前作业目录，只处理B目录（旧→新）和A目录（旧旧→旧）中的变更文件
            for root, dirs, files in os.walk(current_hw_path):
                if os.path.basename(root) == 'B': 
                    for file in files:
                        if file.endswith('cpp.txt') or file.endswith('c.txt') or file.endswith('h.txt'):
                            continue
                        elif file.endswith('.txt'):
                            full_file_path = os.path.join(root, file)
                            # 提取旧→新的变更（主要收集这个）
                            changes = extract_code_changes(full_file_path)
                            old_to_new_changes[file] = changes
                            
                elif os.path.basename(root) == 'A':  
                    for file in files:
                        if file.endswith('cpp.txt') or file.endswith('c.txt') or file.endswith('h.txt'):
                            continue
                        elif file.endswith('.txt'):
                            full_file_path = os.path.join(root, file)
                            # 提取旧旧→旧的变更
                            changes = extract_code_changes(full_file_path)
                            old_to_old_changes[file] = changes
            
            # 对每个文件进行过滤处理
            for file_name in old_to_new_changes:
                if file_name in old_to_old_changes:
                    # 获取两个版本的变更
                    old_new_changes = old_to_new_changes[file_name]  
                    old_old_changes = old_to_old_changes[file_name]  

                    # 合并变更
                    merged_changes = merge_adjacent_changes(old_new_changes)

                    # 过滤变更（使用旧旧→旧的变更信息来过滤旧→新的变更）
                    filtered_changes = filter_changes(merged_changes, old_old_changes, 
                                                   student_id, homework_id, file_name)
                                        
                    save_filtered_changes(filtered_changes, student_id, homework_id, file_name)
                else:
                    old_new_changes = old_to_new_changes[file_name]
                    merged_changes = merge_adjacent_changes(old_new_changes)
                    save_filtered_changes(merged_changes, student_id, homework_id, file_name)


def save_to_file(filename: str = "code_changes_data.pkl"):
    """
    将变更数据保存到pickle文件
    """
    with open(filename, 'wb') as f:
        pickle.dump(all_change_data, f)
    print(f"Data saved to {filename}")

def load_from_file(filename: str = "code_changes_data.pkl"):
    """
    从pickle文件加载变更数据
    """
    with open(filename, 'rb') as f:
        data = pickle.load(f)
    return data

def parse_args():
    parser = argparse.ArgumentParser(description="Build processed_data.pkl from existing mid_data_* and raw labels.")
    parser.add_argument("--data-root", default=str(DATA_ROOT), help="Directory containing data/ and mid_data_*.")
    parser.add_argument("--raw-data", default=str(PROJECT_ROOT / "raw_data.xlsx"), help="Manual label Excel.")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "processed_data.pkl"), help="Output pickle path.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    DATA_ROOT = Path(args.data_root).resolve()
    root_path = str(DATA_ROOT.parent)
    folder_name = DATA_ROOT.name
    print("Starting data processing with filtering...")
    if not mid_data_path or not homework_ids:
        print("Error: mid_data_path and homework_ids must be set before running")
    if len(mid_data_path) != len(homework_ids):
        print("Error: mid_data_path and homework_ids must have the same length")
    
    process_all_data()
    print(f"Data processing completed. total: {len(all_change_data)}")
    load_and_label_changes(args.raw_data) #标注正样本
    save_to_file(args.output)
