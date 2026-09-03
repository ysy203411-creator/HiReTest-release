import os
import re
import shutil

import pandas as pd

data_dir = 'compare/data'
# root_dir = 'compare/mid_data/'
root_dir = 'compare/mid_data_1681_1682_new/'
output_dir = 'compare/final_data_1681_1682_new/'
excel_file = "compare/数据分析_1681_1682_new.xlsx"
change_type = ["match", "delete-node", "delete-tree", "insert-node", "insert-tree", "update-node", "move-tree"]
declaration_name = ["VariableDeclarationFragment", "FieldDeclaration", "VariableDeclarationStatement",
                    "MethodDeclaration", "decl_stmt", "function_decl", "function", "struct", "typedef",
                    "SingleVariableDeclaration", "TypeDeclaration"]

match_pattern = r'\[(\d+),\s*(\d+)\]'
index_pattern = r'\d+'
type_pattern = r'^[^ :]+'
update_pattern = r'replace\s+(?:"([^"]*)"|(\S*))\s+by\s+(?:"([^"]*)"|(\S*))'


# 匹配match 前后版本的位置
# name: c [1117,1118]
# name: c [1157,1158]
# 更新update-node 旧版本的位置，match中存在前后的位置
# literal: "testfile.txt" [610,624]
# replace "testfile.txt" by "testfile1.txt"
# 插入insert-node，insert-tree 只标记了新版本在父节点下的相对位置,从AST树中查询新版本具体位置
# function [573,609]
# ............
# to
# unit [0,0]
# at 10
# 删除delete-node，delete-tree 旧版本的位置
# operator: != [5775,5777]
# 移动move-tree 旧版本的位置，移动后新版本的父节点下的相对位置，match中存在前后的位置
# MethodInvocation [8118,8145]
#     SimpleName: f_LineBreaks_Typenum [8118,8138]
#     METHOD_INVOCATION_ARGUMENTS [8139,8144]
#         SimpleName: value [8139,8144]
# to
# ClassInstanceCreation [8045,8093]
# at 1

class Location:

    def __init__(self, start: int, end: int):
        self.start = start
        self.end = end

    def set(self, start, end):
        self.start = start
        self.end = end

    def same(self, location):
        if self.start < 0 or location.start < 0:
            return False
        elif self.start == location.start and self.end == location.end:
            return True
        else:
            return False

    def isEmpty(self):
        if self.start == -1 and self.end == -1:
            return True
        else:
            return False

    def include(self, location):
        if self.isEmpty() or location.isEmpty():
            return False
        elif self.start <= location.start and self.end >= location.end:
            return True
        # C++的gumtree AST树有bug,最外层的范围是[0,0]
        elif self.start == self.end == 0:
            return True
        else:
            return False

    def to_string(self):
        return f"[{self.start},{self.end}]"


class Node:

    def __init__(self, name, old_location: Location = Location(-1, -1), f_name=None,
                 f_location: Location = Location(-1, -1), index=-1):
        self.location = old_location
        self.f_location = f_location
        self.index = index
        self.name = name
        self.f_name = f_name

    def to_string(self):
        return f"name:{self.name} old:{self.location.to_string()}  f_location:{self.f_location.to_string()} index:{self.index}"

    def search_location(self, f_location, index):
        if self.index == index and self.f_location.same(f_location):
            return self.location
        else:
            return None


