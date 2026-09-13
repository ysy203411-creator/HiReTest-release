import os
from typing import List, Dict, Tuple, Set, Optional
import re
import pickle
import pandas as pd
from collections import defaultdict
import argparse
from pathlib import Path

try:
    from .paths import data_workspace_root, release_root
except ImportError:  # Support direct execution from src/hiretest.
    from paths import data_workspace_root, release_root


# Runtime dataset mappings are supplied through CLI arguments or environment variables.
PROJECT_ROOT = release_root()
DATA_ROOT = data_workspace_root()
RAW_SUBMISSION_ROOT = Path(os.environ.get("HIRETEST_DATA_ROOT", PROJECT_ROOT / "data"))
mid_data_path = []
excel_name = []
homework_ids = []

#Declare type list
declaration_names = ["VariableDeclarationFragment", "FieldDeclaration", "VariableDeclarationStatement",
                    "MethodDeclaration", "decl_stmt", "function_decl", "function", "struct", "typedef",
                    "SingleVariableDeclaration", "TypeDeclaration"]

#List to store all change data
all_change_data = []

def logical_to_physical_offset(file_path: str, log_start: int, log_end: int) -> Tuple[int, int]:
    """
    Map GumTree TextDiff's logical character index to the physical byte offset in the original file.
    
    GumTree TextDiff Rules:
    - \r\n is counted as 1 logical character (normalized to \n)
    - Other characters are counted as 1 each
    
    Args:
        file_path: Source code file path
        log_start: TextDiff's starting logical position
        log_end: TextDiff's ending logical position
    
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
        #Record hit position
        if gum_idx == log_start and phys_start is None:
            phys_start = i
        if gum_idx == log_end and phys_end is None:
            phys_end = i
        if phys_start is not None and phys_end is not None:
            break
        
        #\r\n is counted as 1 step in logic and occupies 2 bytes physically
        if raw[i] == 0x0D and i + 1 < n and raw[i+1] == 0x0A:
            gum_idx += 1
            i += 2
        else:
            gum_idx += 1
            i += 1
    
    #Boundary fallback
    if phys_end is None:
        phys_end = i
    return phys_start or 0, min(phys_end, n)


def extract_code_by_logical_position(file_path: str, log_start: int, log_end: int, 
                                     snap_to_boundary: bool = True) -> str:
    """
    Extract code snippet from source code file based on TextDiff logical coordinates.
    
    Args:
        file_path: Source code file path
        log_start: TextDiff start position
        log, log_end: TextDiff end position
        snap_to_boundary: Whether to smartly snap to complete syntax boundary (solve ±1 truncation issue)
    
    Returns:
        Extracted code string
    """
    if log_start == -1 or log_end == -1:
        return ""
    
    #1. Logical coordinate -> Physical offset
    phys_start, phys_end = logical_to_physical_offset(file_path, log_start, log_end)
    
    #2. Read original file (binary mode preserves \r\n)
    with open(file_path, 'rb') as f:
        raw = f.read()
    
    #3. Smart boundary adhesion (optional, resolves ±1 error caused by GumTree's open/close interval convention)
    if snap_to_boundary:
        #Scan up to 50 bytes forward to find public/private/protected/class modifiers
        scan_back = max(0, phys_start - 50)
        window = raw[scan_back:phys_start]
        for kw in [b'public ', b'private ', b'protected ', b'static ', b'class ', b'interface ']:
            idx = window.rfind(kw)
            if idx != -1:
                phys_start = scan_back + idx
                break
        else:
            #If no modifier is found, fallback to the start of the previous line
            nl = window.rfind(b'\n')
            if nl != -1:
                phys_start = scan_back + nl + 1
        
        #Search backward for closing } and trim trailing whitespace
        scan_fwd = min(len(raw), phys_end + 100)
        window_fwd = raw[phys_end:scan_fwd]
        brace = window_fwd.find(b'}')
        if brace != -1:
            phys_end = phys_end + brace + 1
        #Skip trailing consecutive whitespace
        while phys_end < len(raw) and raw[phys_end:phys_end+1] in b' \t\r\n':
            phys_end += 1
    
    #4. Extract and decode
    try:
        return raw[phys_start:phys_end].decode('utf-8', errors='ignore')
    except:
        return ""

def load_ast_file(file_path: str) -> Dict:
    """
    Parse AST file (indentation format) into nested dictionary tree
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    #Build (line content, indentation level) list
    nodes = []
    for line in lines:
        if not line.strip():
            continue
        #Calculate indentation level (every 4 spaces is one level)
        indent = len(line) - len(line.lstrip(' '))
        level = indent // 4
        content = line.strip()
        nodes.append((content, level))
    
    #Recursively build the tree
    def build_tree(nodes, start_idx, current_level):
        if start_idx >= len(nodes):
            return None, start_idx
        
        content, level = nodes[start_idx]
        if level != current_level:
            return None, start_idx
        
        #Parse current node
        node = parse_ast_node_line(content)
        children = []
        next_idx = start_idx + 1
        
        #Collect all child nodes
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
        #Fallback when parsing fails
        return {'node_type': line, 'content': '', 'start': -1, 'end': -1}
    
    node_type = match.group(1)
    content = (match.group(2) or '').strip()  #group(2) may be None
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
    Find the smallest parent node in AST that contains [target_start, target_end]"""
    def dfs(node):
        if node is None:
            return None
        
        #Check if current node contains target range
        if node['start'] <= target_start and target_end <= node['end']:
            #Check if child nodes also contain (find the smallest one)
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
    Merge adjacent code changes"""
    #Simplified implementation: treat all changes as a single unit
    if not changes:
        return []
    
    #The actual merging logic needs to determine which changes are adjacent based on AST structure
    #This returns the original list; actual merging requires more complex AST analysis
    return changes

def filter_changes(new_changes: List[Dict], old_changes: List[Dict], 
                  student_id: str, homework_id: str, file_name: str) -> List[Dict]:
    """
    Filter changes based on rules"""
    filtered_changes = []
    for change in new_changes:
        #Rule 1: Filter out nodes added in old-old → old change
        filtered_change = remove_newly_added_nodes(change, old_changes)
        
        if filtered_change is None:  #If the root node is deleted
            continue
            
        #Rule 2: If all changed node types are declaration types, exclude (excluding root node)
        if is_declaration_only_change(filtered_change):
            continue
            
        #Rule 3: If the number of lines involved exceeds 50, exclude
        if get_line_count(filtered_change, student_id, homework_id, file_name) > 50:
            continue
            
        filtered_changes.append(filtered_change)
    
    return filtered_changes