class ChangeNode(Node):

    def __init__(self, name, type, old_location: Location = Location(-1, -1), new_location: Location = Location(-1, -1),
                 f_name=None, f_location: Location = Location(-1, -1), index=-1,old_value="",new_value=""):
        super().__init__(name, old_location, f_name, f_location, index)
        self.bro_location2 = Location(-1, -1)
        self.bro_location1 = Location(-1, -1)
        self.type = type
        self.new_location = new_location
        self.old_value = old_value
        self.new_value = new_value
        self.line1 = -1
        self.line2 = -1
        self.line_num = -1

    def to_string(self):
        if self.line2 == -1:
            return f"line{self.line1} type:{self.type} name:{self.name} old:{self.location.to_string()} new:{self.new_location.to_string()} " \
                   f"f_location:{self.f_location.to_string()} index:{self.index}"
        else:
            return f"line{self.line1}-{self.line2} type:{self.type} name:{self.name} old:{self.location.to_string()} new:{self.new_location.to_string()} " \
                   f"f_location:{self.f_location.to_string()} index:{self.index}"

    def set_brothers(self, location: Location):
        if self.bro_location1.isEmpty():
            self.bro_location1 = location
        elif self.bro_location2.isEmpty():
            self.bro_location2 = location
        else:
            print("error for too many brothers")

    # def addLocation(self, node):
    #     if node.new_location.include(self.bro_location1):
    #         if self.new_location.include(node.bro_location1):
    #             self.bro_location1 = node.bro_location2
    #         elif self.new_location.include(node.bro_location2):
    #             self.bro_location1 = node.bro_location1
    #         else:
    #             print(f"error for brother location fault {self.to_string()}")
    #             return
    #     elif node.new_location.include(self.bro_location2):
    #         if self.new_location.include(node.bro_location1):
    #             self.bro_location2 = node.bro_location2
    #         elif self.new_location.include(node.bro_location2):
    #             self.bro_location2 = node.bro_location1
    #         else:
    #             print(f"error for brother location fault {self.to_string()}")
    #             return
    #     else:
    #         print("error for add locaton")
    #     if self.new_location.end <= node.new_location.start:
    #         self.new_location.set(self.new_location.start, node.new_location.end)
    #         self.name = f"{self.name} + {node.name}"
    #     else:
    #         self.new_location.set(node.new_location.start, self.new_location.end)
    #         self.name = f"{node.name} + {self.name}"

    def addLocation(self, node):
        # 判断是否互为兄弟节点
        is_sibling = (
                (not self.bro_location1.isEmpty() and self.bro_location1.include(node.new_location)) or
                (not self.bro_location2.isEmpty() and self.bro_location2.include(node.new_location)) or
                (not node.bro_location1.isEmpty() and node.bro_location1.include(self.new_location)) or
                (not node.bro_location2.isEmpty() and node.bro_location2.include(self.new_location))
        )

        if not is_sibling:
            print(f"error for brother location fault {self.to_string()}")
            return

        # 合并节点
        # 确定哪个节点的索引位置靠前
        if self.new_location.start < node.new_location.start:
            first_node = self
            second_node = node
        else:
            first_node = node
            second_node = self

        # 更新节点名称
        new_name = f"{first_node.name}+{second_node.name}"

        # 更新节点自身的位置
        new_location = Location(min(first_node.new_location.start, second_node.new_location.start),
                                max(first_node.new_location.end, second_node.new_location.end))

        # 更新兄弟节点位置
        # 如果 first_node 的 bro_location1 或 bro_location2 是 second_node 的位置，则将其更新为新的位置
        if not first_node.bro_location1.isEmpty() and (first_node.bro_location1.include(second_node.new_location) or
        second_node.new_location.include(first_node.bro_location1)):
            first_node.bro_location1 = new_location
        elif not first_node.bro_location2.isEmpty() and (first_node.bro_location2.include(second_node.new_location) or
            second_node.new_location.include(first_node.bro_location2)):
            first_node.bro_location2 = new_location

        # 如果 second_node 的 bro_location1 或 bro_location2 是 first_node 的位置，则将其更新为新的位置
        if not second_node.bro_location1.isEmpty() and (second_node.bro_location1.include(first_node.new_location) or
        first_node.new_location.include(second_node.bro_location1)):
            second_node.bro_location1 = new_location
        elif not second_node.bro_location2.isEmpty() and (second_node.bro_location2.include(first_node.new_location) or
        first_node.new_location.include(second_node.bro_location2)):
            second_node.bro_location2 = new_location

        # 更新 self 的属性
        self.name = new_name
        self.new_location = new_location
        self.bro_location1 = first_node.bro_location1
        self.bro_location2 = first_node.bro_location2

    def setLine(self, num1, num2=-1):
        self.line1 = num1
        self.line2 = num2
        if num2 != -1:
            self.line_num = self.line2 - self.line1 + 1
        else:
            self.line_num = 1

    def getLineNum(self):
        return self.line_num

    def merge_lines(self, node):
        # 处理 self 或 node 只占一行的情况
        self_end = self.line1 if self.line2 == -1 else self.line2
        node_end = node.line1 if node.line2 == -1 else node.line2

        # 检查是否有重叠或相邻
        if not (self_end < node.line1 - 1 or node_end < self.line1 - 1):
            # 合并行范围
            new_line1 = min(self.line1, node.line1)
            new_line2 = max(self_end, node_end)
            if new_line2 == new_line1:
                new_line2 = -1

            if node.line1 <= self.line1 <= self_end <= node_end:
                self.name = node.name
            elif node.line1 < self.line1:
                self.name = f"{node.name} + {self.name}"
            elif self.line1 < node.line1:
                self.name = f"{self.name} + {node.name}"
            # 更新 self 的行范围
            self.setLine(new_line1,new_line2)
            if self.type == "delete-tree" or self.type == "delete-node":
                self.location.set(min(self.location.start, node.location.start),
                                  max(self.location.end, node.location.end))
            else:
                self.new_location.set(min(self.new_location.start, node.new_location.start),
                                      max(self.new_location.end, node.new_location.end))

            return True
        else:
            return False