def remove_newly_added_nodes(change: Dict, old_changes: List[Dict]) -> Dict:
    """
    Remove nodes added in the old-old → old change, keep other nodes
    """
    def filter_node_recursive(node: Dict) -> Dict:
        #Check if the current node is newly added
        if is_newly_added_node_single(node, old_changes):
            return None  #Delete this node
        
        #Recursively filter child nodes
        filtered_children = []
        for child in node['children']:
            filtered_child = filter_node_recursive(child)
            if filtered_child is not None:
                filtered_children.append(filtered_child)
        
        #If the node is not newly added, but all child nodes are deleted and the change type of child nodes are all new, delete this node as well
        if filtered_children:
            #If there are retained child nodes, keep the current node
            node_copy = node.copy()
            node_copy['children'] = filtered_children
            return node_copy
        else:
            #If there are no retained child nodes, check whether to delete the current node
            #If the original node has child nodes, but now there are none, it means all child nodes are newly added
            if node['children']:  #The original node had child nodes, but now there are none
                return None
            else:
                #The original node had no child nodes, keep the current node
                node_copy = node.copy()
                node_copy['children'] = []
                return node_copy
    
    return filter_node_recursive(change)

def is_newly_added_node_single(node: Dict, old_changes: List[Dict]) -> bool:
    """Check if a single node was newly added in the old-old → old change"""
    for old_change in old_changes:
        if old_change.get('change_type') == 'insert':
            #If there are insertions in old-old → old, check if the current node is one of these inserted nodes
            if is_overlapping_position_node(node, old_change):
                return True
    return False

def is_overlapping_position_node(node: Dict, change_info: Dict) -> bool:
    """Check if the node position overlaps with the change information position"""
    #Check if the position ranges overlap
    return not (node['old_start'] > change_info['old_end'] or 
                node['old_end'] < change_info['old_start'])

def is_declaration_only_change(change: Dict) -> bool:
    """Check if the change involves only declared type nodes (excluding root node)"""
    def check_node_types(node: Dict) -> bool:
        #Check if the current node type is a declared type
        if node['node_type'] in declaration_names:
            #Check if all child nodes are also declared types
            if node['children']:
                return all(check_node_types(child) for child in node['children'])
            else:
                return True
        return False
    
    #Do not check root node, only check child nodes
    if change['children']:
        return all(check_node_types(child) for child in change['children'])
    return False

def get_line_count(change: Dict, student_id: str, homework_id: str, file_name: str) -> int:
    """Calculate the number of lines affected by the change"""
    #Need to read the source code file to calculate line numbers
    #Build the source code path (new version code)
    code_path = RAW_SUBMISSION_ROOT / student_id / homework_id / "last" / file_name.replace('.txt', '')
    
    code_file = str(code_path)
    
    if not os.path.exists(code_file):
        return 0  #If source code is not found, return 0
    
    try:
        with open(code_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        #Count the number of lines affected by the change
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
    Get line numbers based on character positions (based on the list of lines read in text mode)
    
    Note: This function assumes that lines are read by read_code_file(),
    each line already includes the original newline character, and position calculations are based on the original file byte offset.
    """
    if position == -1:  #Deleted node
        return -1
    
    current_pos = 0
    for i, line in enumerate(lines):
        line_length = len(line)  #Use the original length directly, no longer +1
        if current_pos <= position < current_pos + line_length:
            return i + 1
        current_pos += line_length
    
    return -1

def is_overlapping_position(change1: Dict, change2: Dict) -> bool:
    """
    Check if the positions of the two changes overlap
    """
    #Check if the range of positions overlaps
    return not (change1['start_pos'] > change2['end_pos'] or 
                change1['end_pos'] < change2['start_pos'])

def read_code_file(file_path: str) -> List[str]:
    """
    Read the code file (text mode, for line counting etc. scenarios that do not rely on precise positions)
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
    [New] Read the source code in binary mode, preserving original \r\n newline characters
    For scenarios that require precise character position mapping (such as GumTree TextDiff coordinate extraction)
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
    Calculate the number of lines affected by the change (take the higher value between new and old versions), based on child node ranges
    """
    #Get all line numbers involved by the child nodes
    old_lines_set = set()
    new_lines_set = set()
    
    def collect_lines_recursive(node: Dict):
        #Collect the line numbers of the current node
        old_start_line = get_line_number_from_position(old_code_lines, node['old_start'])
        old_end_line = get_line_number_from_position(old_code_lines, node['old_end'])
        new_start_line = get_line_number_from_position(new_code_lines, node['start_pos'])
        new_end_line = get_line_number_from_position(new_code_lines, node['end_pos'])
        
        #Add the line numbers involved in the old version
        if old_start_line != -1 and old_end_line != -1:
            for line_num in range(old_start_line, old_end_line + 1):
                old_lines_set.add(line_num)
        
        #Add line numbers involved in new version
        if new_start_line != -1 and new_end_line != -1:
            for line_num in range(new_start_line, new_end_line + 1):
                new_lines_set.add(line_num)
        
        #Recursively process child nodes
        for child in node['children']:
            collect_lines_recursive(child)
    
    #Collect all line numbers involved from root node
    collect_lines_recursive(change)
    
    #Calculate line count (take maximum of line counts from new and old versions)
    old_lines_count = len(old_lines_set)
    new_lines_count = len(new_lines_set)
    
    return max(old_lines_count, new_lines_count)

def get_function_class_length(change: Dict, old_code_lines: List[str], new_code_lines: List[str]) -> int:
    """
    Get length of containing function/class (take higher value from new and old versions)
    """
    #Here need to find the range of function/class containing the current change based on AST structure
    #Simplified implementation: return entire file length as example
    return max(len(old_code_lines), len(new_code_lines))

def get_avg_change_lines_in_scope(change: Dict, old_code_lines: List[str], new_code_lines: List[str]) -> float:
    """
    Calculate average line count of changed domain
    """
    #Here need to find all changes within same function/class and calculate average
    #Simplified implementation: return line count of current change
    return calculate_change_lines(change, old_code_lines, new_code_lines)

def determine_change_type(change: Dict) -> str:
    """
    Determine change type: insert/delete/update/modify
    """
    #Count the number of each change type
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
        return 'Update'
    
    #Only insert
    if insert_count > 0 and delete_count == 0 and update_count == 0 and other_count == 0:
        return 'Insert'
    
    #Only delete
    if delete_count > 0 and insert_count == 0 and update_count == 0 and other_count == 0:
        return 'Delete'
    
    #Only update
    if update_count > 0 and insert_count == 0 and delete_count == 0 and other_count == 0:
        return 'Update'
    
    #Other cases
    return 'Update'

def get_syntax_structures(change: Dict) -> List[str]:
    """
    Get the syntax structure involved in the change (root node and child node types)
    """
    structures = [change['node_type']]
    
    #Add child node type
    for child in change['children']:
        structures.append(child['node_type'])
    
    return structures

def check_method_signature_change(change: Dict, old_code_lines: List[str], new_code_lines: List[str]) -> Dict:
    """
    Check method signature change
    """
    #Check if it involves method or class name and parameter change
    method_changed = False
    class_changed = False
    
    def check_node_for_signature_change(node: Dict):
        nonlocal method_changed, class_changed
        
        if node['node_type'] in ['MethodDeclaration', 'function_decl', 'function']:
            #Check if method name and parameters have changed
            method_changed = True
        elif node['node_type'] in ['TypeDeclaration', 'struct', 'class']:
            #Check class name change
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
    Save filtered changes to global list
    """
    #Read new and old version code files
    old_code_path = RAW_SUBMISSION_ROOT / student_id / homework_id / "first" / file_name.replace('.txt', '')
    new_code_path = RAW_SUBMISSION_ROOT / student_id / homework_id / "last" / file_name.replace('.txt', '')
    
    old_code_lines = read_code_file(str(old_code_path))
    new_code_lines = read_code_file(str(new_code_path))
    
    for change in changes:
        #Calculate changed line count
        change_lines = calculate_change_lines(change, old_code_lines, new_code_lines)
        
        #Calculate function/class length and change ratio
        function_class_length = get_function_class_length(change, old_code_lines, new_code_lines)
        change_ratio = change_lines / max(function_class_length, 1)  #Avoid division by zero
        
        #Calculate average line change in the scope
        avg_change_lines_in_scope = get_avg_change_lines_in_scope(change, old_code_lines, new_code_lines)
        
        #Determine change type
        change_type = determine_change_type(change)
        
        #Get syntax structure involved in the change
        syntax_structures = get_syntax_structures(change)
        
        #Judge method signature change
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
    Extract code change
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
        self.start_pos = start_pos  #New version location
        self.end_pos = end_pos      #New version location
        self.old_start = old_start  #Old version location
        self.old_end = old_end      #Old version location
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
        self.matches = {}  #Old character position -> New character position
        self.match_ranges_old_to_new = {} # (old_start, old_end) -> (new_start, new_end)
        self.changes = []
        self.changes_by_new_range = {}
        self._parse_diff_file()
        
    def _infer_ast_paths(self):
        """Derive old/new version AST file paths from diff file path"""
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
        #Find location of A/B
        next_part = parts[homework_idx + 1]
        if next_part in ('A', 'B'):
            relative_parts = parts[homework_idx + 2:]  #Skip A/B
        else:
            relative_parts = parts[homework_idx + 1:]
        #Construct relative path (remove .txt)
        relative_path = os.path.join(*relative_parts)
        #Base directory
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
        #Outer loop: find '---' delimiter, indicating a new change block starts
        while i < len(lines):
            line = lines[i].strip()
            if line == '---':
                #Found '---', core change node is on the next line
                i += 1 #Move to next line
                if i >= len(lines):
                    #There is no content after '---'
                    break

                core_line = lines[i].strip()
                if not core_line:
                    #There is an empty line after '---'
                    i += 1
                    continue

                #Parsing core change node
                node_match = re.search(r'([a-zA-Z_][a-zA-Z0-9_]*)(?::\s*([a-zA-Z_][a-zA-Z0-9_]*))?\s*\[([0-9]+),([0-9]+)\](?:\s+(.*))?', core_line)
                if node_match:
                    node_type = node_match.group(1)                     #Extracting type (e.g. SimpleName)
                    identifier = node_match.group(2)                    #Extracting identifier after colon (e.g. errorOutputPath)
                    raw_start = int(node_match.group(3))               #Extracting start position
                    raw_end = int(node_match.group(4))                 #Extracting end position
                    extra_content = node_match.group(5) or ""          #Extracting additional content
                    content = identifier if identifier else extra_content
                    #Here change_type is a function parameter representing the overall type of this change block (e.g. 'delete-tree')
                    actual_change_type = self._map_change_type(change_type)

                    #--- Initialization ---
                    old_start_CN, old_end_CN = -1, -1
                    new_start_CN, new_end_CN = -1, -1
                    parent_info = None

                    #--- Parsing core change node (CN) and its parent node (PN) information based on change type ---
                    #Note: Now we are only looking for parent_info for the core change node (i.e. the node defined by core_line)
                    if actual_change_type in ('insert', 'Insert'):
                        # --- INSERT LOGIC ---
                        new_start_CN, new_end_CN = raw_start, raw_end
                        # ... (INSERT parent_info logic here, similar to before but only for core_line) ...
                        #Parse 'to' part (target parent node information)
                        potential_parent_old_start = -1
                        potential_parent_old_end = -1
                        j = i + 1 #Start searching from the line after the core node line
                        while j < len(lines) and not lines[j].strip().lower().startswith('to'):
                            j += 1
                        if j < len(lines) and lines[j].strip().lower().startswith('to'):
                            j += 1 #Skip 'to'
                            if j < len(lines):
                                parent_line = lines[j].strip()
                                parent_match = re.search(r'([a-zA-Z_][a-zA-Z0-9_:]*)\s*\[([0-9]+),([0-9]+)\]', parent_line)
                                if parent_match:
                                    potential_parent_old_start = int(parent_match.group(2))
                                    potential_parent_old_end = int(parent_match.group(3))

                                    #1. Search in the old version AST
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
                                                #2. Try to find new position via match
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
                                        #3. If not found in old version AST, 'to' may point to new version range (parent node is also inserted)
                                        if os.path.exists(self.new_ast_path):
                                            new_ast = load_ast_file(self.new_ast_path)
                                            found_node_in_new = find_parent_in_ast(new_ast, potential_parent_old_start, potential_parent_old_end)
                                            if found_node_in_new and found_node_in_new['start'] <= potential_parent_old_start and potential_parent_old_end <= found_node_in_new['end']:
                                                #4. Found in new version AST, indicating parent node is also newly inserted
                                                pn_new_start = found_node_in_new['start']
                                                pn_new_end = found_node_in_new['end']
                                                #Parent node does not exist in old version
                                                pn_old_start, pn_old_end = -1, -1

                                    #Build parent_info (only for core node)
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
                        #else: # no 'to' line
                        #     print(f"Debug: Expected 'to' line for insert in {self.diff_file_path}")


                    elif actual_change_type in ('update', 'Update'):
                        # --- UPDATE LOGIC ---
                        old_start_CN, old_end_CN = raw_start, raw_end
                        new_start_CN = self.matches.get(raw_start, -1)
                        new_end_CN = self.matches.get(raw_end, -1)
                        # ... (UPDATE parent_info logic here) ...
                        #(Use previously provided UPDATE parent_info logic)
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
                        #(Use previously provided MOVE parent_info logic)
                        potential_parent_old_start = -1
                        potential_parent_old_end = -1
                        j = i + 1
                        while j < len(lines) and not lines[j].strip().lower().startswith('to'):
                            j += 1
                        if j < len(lines) and lines[j].strip().lower().startswith('to'):
                            j += 1 #Skip 'to'
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
                        # else: # no 'to' line
                        #     print(f"Debug: Expected 'to' line for move in {self.diff_file_path}")


                    elif actual_change_type in ('delete', 'Delete'):
                        # --- DELETE LOGIC (CORRECTED AGAIN) ---
                        old_start_CN, old_end_CN = raw_start, raw_end
                        # new_start_CN, new_end_CN remain (-1, -1)

                        # CN parent node (PN) information (only find parent of *core change node* )
                        pn_old_start, pn_old_end = -1, -1
                        pn_new_start, pn_new_end = -1, -1

                        if old_start_CN != -1 and old_end_CN != -1 and os.path.exists(self.old_ast_path):
                            try:
                                old_ast = load_ast_file(self.old_ast_path)
                                # Find the *core change node* itself (i.e. node defined by core_line)
                                # Use exact search function
                                target_node_old = self._find_node_in_ast_by_range(old_ast, old_start_CN, old_end_CN)
                                # If exact search fails, fall back to inclusive search
                                if not target_node_old:
                                    target_node_old = find_parent_in_ast(old_ast, old_start_CN, old_end_CN)

                                if target_node_old and target_node_old['start'] == old_start_CN and target_node_old['end'] == old_end_CN:
                                    # Confirm that the exact match node is found
                                    # Check if *core change node* is root node
                                    if target_node_old['start'] != old_ast.get('start', -1) or target_node_old['end'] != old_ast.get('end', -1):
                                        # --- Key change: use _find_parent_by_child_range to find parent node ---
                                        parent_node_old = self._find_parent_by_child_range(old_ast, target_node_old['start'], target_node_old['end'])
                                        if parent_node_old:
                                            pn_old_start = parent_node_old['start']
                                            pn_old_end = parent_node_old['end']
                                            # Try to find new position of parent node via match
                                            pn_new_range_from_match = self.match_ranges_old_to_new.get((pn_old_start, pn_old_end), None)
                                            if pn_new_range_from_match:
                                                pn_new_start, pn_new_end = pn_new_range_from_match
                                            else:
                                                # Here the parent node also changed (deleted or updated), but now there is no search for the changed position
                                                #print(f"Debug:[{old_start_CN},{old_end_CN}] Delete parent [{pn_old_start}, {pn_old_end}] has no match range. New location unknown or parent also changed.")
                                                pass
                                        else:
                                            #If target_node_old is the root node, it has no parent node
                                            #Or the parent node could not be found in the AST (theoretically should not happen unless the AST structure is corrupted)
                                            pass
                                    else:
                                        #*Core changed node* is the root node, has no parent node
                                        pass
                                else:
                                    #No exact matching node was found, or find_parent_in_ast returned something that is not an exact match
                                    # print(f"Debug: Could not find exact core delete node [{old_start_CN}, {old_end_CN}] in old AST.")
                                    pass
                            except Exception as e:
                                print(f"Warning: Failed to load/parse old AST for delete *core node's* parent lookup in {self.diff_file_path}: {e}")
                        else:
                            print(f"Debug: Old AST path does not exist or delete *core node* [{old_start_CN}, {old_end_CN}] has invalid range for parent lookup: {self.old_ast_path}")

                        #Build parent_info (only for core nodes)
                        if pn_old_start != -1:
                            parent_info = {
                                'node_type': find_parent_in_ast(load_ast_file(self.old_ast_path), pn_old_start, pn_old_end)['node_type'], #Search for node type again
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

                    #--- Store change information (only for core changed node) ---
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
                    #--- Parse 'to' and 'at' (if needed to store - only for move/insert) ---
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

                    #--- Skip child line ---
                    #Core node line is i, now start searching for the next independent change line from i+1
                    j = i + 1
                    #Search for the next non-indented line (independent change line, 'to'/'at' line, or end of file)
                    #One approach is to calculate the indentation of the core node line
                    initial_indent = len(lines[i]) - len(lines[i].lstrip(' '))
                    while j < len(lines):
                        current_line_stripped = lines[j].strip()
                        if not current_line_stripped:
                            j += 1
                            continue
                        current_indent = len(lines[j]) - len(lines[j].lstrip(' '))
                        #If the current line's indentation is less than or equal to the initial core node line's indentation,
                        #or it is a line that does not belong to the current core node's substructure such as 'to'/'at'
                        if current_indent <= initial_indent or lines[j].strip().lower() in ['to', 'at']:
                            #found the next independent line or 'to'/'at' line, stop skipping
                            break
                        #otherwise, the current line is a child node, continue
                        j += 1
                    #point i to the next independent line, prepare for the next outer loop iteration
                    i = j
                    #the outer loop continues because i has been updated
                    continue # Explicitly continue outer loop after skipping sub-nodes

                else:
                    #'---' is not followed by a valid node line, skip
                    i += 1
                    continue
            else:
                #the current line is not '---', skip
                i += 1
                continue

    def _find_node_in_ast_by_range(self, ast_node: Dict, target_start: int, target_end: int) -> Optional[Dict]:
        """
        Find a node in the AST that exactly matches the [target_start, target_end] range.
        Return the node dictionary if found; otherwise return None.
        """
        if ast_node['start'] == target_start and ast_node['end'] == target_end:
            return ast_node

        #Recursively check child nodes
        for child in ast_node.get('children', []):
            result = self._find_node_in_ast_by_range(child, target_start, target_end)
            if result:
                return result

        return None

    def _find_parent_by_child_range(self, ast_root: Dict, child_start: int, child_end: int) -> Optional[Dict]:
        """
        In the AST root node, find the parent node of the child node based on its [start, end] range.
        If the child node is the root node itself, return None.
        If found, return the parent node dictionary; otherwise return None.
        """
        #Check if it is the root node
        if ast_root['start'] == child_start and ast_root['end'] == child_end:
            # print(f"Debug: Node [{child_start}, {child_end}] is the root node, has no parent.")
            return None #The root node has no parent node

        def dfs(node, parent=None):
            if node['start'] <= child_start and child_end <= node['end']:
                #Check if the current node is the target child node
                if node['start'] == child_start and node['end'] == child_end:
                    return parent #Return its parent node
                #Otherwise, continue searching in the child nodes
                for child in node.get('children', []):
                    result = dfs(child, node)
                    if result:
                        return result
            return None

        return dfs(ast_root)

    def _find_corresponding_node_in_other_ast(self, other_ast_root: Dict, node_info: Dict) -> Optional[Dict]:
        """
        Try to find the corresponding node in other_ast_root based on node_info.
        node_info: A dictionary containing information like 'node_type', 'start', 'end', etc.
        Return the found corresponding node or None.
        Strategy: Prioritize exact position matching, fall back to type and structure matching.
        """
        target_type = node_info['node_type']
        target_start = node_info['start']
        target_end = node_info['end']

        #Strategy 1: Try exact position matching
        corresponding_node = self._find_node_in_ast_by_range(other_ast_root, target_start, target_end)
        if corresponding_node:
            # print(f"Found corresponding node by exact range [{target_start}, {target_end}] in other AST.")
            return corresponding_node

        #Strategy 2: Try type and structure matching (more complex, simplified here as finding nodes of the same type and checking if the range is close enough)
        def search_by_type_and_proximity(node):
            if node['node_type'] == target_type:
                #Check if the range is close enough (e.g., start position difference less than 10)
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
        Based on the GumTree information from the move operation (old version's new_parent_info and move_index (new position index)),
        Find the new position of the moved node in the new version AST.
        move_change_info['new_parent_range_for_move'] contains the range of the target parent node in the *new version* AST.
        move_change_info['move_index'] is the index of the moved node in the *new version* parent node's child list.
        move_change_info['old_start/end'] is the range of the moved node in the *old version*.
        Return (new_start, new_end) or (-1, -1).
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

        #Step 1: Find the parent node in the new version AST
        new_parent_node_in_new_ast = find_parent_in_ast(new_ast_root, new_parent_start, new_parent_end)
        if not new_parent_node_in_new_ast or not (new_parent_node_in_new_ast['start'] == new_parent_start and new_parent_node_in_new_ast['end'] == new_parent_end):
            # print(f"Debug: Could not find or match new parent node [{new_parent_start}, {new_parent_end}] in new AST for move in {self.diff_file_path}. Found: {new_parent_node_in_new_ast}")
            return -1, -1

        #Step 2: Get the child list of the new version parent node and find the target position based on move_index (new version index)
        new_parent_children = new_parent_node_in_new_ast.get('children', [])
        if move_index >= len(new_parent_children):
            # print(f"Warning: move_index {move_index} is invalid (new parent has {len(new_parent_children)} children) for move in {self.diff_file_path}. Attempting fallback.")
            #Fallback: Try to find in the old version AST based on the original position [original_old_start, original_old_end] of the moved node in the old version
            #Then find new position via match mapping
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
                        #Attempt to find new position via match mapping
                        new_start_from_match = self.matches.get(original_old_node_in_old_ast['start'], -1)
                        new_end_from_match = self.matches.get(original_old_node_in_old_ast['end'], -1)
                        if new_start_from_match != -1 and new_end_from_match != -1:
                            return new_start_from_match, new_end_from_match

                        #Fallback: Try structural/type matching in new version AST (within new parent node)
                        # print(f"Warning: Match mapping failed for fallback node [{original_old_start}, {original_old_end}] in {self.diff_file_path}. Attempting structural fallback within new parent.")
                        original_node_type = original_old_node_in_old_ast['node_type']
                        best_match = None
                        min_distance = float('inf')
                        for child in new_parent_node_in_new_ast.get('children', []):
                            if child['node_type'] == original_node_type:
                                distance = abs(child['start'] - original_old_start)
                                if distance < min_distance:
                                    min_distance = distance
                                    if min_distance <= 10: #Tolerate small position offsets
                                        best_match = child

                        if best_match:
                            # print(f"Fallback resolved move child (within new parent) [{original_old_start}, {original_old_end}] -> [{best_match['start']}, {best_match['end']}] in {self.diff_file_path}")
                            return best_match['start'], best_match['end']

                except Exception as e:
                    print(f"Warning: Failed to load or parse old AST for fallback in {self.diff_file_path}: {e}")

            return -1, -1

        #If move_index is valid, theoretically we already know the new position of the moved node is [new_start_from_match, new_end_from_match]
        #Or need to find it through other means (e.g., structural matching).
        #The key is still to find new position via `original_old_range` and `self.matches`.

        #Retry finding new position of original moved node via match mapping
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

        #If match mapping fails, try structural matching (within new parent node)
        print(f"Warning: Match mapping failed for move child [{original_old_start}, {original_old_end}] in {self.diff_file_path}. Attempting structural fallback within new parent.")
        original_node_type = original_old_node_in_old_ast['node_type'] if original_old_node_in_old_ast else ''
        best_match = None
        min_distance = float('inf')
        for child in new_parent_node_in_new_ast.get('children', []):
            if child['node_type'] == original_node_type:
                distance = abs(child['start'] - original_old_start) #Use old position as reference
                if distance < min_distance:
                    min_distance = distance
                    if min_distance <= 10: #Tolerate small position offsets
                        best_match = child

        if best_match:
            # print(f"Fallback resolved move child (within new parent) [{original_old_start}, {original_old_end}] -> [{best_match['start']}, {best_match['end']}] in {self.diff_file_path}")
            return best_match['start'], best_match['end']

        print(f"Debug: Fallback search within new parent also failed for move child [{original_old_start}, {original_old_end}] in {self.diff_file_path}")
        return -1, -1

    def _parse_match_section(self, lines: List[str]):
        """
        Parse match line, build character position mapping and node range mapping
        """
        i = 0
        while i < len(lines) - 1: #Process paired lines
            old_line = lines[i].strip()
            new_line = lines[i + 1].strip()

            old_match = re.search(r'\[([0-9]+),([0-9]+)\]', old_line)
            new_match = re.search(r'\[([0-9]+),([0-9]+)\]', new_line)

            if old_match and new_match:
                old_start, old_end = int(old_match.group(1)), int(old_match.group(2))
                new_start, new_end = int(new_match.group(1)), int(new_match.group(2))

                #Store node range mapping
                self.match_ranges_old_to_new[(old_start, old_end)] = (new_start, new_end)

                #Store character position mapping (keep original logic)
                for pos in range(old_start, old_end + 1):
                    self.matches[pos] = new_start + (pos - old_start)

            i += 2
    
    
    def _build_change_type_map(self, changes: List[Dict]) -> Dict[Tuple[int, int], str]:
        """
        Build (start, end) -> change_type mapping, including:
        - Explicitly changed nodes
        - Matched nodes (marked as 'unchanged')
        """
        mapping = {}

        #1. Explicitly changed nodes
        for ch in changes:
            key = (ch['old_start'], ch['old_end'])
            if key != (-1, -1):
                mapping[key] = ch['type']
            key_new = (ch['new_start'], ch['new_end'])
            if key_new != (-1, -1):
                mapping[key_new] = ch['type']

        #2. Match nodes (unchanged)
        for pos_old, pos_new in self.matches.items():
            #Simplify: record single points, but should record ranges
            #More precise approach is to parse the full [start, end] of match nodes
            #Assume match ranges are already in self.matches_ranges here (can be extended)
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

        #Group by parent_info, using new parent node positions
        #Ensure changes for the same parent node (in new version) are grouped together
        grouped = {}
        for ch in self.changes:
            key = None
            parent_info = ch['parent_info']
            
            if parent_info:
                #Group using new parent node positions
                key = (parent_info['node_type'], parent_info['new_start'], parent_info['new_end'])
            else:
                key = 'orphan'
                
            #Ensure key is not None to avoid dictionary key errors
            if key is None:
                key = 'orphan_with_none_key' #Or use a suitable default value, but theoretically None should not occur
                
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
        Group changes based on parent_info using the new parent node position.
        """
        parent_groups = {}

        for change in self.changes:
            parent_key = None
            parent_info = change['parent_info']

            if parent_info:
                #Group using the new parent node position
                parent_key = (parent_info['node_type'], parent_info['new_start'], parent_info['new_end'])
            else:
                parent_key = 'orphan'

            if parent_key not in parent_groups:
                parent_groups[parent_key] = []
            parent_groups[parent_key].append(change)

        return list(parent_groups.values())
    
    def _build_from_changes_only(self, changes: List[Dict]) -> Optional['CodeChangeNode']:
        """
        Rollback plan: build a tree using only the changed nodes reported by GumTree (without AST context)
        """
        if not changes:
            return None

        #Build a change_info lookup dictionary for _build_full_tree_recursive
        change_info_lookup = {}
        for ch in changes:
            if ch['old_start'] != -1:
                change_info_lookup[(ch['old_start'], ch['old_end'])] = ch
            if ch['new_start'] != -1:
                change_info_lookup[(ch['new_start'], ch['new_end'])] = ch

        #Try using a common parent node (from 'to' info in the changed file, now containing new and old positions)
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
            #No parent node: create a virtual root
            #Filter out -1 values before calculating ranges
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

        #Add explicit change nodes as child nodes
        #No longer directly create child nodes, but instead try to build a minimal AST fragment to call _build_full_tree_recursive
        #Or, create a leaf node for each change directly
        #To align with the new _build_full_tree_recursive, we can create a virtual old_node/new_node for each change,
        #then call _build_full_tree_recursive, but this would be complicated.
        #A simpler approach is: only build the root node, and the children are the changes themselves.

        #Simplified implementation: create a child node for each change
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
        Build a full change tree with dual version AST, including change nodes and context nodes.
        """
        if not changes:
            return None

        #Build a change_info lookup dictionary for _build_full_tree_recursive
        change_info_lookup = {}
        for ch in changes:
            if ch['old_start'] != -1:
                change_info_lookup[(ch['old_start'], ch['old_end'])] = ch
            if ch['new_start'] != -1:
                change_info_lookup[(ch['new_start'], ch['new_end'])] = ch

        #Step 1: Determine the root node range of the change (from GumTree changes or its parent node)
        common_parent_info = changes[0]['parent_info']
        if not common_parent_info:
            # print(f"Warning: No parent_info found for changes in {self.diff_file_path}. Using fallback.")
            return self._build_from_changes_only(changes)

        #Step 2: Load the old and new version ASTs
        try:
            old_ast_root = load_ast_file(self.old_ast_path) if os.path.exists(self.old_ast_path) else None
            new_ast_root = load_ast_file(self.new_ast_path) if os.path.exists(self.new_ast_path) else None
        except Exception as e:
            # print(f"Warning: Failed to load AST files for {self.diff_file_path}: {e}")
            return self._build_from_changes_only(changes)

        if not old_ast_root and not new_ast_root:
            # print(f"Warning: No AST files available for {self.diff_file_path}")
            return self._build_from_changes_only(changes)

        #Step 3: Find the root node of the change in the old and new version ASTs
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

        #Step 4: Build the change type mapping (start, end) -> change_type
        change_type_map = self._build_change_type_map(changes)

        #Step 5: Recursively build the full change tree with context
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
        Recursively build the change tree, old_node and new_node are representations of the same logical node in different versions.
        change_info_lookup: a dictionary, key is (old_start, old_end) or (new_start, new_end), value is the *core* change_info parsed by GumTree.
                            Used to look up additional information for operations like move.
        is_sub_node_of_core_change: indicates whether the current node is a child of a core change node.
                                    Special logic for core nodes is only executed when this is False (e.g., look up parent_info, call _find_moved_node_in_new_ast)."""
        if not old_node and not new_node:
            return None

        #Determine current node position
        old_start = old_node['start'] if old_node else -1
        old_end = old_node['end'] if old_node else -1
        new_start = new_node['start'] if new_node else -1
        new_end = new_node['end'] if new_node else -1

        #Determine current node change type
        change_type = default_change_type
        current_change_info = None

        # --- only for core nodes to find change_info ---
        if not is_sub_node_of_core_change and change_info_lookup:
            current_change_info = (change_info_lookup.get((old_start, old_end)) or
                                change_info_lookup.get((new_start, new_end)))
            if current_change_info:
                change_type = current_change_info['type']

                # --- only for core nodes to handle complex logic ---
                #If it's a move and new position is -1, need to find real position in new AST
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
        # --- non-core node processing ends ---

        #Create current CodeChangeNode
        node = CodeChangeNode(
            node_type=(new_node or old_node)['node_type'],
            content=(new_node or old_node)['content'],
            start_pos=new_start,
            end_pos=new_end,
            old_start=old_start,
            old_end=old_end,
            change_type=change_type
        )

        #Recursively process child nodes
        old_children = old_node.get('children', []) if old_node else []
        new_children = new_node.get('children', []) if new_node else []

        # --- child node alignment logic (Simplified) ---
        old_child_map = {(c['start'], c['end']): c for c in old_children}
        new_child_map = {(c['start'], c['end']): c for c in new_children}

        for new_child_key, new_child_node in new_child_map.items():
            old_child_node = old_child_map.get(new_child_key)
            if old_child_node:
                #Recursively process child nodes, marked as child nodes
                child_change_node = self._build_full_tree_recursive(old_child_node, new_child_node, change_type_map, change_type, change_info_lookup, is_sub_node_of_core_change=True)
                if child_change_node:
                    node.add_child(child_change_node)
                del old_child_map[new_child_key]

        for old_child_node in old_child_map.values():
            #Recursively process child nodes, marked as child nodes
            child_change_node = self._build_full_tree_recursive(old_child_node, None, change_type_map, change_type, change_info_lookup, is_sub_node_of_core_change=True)
            if child_change_node:
                node.add_child(child_change_node)

        for new_child_key, new_child_node in new_child_map.items():
            old_corresponding = None
            #Recursively process child nodes, marked as child nodes
            child_change_node = self._build_full_tree_recursive(old_corresponding, new_child_node, change_type_map, change_type, change_info_lookup, is_sub_node_of_core_change=True)
            if child_change_node:
                node.add_child(child_change_node)

        return node

def parse_range(range_str):
    """
    Parse range string
    """
    if pd.isna(range_str) or range_str is None or str(range_str).strip() == "":
        return None, None
    
    range_str = str(range_str).strip()
    if not (range_str.startswith('[') and range_str.endswith(']')):
        return None, None
    
    # Extract middle part
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
    Check if change data overlaps with marked range
    """
    # Check if new version position overlaps
    change_new_start = change_data['start_pos']
    change_new_end = change_data['end_pos']
    
    new_overlap = not (change_new_start > labeled_new_end or change_new_end < labeled_new_start)
    
    # Check if old version position overlaps
    change_old_start = change_data['old_start']
    change_old_end = change_data['old_end']
    
    old_overlap = not (change_old_start > labeled_old_end or change_old_end < labeled_old_start)
    
    return new_overlap and old_overlap

def ranges_overlap(start1, end1, start2, end2):
    """ Determine if two [start, end] ranges overlap, [-1,-1] is considered invalid"""
    if start1 == -1 and end1 == -1:
        return False
    return not (end1 < start2 or start1 > end2)


def load_and_label_changes(xlsx_file_path: str):
    """
    Read xlsx file and mark extracted changes.
    - Group by homework_id first to speed up matching
    - Require student_id, homework_id, file_name to be exactly the same
    - Mark as True if either old or new range overlaps"""
    # Read all worksheets from xlsx file
    excel_file = pd.ExcelFile(xlsx_file_path)
    
    # Build annotation mapping grouped by homework_id
    # label_by_hw[hw_id] = {(student_id, file_name): [(old_start, old_end, new_start, new_end), ...]}
    label_by_hw = defaultdict(lambda: defaultdict(list))
    
    # Traverse all worksheets
    for sheet_name in excel_file.sheet_names:
        if sheet_name in excel_name:
            # Find the corresponding homework_id
            try:
                idx = excel_name.index(sheet_name)
                homework_id = str(homework_ids[idx])
            except ValueError:
                continue  # Skip irrelevant worksheets
            
            #Read current worksheet
            df_sheet = pd.read_excel(xlsx_file_path, sheet_name=sheet_name)
            
            for _, row in df_sheet.iterrows():
                student_id = str(row['student_id'])
                file_name = str(row['file_name']) 
                old_range = row['old']
                new_range = row['new']
                
                #Parse [start, end] format
                try:
                    old_start, old_end = parse_range(old_range)
                    new_start, new_end = parse_range(new_range)
                except:
                    continue  #Skip lines with format errors
                
                #Store in a dictionary grouped by homework_id
                key = (student_id, file_name)
                label_by_hw[homework_id][key].append((old_start, old_end, new_start, new_end))
    
    #Mark all changed data
    labeled_data = []
    true_num = 0
    for record in all_change_data:
        student_id = str(record['student_id'])
        homework_id = str(record['homework_id'])
        file_path = record['file_path']
        
        #Extract pure filename from full path (remove directory and .txt)
        extracted_file_name = os.path.basename(file_path)
        if extracted_file_name.endswith('.txt'):
            extracted_file_name = extracted_file_name[:-4]
        
        #Build matching key
        match_key = (student_id, extracted_file_name)
        
        #Search only under current homework_id
        is_labeled = False
        if homework_id in label_by_hw and match_key in label_by_hw[homework_id]:
            change_data = record['change_data']
            for child in change_data.get('children', []):
                child_old_start = child['old_start']
                child_old_end = child['old_end']
                child_new_start = child['start_pos']
                child_new_end = child['end_pos']

                #Judge child node validity
                old_valid = not (child_old_start == -1 and child_old_end == -1)
                new_valid = not (child_new_start == -1 and child_new_end == -1)

                #Compare with all marked items under current homework_id
                for old_start, old_end, new_start, new_end in label_by_hw[homework_id][match_key]:
                    #Old version overlap check (if valid)
                    old_match = (not old_valid) or ranges_overlap(child_old_start, child_old_end, old_start, old_end)
                    #New version overlap check (if valid)
                    new_match = (not new_valid) or ranges_overlap(child_new_start, child_new_end, new_start, new_end)

                    if old_match or new_match:
                        is_labeled = True
                        true_num += 1
                        break  #Find an overlapping child node
                if is_labeled:
                    break  #Break out of the child node loop
        record['label'] = is_labeled
        labeled_data.append(record)
    
    print(f"{true_num} changes is labeled as true")
    return labeled_data

def process_all_data():
    """
    Traverse and process all data, process changes from old version to new version, and filter using changes from old-old to old
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
            
            #Get current job path
            current_hw_path = os.path.join(student_path, str(homework_id))

            if not os.path.exists(current_hw_path):
                continue
            
            #Store required change information
            old_to_new_changes = {} 
            old_to_old_changes = {}  
            
            #Traverse current job directory, process only change files in B directory (old→new) and A directory (old-old→old)
            for root, dirs, files in os.walk(current_hw_path):
                if os.path.basename(root) == 'B': 
                    for file in files:
                        if file.endswith('cpp.txt') or file.endswith('c.txt') or file.endswith('h.txt'):
                            continue
                        elif file.endswith('.txt'):
                            full_file_path = os.path.join(root, file)
                            #Extract changes from old→new (mainly collect this)
                            changes = extract_code_changes(full_file_path)
                            old_to_new_changes[file] = changes
                            
                elif os.path.basename(root) == 'A':  
                    for file in files:
                        if file.endswith('cpp.txt') or file.endswith('c.txt') or file.endswith('h.txt'):
                            continue
                        elif file.endswith('.txt'):
                            full_file_path = os.path.join(root, file)
                            #Extract changes from old-old→old
                            changes = extract_code_changes(full_file_path)
                            old_to_old_changes[file] = changes
            
            #Filter processing for each file
            for file_name in old_to_new_changes:
                if file_name in old_to_old_changes:
                    #Get changes from two versions
                    old_new_changes = old_to_new_changes[file_name]  
                    old_old_changes = old_to_old_changes[file_name]  

                    #Merge changes
                    merged_changes = merge_adjacent_changes(old_new_changes)

                    #Filter changes (use old-old→old change information to filter old→new changes)
                    filtered_changes = filter_changes(merged_changes, old_old_changes, 
                                                   student_id, homework_id, file_name)
                                        
                    save_filtered_changes(filtered_changes, student_id, homework_id, file_name)
                else:
                    old_new_changes = old_to_new_changes[file_name]
                    merged_changes = merge_adjacent_changes(old_new_changes)
                    save_filtered_changes(merged_changes, student_id, homework_id, file_name)


def save_to_file(filename: str = "code_changes_data.pkl"):
    """
    Save change data to pickle file
    """
    with open(filename, 'wb') as f:
        pickle.dump(all_change_data, f)
    print(f"Data saved to {filename}")

def load_from_file(filename: str = "code_changes_data.pkl"):
    """
    Load change data from pickle file
    """
    with open(filename, 'rb') as f:
        data = pickle.load(f)
    return data

def parse_args():
    parser = argparse.ArgumentParser(description="Build processed_data.pkl from existing mid_data_* and raw labels.")
    parser.add_argument("--data-root", default=str(DATA_ROOT), help="Directory containing generated transition data.")
    parser.add_argument(
        "--submission-root",
        default=os.environ.get("HIRETEST_DATA_ROOT", str(PROJECT_ROOT / "data")),
        help="Authorized student-submission directory; see README.md.",
    )
    parser.add_argument(
        "--assignment-ids",
        default=os.environ.get("HIRETEST_ASSIGNMENT_SEQUENCE"),
        required=not bool(os.environ.get("HIRETEST_ASSIGNMENT_SEQUENCE")),
        help="Comma-separated ordered assignment IDs; provide one more ID than stage names.",
    )
    parser.add_argument(
        "--stage-names",
        default=os.environ.get("HIRETEST_STAGE_NAMES", "1to2,2to3,3to4,4to5,5to6"),
        help="Comma-separated worksheet/stage names.",
    )
    parser.add_argument(
        "--transition-dirs",
        default=os.environ.get("HIRETEST_TRANSITION_DIRS"),
        required=not bool(os.environ.get("HIRETEST_TRANSITION_DIRS")),
        help="Comma-separated diff directories corresponding to the stage names.",
    )
    parser.add_argument("--raw-data", help="Manual label workbook; defaults to <data-root>/labels.xlsx.")
    parser.add_argument("--output", help="Output pickle path; defaults to <data-root>/processed_data.pkl.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    DATA_ROOT = Path(args.data_root).resolve()
    RAW_SUBMISSION_ROOT = Path(args.submission_root).expanduser().resolve()
    homework_ids = [item.strip() for item in args.assignment_ids.split(",") if item.strip()]
    stage_names = [item.strip() for item in args.stage_names.split(",") if item.strip()]
    transition_dirs = [item.strip() for item in args.transition_dirs.split(",") if item.strip()]
    excel_name = [""] + stage_names
    mid_data_path = [""] + transition_dirs
    print("Starting data processing with filtering...")
    if len(homework_ids) != len(stage_names) + 1:
        raise ValueError("--assignment-ids must contain exactly one more item than --stage-names")
    if len(transition_dirs) != len(stage_names):
        raise ValueError("--transition-dirs and --stage-names must contain the same number of items")
    if not DATA_ROOT.is_dir():
        raise FileNotFoundError(
            f"Data directory not found: {DATA_ROOT}. Obtain the authorized data package "
            "and configure it as described in README.md."
        )
    if not RAW_SUBMISSION_ROOT.is_dir():
        raise FileNotFoundError(
            f"Submission directory not found: {RAW_SUBMISSION_ROOT}. Obtain the authorized "
            "data package and configure it as described in README.md."
        )
    raw_data_path = Path(args.raw_data).expanduser().resolve() if args.raw_data else DATA_ROOT / "labels.xlsx"
    output_path = Path(args.output).expanduser().resolve() if args.output else DATA_ROOT / "processed_data.pkl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    process_all_data()
    print(f"Data processing completed. total: {len(all_change_data)}")
    load_and_label_changes(str(raw_data_path))  # Label positive samples
    save_to_file(str(output_path))