def getCommand(file,path1,path2):
    filename_, ext = os.path.splitext(file)
    command = ""
    if ext == '.java':
        command = "gumtree swingdiff -m gumtree-simple-id " + path1 + " " + path2
    elif ext == '.cpp' or ext == '.hpp':
        command = "gumtree swingdiff -m gumtree-simple-id -g cpp-srcml " + path1 + " " + path2
    elif ext == '.h' or ext == '.c':
        command = "gumtree swingdiff -m gumtree-simple-id -g c-srcml " + path1 + " " + path2
        #-theta
    return command


def mat_pattern(line):
    match = re.search(match_pattern, line)
    if match:
        # 提取捕获组中的数字
        num1 = int(match.group(1))
        num2 = int(match.group(2))
        return Location(num1, num2)
    else:
        # print(f"match pattern error:{line}")
        return None


def ind_pattern(line):
    match = re.search(index_pattern, line)
    if match:
        # 提取捕获组中的数字
        num = int(match.group())
        return num
    else:
        print("index pattern error")
        return -1


def na_pattern(line):
    match = re.search(type_pattern, line)
    if match:
        # 提取捕获组中的数字
        s = str(match.group())
        return s
    else:
        print("name pattern error")
        return None


def upd_pattern(line):
    # 使用正则表达式匹配
    match = re.match(update_pattern, line)

    if not match:
        # print(f"update pattern error {line}")
        return "",""

    old = match.group(1) if match.group(1) is not None else match.group(2)
    new = match.group(3) if match.group(3) is not None else match.group(4)

    old = old if old is not None else ""
    new = new if new is not None else ""

    return old, new


def search_match(matchs, location):
    for node in matchs:
        if location.same(node.location):
            return node.new_location
    print(f"search matchs error:{location.to_string()}")
    return None


def get_tree_node(location, tree):
    f_name = None
    f_location = Location(-1, -1)
    node_index = -1
    for node in tree:
        if node.location.same(location):
            f_location = node.f_location
            node_index = node.index
            f_name = node.f_name
            break
    if node_index == -1:
        print("can not find node in AST tree")
    return f_name, f_location, node_index


def analyse_txt(diff_path, AST_path):
    if not os.path.isfile(diff_path):
        return None, None
    tree = get_tree(AST_path)
    with open(diff_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()
        results = []
        matchs = []
        flag = False  # 判断分割线
        type = ""
        index = 0
        while index < len(lines):
            line = lines[index].strip()
            if line != "===" and not flag and type in change_type:
                name = na_pattern(line)
                if name == "comment":
                    while index < len(lines) and lines[index].strip() != "===":
                        index += 1
                    continue
            if line == "===":
                flag = True
                type = ""
            elif flag and line in change_type:
                type = line
            elif not flag and type == "match":
                name = na_pattern(line)
                next_line = lines[index + 1].strip()
                index += 1
                old_location = mat_pattern(line)
                new_location = mat_pattern(next_line)
                matchs.append(ChangeNode(name, type, old_location, new_location))
            elif not flag and type == "delete-node":
                name = na_pattern(line)
                old_location = mat_pattern(line)
                results.append(ChangeNode(name, type, old_location))
            elif not flag and type == "delete-tree":
                name = na_pattern(line)
                old_location = mat_pattern(line)
                results.append(ChangeNode(name, type, old_location))
                next_line = ""
                while index + 1 < len(lines) and next_line != "===":
                    next_line = lines[index + 1].strip()
                    index += 1
                if next_line == "===":
                    index -= 1
            elif not flag and type == "update-node":
                name = na_pattern(line)
                old_value, new_value = upd_pattern(lines[index+1])
                old_location = mat_pattern(line)
                new_location = search_match(matchs, old_location)
                f_name, f_location, node_index = get_tree_node(new_location, tree)
                results.append(ChangeNode(name, type, old_location, new_location, f_name, f_location, node_index,old_value,new_value))
                index += 1
            elif not flag and type == "move-tree":
                name = na_pattern(line)
                old_location = mat_pattern(line)
                new_location = search_match(matchs, old_location)
                next_line = ""
                while index + 1 < len(lines) and next_line != "to":
                    next_line = lines[index + 1].strip()
                    index += 1
                index += 2
                f_name, f_location, node_index = get_tree_node(new_location, tree)
                results.append(ChangeNode(name, type, old_location, new_location, f_name, f_location, node_index))
            elif not flag and type == "insert-node":
                name = na_pattern(line)
                location = mat_pattern(line)
                index += 3
                f_name, f_location, node_index = get_tree_node(location, tree)
                results.append(ChangeNode(name, type, Location(-1, -1), location, f_name, f_location, node_index))
            elif not flag and type == "insert-tree":
                name = na_pattern(line)
                location = mat_pattern(line)
                next_line = ""
                while index + 1 < len(lines) and next_line != "to":
                    next_line = lines[index + 1].strip()
                    index += 1
                index += 2
                f_name, f_location, node_index = get_tree_node(location, tree)
                results.append(ChangeNode(name, type, Location(-1, -1), location, f_name, f_location, node_index))
            elif flag and line == "---":
                flag = False
            elif flag:
                print(f"error for type:{line} when flag is true")
            elif not flag:
                print(f"error! there is no analyse for {type}")
            index += 1
        for node in results:
            if node.index == 0:
                for tree_node in tree:
                    if tree_node.f_location.same(node.f_location) and tree_node.index == 1:
                        node.set_brothers(tree_node.location)
                        break
            elif node.index > 0:
                n = 0
                for tree_node in tree:
                    if tree_node.f_location.same(node.f_location) and node.index - 1 == tree_node.index:
                        node.set_brothers(tree_node.location)
                        n += 1
                    elif tree_node.f_location.same(node.f_location) and node.index + 1 == tree_node.index:
                        node.set_brothers(tree_node.location)
                        n += 1
                    if n == 2:
                        break
        # fo = open("compare/result.txt", "w")
        # for node in results:
        #     if node.location is None or node.new_location is None:
        #         print("None location")
        #     fo.write(f"{node.to_string()}\n")
        return results, matchs


def get_tree(path):
    with open(path, 'r', encoding='utf-8') as file:
        lines = file.readlines()
        tree = []
        node_locations = []
        node_nums = []
        f_names = []
        index = 0
        while index < len(lines):
            raw_line = lines[index]
            stripped_line = raw_line.lstrip()
            # 计算原字符串和移除了空白的字符串的长度差
            indent_whitespace = raw_line[:len(raw_line) - len(stripped_line)]
            level = indent_whitespace.count('    ')  # 缩进级别
            line = raw_line.strip()
            name = na_pattern(line)
            if name == "comment" or '/' in name or '*' in name:
                while index < len(lines) and mat_pattern(lines[index]) is None:
                    index += 1
                index += 1
                continue
            location = mat_pattern(line)
            name = na_pattern(line)
            while len(node_locations) > level:
                node_locations.pop()
                node_nums.pop()
                f_names.pop()
            node_locations.append(location)
            node_nums.append(0)
            f_names.append(name)
            if len(node_locations) > 1:
                tree.append(Node(name, location, f_names[level - 1], node_locations[level - 1], node_nums[level - 1]))
                node_nums[level - 1] += 1
            else:
                tree.append(Node(name, location, None, Location(-1, -1), -1))
            index += 1
        return tree


def extract_filename_add_id(file_path, id):
    """
    提取文件路径中的文件名，并在文件名后添加编号。

    :param file_path: 源文件路径
    :return: 新的文件名（不包括路径）
    """
    # 使用os.path.basename获取文件名
    filename = os.path.basename(file_path)

    # 分割文件名和扩展名
    name, ext = os.path.splitext(filename)

    # 重新组合文件名和扩展名
    new_filename = f"{name}{id}{ext}"
    if name == "Com":
        new_filename = f"{name}({id}){ext}"

    return new_filename


def move_and_rename_file(source_path, file_id, destination_folder):
    """
    将文件从源路径复制到目标文件夹，并使用extract_filename_add_one函数重命名文件。

    :param source_path: 源文件路径
    :param destination_folder: 目标文件夹路径
    """
    # 确保目标文件夹存在
    os.makedirs(destination_folder, exist_ok=True)

    # 提取新的文件名
    dir = os.path.dirname(source_path)
    name, ext = os.path.splitext(os.path.basename(source_path))
    source = os.path.join(dir, name)
    new_filename = extract_filename_add_id(source, file_id)

    # 构建新的完整目标路径
    destination_path = os.path.join(destination_folder, new_filename)

    # 使用shutil.copy2复制并重命名文件
    shutil.copy2(source, destination_path)
    return destination_path


def get_old_location(match_tree, location):
    for node in match_tree:
        if node.new_location.same(location):
            return node.location
    return None


def search_tree(tree, location):
    for node in tree:
        if node.location.same(location):
            return node
        else:
            return None


def sort_nodes(node_list):
    """
    对 Node 列表进行排序。
    排序规则：
    1. 按照 new_location.start 从小到大排序。
    2. 如果 new_location.start 相同，则按照 new_location.end 从大到小排序。
    """
    # 使用 sorted 函数和自定义的排序键
    sorted_list = sorted(
        node_list,
        key=lambda node: (node.new_location.start, -node.new_location.end)
    )
    return sorted_list

def search_bros(tree, old_tree, match, node):
    num = 0
    bro1 = search_tree(tree, node.bro_location1)
    loc = node.bro_location1
    while bro1 is not None:
        if bro1.bro_location1.same(loc):
            loc = bro1.bro_location2
        elif bro1.bro_location2.same(loc):
            loc = bro1.bro_location1
        else:
            print("search tree return error")
        bro1 = search_tree(tree, loc)
    if loc.isEmpty:
        return False
    else:
        old_bro1_loc = get_old_location(match, loc)
        if old_bro1_loc is not None:
            for old_node in old_tree:
                if old_node.new_location.include(old_bro1_loc):
                    if old_node.type != "move_tree" and old_node.type != "update-node":
                        num += 1
                    break
    bro2 = search_tree(tree, node.bro_location2)
    loc = node.bro_location2
    while bro2 is not None:
        if bro2.bro_location1.same(loc):
            loc = bro2.bro_location2
        elif bro2.bro_location2.same(loc):
            loc = bro2.bro_location1
        else:
            print("search tree return error")
        bro2 = search_tree(tree, loc)
    if loc.isEmpty:
        return False
    else:
        old_bro2_loc = get_old_location(match, loc)
        if old_bro2_loc is not None:
            for old_node in old_tree:
                if old_node.new_location.include(old_bro2_loc):
                    if old_node.type != "move_tree" and old_node.type != "update-node":
                        num += 1
                    break
    if num == 2:
        return True
    else:
        return False


def get_lines_index(file_path, location):
    num1 = location.start
    num2 = location.end
    start_line = -1
    end_line = -1
    current_index = 0
    line_num = 0

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
        lines = file.readlines()
        modified_lines = [lines[0]] + [' ' + line for line in lines[1:]]
        for line in modified_lines:
            line_length = len(line)
            if num1 >= current_index and num1 < current_index + line_length:
                if start_line == -1:
                    start_line = line_num + 1
            if num2 >= current_index and num2 <= current_index + line_length:
                end_line = line_num + 1
            current_index += line_length + 1
            line_num += 1

    if start_line == -1 or end_line == -1:
        return -1, -1  # 如果没有找到匹配的索引范围，则返回-1, -1

    if start_line == end_line:
        end_line = -1  # 如果索引范围只涉及一行，则将结束行设置为-1

    return start_line, end_line

def merge_intervals(intervals):
    """
    合并重叠或包含的区间
    :param intervals: 区间列表，每个区间是一个 [start, end] 的列表
    :return: 合并后的区间列表
    """
    # 按 start 排序
    intervals.sort(key=lambda x: x[0])

    merged = []
    current_interval = intervals[0]

    for interval in intervals[1:]:
        start, end = interval
        # 如果当前区间与下一个区间重叠或包含
        if start <= current_interval[1]:
            # 合并区间，取最大的 end
            current_interval[1] = max(current_interval[1], end)
        else:
            # 如果不重叠，将当前区间加入结果，并更新当前区间
            merged.append(current_interval)
            current_interval = interval

    # 加入最后一个区间
    merged.append(current_interval)
    return merged


def extract_substring_from_file(file_path, start, end):
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
        lines = file.readlines()
    modified_lines = [lines[0]] + [' ' + line for line in lines[1:]]
    modified_content = ''.join(modified_lines)

    # 检查索引是否在文件内容范围内
    if start < 0 or end > len(modified_content) or start > end:
        print(f"提供的索引范围无效,{start},{end},{len(modified_content)}")
        end = len(modified_content)
        if start < 0:
            start = 0

    # 提取子字符串
    substring = modified_content[start:end]
    return substring


def calculate_total_coverage(nodes):
    """
    计算所有节点覆盖的总长度
    :param nodes: 节点列表，每个节点是一个字典，包含 location（location 是一个字典，包含 start 和 end）
    :return: 覆盖的总长度
    """
    # 提取所有区间
    intervals = []
    for node in nodes:
        if not node.new_location.isEmpty():
            intervals.append([node.new_location.start,node.new_location.end])

    if len(intervals) == 0:
        return 0
    # 合并重叠或包含的区间
    merged_intervals = merge_intervals(intervals)

    # 计算总长度
    total_length = 0
    for interval in merged_intervals:
        total_length += interval[1] - interval[0] + 1  # 包含两端点

    return total_length


def compare_tree(student_id, assignment_id, output_id, file_path):
    basename = os.path.splitext(file_path)[0]
    raw_file_path1 = os.path.join('compare/data', student_id, assignment_id, "first", basename)
    raw_file_path2 = os.path.join('compare/data', student_id, assignment_id, "last", basename)
    with open(raw_file_path1, 'r', encoding='utf-8', errors='ignore') as file1:
        content1 = file1.read()
        length1 = len(content1)
    with open(raw_file_path2, 'r', encoding='utf-8', errors='ignore') as file2:
        content2 = file2.read()
        length2 = len(content2)
    if length1 > length2 * 3 or length2 > length1 * 3:
        return None
    file_path1 = os.path.join(root_dir, student_id, assignment_id, "A", file_path)
    AST_path1 = os.path.join(root_dir, student_id, assignment_id, "2", file_path)
    file_path2 = os.path.join(root_dir, student_id, assignment_id, "B", file_path)
    AST_path2 = os.path.join(root_dir, student_id, assignment_id, "3", file_path)
    result1, match1 = analyse_txt(file_path1, AST_path1)
    result2, match2 = analyse_txt(file_path2, AST_path2)
    mid_data = []
    output = []
    if result1 is None or result2 is None or len(result2) == 0:
        return None
    if calculate_total_coverage(result2) / length2 >= 0.6:
        return None
    num = {'start': len(result2), 'mid': 0, 'mid_1': 0, 'end': 0}
    index = 0
    while index < len(result2):
        flag = False
        node = result2[index]
        if node.type == "delete-tree" or node.type == "delete-node":  # 同类合并
            for node1 in result2:
                if (node1.type == "delete-tree" or node1.type == "delete-node") and \
                        (not node.location.same(node1.location)) and node1.location.include(node.location):
                    flag = True
                    break
        elif node.type == "insert-tree" or node.type == "insert-node":
            for node1 in result2:
                if (node1.type == "insert-tree" or node1.type == "insert-node") and \
                        (not node.new_location.same(node1.new_location)) and node1.new_location.include(
                    node.new_location):
                    flag = True
                    break
        elif node.type == "move-tree":
            for node1 in result2:
                if (node1.type == "insert-tree" or node1.type == "insert-node" or node1.type == "move-tree") and \
                        (not node.new_location.same(node1.new_location)) and node1.new_location.include(
                    node.new_location):
                    flag = True
                    break
        elif node.type == "update-node":
            for node1 in result2:
                if (node1.type == "insert-tree" or node1.type == "insert-node" or node1.type == "move-tree") \
                        and node1.new_location.include(node.new_location):
                    flag = True
                    break
        if flag is False:
            mid_data.append(node)

        index += 1
    index = 0
    while index < len(mid_data):
        node = mid_data[index]
        flag = False
        if node.type == "update-node":
            if node.name == "SimpleName" and (
                    node.f_name in declaration_name or node.f_name == "SingleVariableDeclaration"):
                flag = True
            elif node.name == "name" and (node.f_name == "function" or node.f_name == "decl"):
                flag = True
            else:
                for old_node in result1:
                    if old_node.new_location.include(node.location):
                        if old_node.type != "move_tree" and old_node.type != "update-node":
                            flag = True
                        break
        elif node.type == "delete-tree" or node.type == "delete-node":
            if node.name in declaration_name or node.name == "ImportDeclaration" or node.name == "include" \
                    or node.f_name == "decl_stmt":
                flag = True
            else:
                for old_node in result1:
                    if old_node.new_location.include(node.location):
                        if old_node.type != "move_tree" and old_node.type != "update-node":
                            flag = True
                        break
        elif node.type == "insert-tree" or node.type == "insert-node":
            if node.name in declaration_name or node.name == "ImportDeclaration" or node.name == "include" \
                    or node.f_name == "decl_stmt":
                flag = True
            else:
                if match2 and match2 != []:
                    # 父节点是A中新增的节点
                    old_f_loc = get_old_location(match2, node.f_location)
                    if old_f_loc is not None:
                        for old_node in result1:
                            if old_node.new_location.include(old_f_loc):
                                if old_node.type != "move_tree" and old_node.type != "update-node":
                                    flag = True
                                    break
                    # #被两个A中新增的兄弟节点包围：
                    # if flag is False and not node.bro_location1.isEmpty and not node.bro_location2.isEmpty:
                    #     flag = search_bros(mid_data, result1, match2, node)
        elif node.type == "move-tree":
            if node.name == "MethodDeclaration" or node.name == "ImportDeclaration" or node.name == "include" \
                    or node.name == "function_decl" or node.name == "function" or node.name == "using" or node.name == "constructor":
                flag = True
            else:
                for old_node in result1:
                    if old_node.new_location.include(node.location):
                        if old_node.type != "move_tree" and old_node.type != "update-node":
                            flag = True
                            break
                if flag is False:
                    old_f_loc = get_old_location(match2, node.f_location)
                    if old_f_loc is not None:
                        for old_node in result1:
                            if old_node.new_location.include(old_f_loc):
                                if old_node.type != "move_tree" and old_node.type != "update-node":
                                    flag = True
                                    break
                    # if flag is False and not node.bro_location1.isEmpty and not node.bro_location2.isEmpty:
                    # flag = search_bros(mid_data, result1, match2, node)
        else:
            print(node.type)
        if flag is False:
            output.append(node)
        index += 1
    num['mid'] = len(output)
    index = 0
    # 删除重复项
    while index < len(output):
        node = output[index]
        i = index + 1
        while i < len(output):
            node1 = output[i]
            if node.location.same(node1.location) and node.new_location.same(node1.new_location):
                output.remove(node1)
            else:
                i += 1
        index += 1
    output = sort_nodes(output)
    # 合并相邻项
    index = 0
    while index < len(output):
        node = output[index]
        if node.type == "delete-tree" or node.type == "delete-node":
            index += 1
            continue
        elif node.bro_location1.isEmpty() and node.bro_location2.isEmpty():
            index += 1
            continue
        i = index + 1
        while i < len(output):
            node1 = output[i]
            if node1.type == "delete-tree" or node1.type == "delete-node":
                i += 1
                continue
            if node.f_location.same(node1.f_location) and node.bro_location1.include(node1.new_location) and node1.new_location.include(node.bro_location1):
                node.addLocation(node1)
                output.remove(node1)
            elif node.f_location.same(node1.f_location) and node.bro_location2.include(node1.new_location) and node1.new_location.include(node.bro_location2):
                node.addLocation(node1)
                output.remove(node1)
            else:
                i += 1
        index += 1
    num['mid_1'] = len(output)
    # 标注所在行
    for node in output:
        if node.new_location.isEmpty():
            num1, num2 = get_lines_index(raw_file_path1, node.location)
            node.old_value = extract_substring_from_file(raw_file_path1,node.location.start,node.location.end)
        else:
            num1, num2 = get_lines_index(raw_file_path2, node.new_location)
            if node.type == "insert-tree" or node.type == "insert-node":
                node.new_value = extract_substring_from_file(raw_file_path2,node.new_location.start,node.new_location.end)
        node.setLine(num1, num2)
    index = 0
    while index < len(output):
        node = output[index]
        if node.type == "update-node":
            i = index + 1
            while i < len(output):
                node1 = output[i]
                if node1.type == "update-node" and not(node.new_value == "" and node.old_value == "") \
                        and node.old_value == node1.old_value and node.new_value == node1.new_value:
                    node.line_num += node1.line_num
                    output.remove(node1)
                else:
                    i += 1
        elif node.type == "insert-tree" or node.type == "insert-node":
            i = index + 1
            while i < len(output):
                node1 = output[i]
                if node1.type == "insert-tree" or node1.type == "insert-node" and node.new_value == node1.new_value:
                    node.line_num += node1.line_num
                    output.remove(node1)
                else:
                    i += 1
        elif node.type == "delete-tree" or node.type == "delete-node":
            i = index + 1
            while i < len(output):
                node1 = output[i]
                if node1.type == "delete-tree" or node1.type == "delete-node" and node.old_value == node1.old_value:
                    node.line_num += node1.line_num
                    output.remove(node1)
                else:
                    i += 1
        index += 1
    # 合并重叠和相邻
    index = 0
    while index < len(output):
        node = output[index]
        i = index + 1
        while i < len(output):
            node1 = output[i]
            if node.type == "delete-tree" or node.type == "delete-node":
                if node1.type != "delete-tree" and node1.type != "delete-node":
                    i += 1
                    continue
            elif node1.type == "delete-tree" or node1.type == "delete-node":
                i += 1
                continue
            f = node.merge_lines(node1)
            if f:
                output.remove(node1)
            else:
                i += 1
        index += 1

    num['end'] = len(output)
    if len(output) == 0:
        return num
    # output_path = os.path.join(output_dir,student_id, assignment_id,"output", str(output_id), os.path.basename(file_path))
    output_path = os.path.join(output_dir, student_id, str(output_id), os.path.basename(file_path))
    dir = os.path.dirname(output_path)

    # 检查输出文件夹是否存在，如果不存在则创建它
    if os.path.exists(dir):
        shutil.rmtree(dir)
    os.makedirs(dir)
    dst_path1 = move_and_rename_file(os.path.join(data_dir, student_id, assignment_id, "first", file_path), 1, dir)
    dst_path2 = move_and_rename_file(os.path.join(data_dir, student_id, assignment_id, "last", file_path), 2, dir)
    fo = open(output_path, "w")
    for node in output:
        if node.location.isEmpty() and node.new_location.isEmpty():
            print(f"{output_path} has node None location")
        fo.write(f"{node.to_string()}\n")
    #写入excel
    if os.path.exists(excel_file):
        # 如果存在，读取现有内容
        df = pd.read_excel(excel_file)
    else:
        # 如果不存在，创建一个空的 DataFrame
        df = pd.DataFrame(columns=["student_id", "file_name", "change_id", "line_num","command","当次作业/过去作业",
                                   "修改描述","修改类型","重构类型","错误类型","错误子类型"])
    file_name,ext = os.path.splitext(os.path.basename(file_path))
    new_rows = []
    for index, node in enumerate(output, start=1):
        new_row = {
            "student_id": student_id,
            "file_name": file_name,
            "change_id": index,
            "line_num": node.getLineNum(),
            "command": getCommand(file_name,os.path.basename(dst_path1),os.path.basename(dst_path2)),
            "当次作业/过去作业": None,
            "修改描述": None,
            "修改类型": None,
            "重构类型": None,
            "错误类型": None,
            "错误子类型": None,
        }
        new_rows.append(new_row)
    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    df.to_excel(excel_file, index=False)
    return num


def collect_files(path, files_set):
    for root, dirs, files in os.walk(path):
        for file in files:
            files_set.add(os.path.relpath(os.path.join(root, file), path))

#从 GumTree 生成的文本级 Diff 报告中，对代码修改进行初步过滤，并将最终结果按结构化格式输出到Excel 中，便于后续人工标注或模型训练
if __name__ == "__main__":
    file_num = 0
    total_num = {'start': 0, 'mid': 0, 'mid_1': 0, 'end': 0}
    flag = 0
    for student_id in os.listdir(root_dir):
        student_path = os.path.join(root_dir, student_id)
        if not os.path.exists(student_path):
            continue
        for assignment_id in os.listdir(student_path):
            # score_path = os.path.join(data_dir, student_id, assignment_id,'last_100.0.txt')
            # if not os.path.isfile(score_path):
            #     break
            # score_path = os.path.join(data_dir, student_id, assignment_id,'first_100.0.txt')
            # if os.path.isfile(score_path):
            #     break
            assignment_path = os.path.join(student_path, assignment_id)
            files = set()
            collect_files(os.path.join(assignment_path, "A"), files)
            id = 0
            # p = os.path.join(output_dir, student_id, assignment_id, "output")
            # if os.path.exists(p):
            #     # 删除文件夹及其所有内容
            #     shutil.rmtree(p)
            for file in files:
                num = compare_tree(student_id, assignment_id, id, file)
                if num is None:
                    continue
                if num['end'] != 0:
                    id += 1
                file_num += 1
                total_num['start'] += num['start']
                total_num['mid'] += num['mid']
                total_num['mid_1'] += num['mid_1']
                total_num['end'] += num['end']
        print(f"{student_id} end")
    print(
        f"total file:{file_num},total num ———— start:{total_num['start']}, mid:{total_num['mid']},mid_1:{total_num['mid_1']}, end:{total_num['end']}")
