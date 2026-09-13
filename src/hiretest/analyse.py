import argparse
import os
import re
import shutil
from pathlib import Path

import pandas as pd

try:
    from .paths import data_workspace_root, release_root
except ImportError:  # Support direct execution from src/hiretest.
    from paths import data_workspace_root, release_root


# Runtime paths are overridden by CLI arguments in the command-line entry point.
data_dir = str(Path(os.environ.get("HIRETEST_DATA_ROOT", release_root() / "data")))
root_dir = str(data_workspace_root() / "version_diffs")
output_dir = str(data_workspace_root() / "filtered_changes")
excel_file = str(data_workspace_root() / "change_analysis.xlsx")
change_type = ["match", "delete-node", "delete-tree", "insert-node", "insert-tree", "update-node", "move-tree"]
declaration_name = ["VariableDeclarationFragment", "FieldDeclaration", "VariableDeclarationStatement",
                    "MethodDeclaration", "decl_stmt", "function_decl", "function", "struct", "typedef",
                    "SingleVariableDeclaration", "TypeDeclaration"]

match_pattern = r'\[(\d+),\s*(\d+)\]'
index_pattern = r'\d+'
type_pattern = r'^[^ :]+'
update_pattern = r'replace\s+(?:"([^"]*)"|(\S*))\s+by\s+(?:"([^"]*)"|(\S*))'


#Match positions before and after version
# name: c [1117,1118]
# name: c [1157,1158]
#Update node positions of old version, match contains positions before and after
# literal: "testfile.txt" [610,624]
# replace "testfile.txt" by "testfile1.txt"
#Insert node, insert tree only marks the relative position of new version under parent node from AST tree, query specific position of new version
# function [573,609]
# ............
# to
# unit [0,0]
# at 10
#Delete node, delete tree old version position
# operator: != [5775,5777]
#Move tree old version position, relative position under parent node of new version after moving, match contains positions before and after
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
        #C++ gumtree AST tree has bug, outermost scope is [0,0]
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
        #Determine if nodes are siblings
        is_sibling = (
                (not self.bro_location1.isEmpty() and self.bro_location1.include(node.new_location)) or
                (not self.bro_location2.isEmpty() and self.bro_location2.include(node.new_location)) or
                (not node.bro_location1.isEmpty() and node.bro_location1.include(self.new_location)) or
                (not node.bro_location2.isEmpty() and node.bro_location2.include(self.new_location))
        )

        if not is_sibling:
            print(f"error for brother location fault {self.to_string()}")
            return

        #Merge nodes
        #Determine which node's index position is earlier
        if self.new_location.start < node.new_location.start:
            first_node = self
            second_node = node
        else:
            first_node = node
            second_node = self

        #Update node name
        new_name = f"{first_node.name}+{second_node.name}"

        #Update node's own position
        new_location = Location(min(first_node.new_location.start, second_node.new_location.start),
                                max(first_node.new_location.end, second_node.new_location.end))

        #Update sibling node position
        #If first_node's bro_location1 or bro_location2 is second_node's position, update it to the new position
        if not first_node.bro_location1.isEmpty() and (first_node.bro_location1.include(second_node.new_location) or
        second_node.new_location.include(first_node.bro_location1)):
            first_node.bro_location1 = new_location
        elif not first_node.bro_location2.isEmpty() and (first_node.bro_location2.include(second_node.new_location) or
            second_node.new_location.include(first_node.bro_location2)):
            first_node.bro_location2 = new_location

        #If second_node's bro_location1 or bro_location2 is first_node's position, update it to the new position
        if not second_node.bro_location1.isEmpty() and (second_node.bro_location1.include(first_node.new_location) or
        first_node.new_location.include(second_node.bro_location1)):
            second_node.bro_location1 = new_location
        elif not second_node.bro_location2.isEmpty() and (second_node.bro_location2.include(first_node.new_location) or
        first_node.new_location.include(second_node.bro_location2)):
            second_node.bro_location2 = new_location

        #Update self's properties
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
        #Handle self or node occupying only one line
        self_end = self.line1 if self.line2 == -1 else self.line2
        node_end = node.line1 if node.line2 == -1 else node.line2

        #Check for overlaps or adjacency
        if not (self_end < node.line1 - 1 or node_end < self.line1 - 1):
            #Merge line ranges
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
            #Update self's line range
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
        #Extract numbers from captured groups
        num1 = int(match.group(1))
        num2 = int(match.group(2))
        return Location(num1, num2)
    else:
        # print(f"match pattern error:{line}")
        return None


def ind_pattern(line):
    match = re.search(index_pattern, line)
    if match:
        #Extract numbers from captured groups
        num = int(match.group())
        return num
    else:
        print("index pattern error")
        return -1


def na_pattern(line):
    match = re.search(type_pattern, line)
    if match:
        #Extract numbers from captured groups
        s = str(match.group())
        return s
    else:
        print("name pattern error")
        return None


def upd_pattern(line):
    #Use regular expression matching
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
        flag = False  #Determine the split line
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
            #Calculate the length difference between the original string and the string with whitespace removed
            indent_whitespace = raw_line[:len(raw_line) - len(stripped_line)]
            level = indent_whitespace.count('    ')  #Indent level
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
    Extract the filename from the file path and add a number to it.

    :param file_path: Source file path
    :return: New filename (without path)
    """
    #Use os.path.basename to get the filename
    filename = os.path.basename(file_path)

    #Split filename and extension
    name, ext = os.path.splitext(filename)

    #Recombine filename and extension
    new_filename = f"{name}{id}{ext}"
    if name == "Com":
        new_filename = f"{name}({id}){ext}"

    return new_filename


def move_and_rename_file(source_path, file_id, destination_folder):
    """
    Copy the file from the source path to the destination folder, and rename the file using the extract_filename_add_one function.

    :param source_path: Source file path
    :param destination_folder: Destination folder path
    """
    #Ensure the destination folder exists
    os.makedirs(destination_folder, exist_ok=True)

    #Extract the new filename
    dir = os.path.dirname(source_path)
    name, ext = os.path.splitext(os.path.basename(source_path))
    source = os.path.join(dir, name)
    new_filename = extract_filename_add_id(source, file_id)

    #Build the new full target path
    destination_path = os.path.join(destination_folder, new_filename)

    #Use shutil.copy2 to copy and rename the file
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
    """Sort the Node list.
Sorting rules:
1. Sort by new_location.start in ascending order.
2. If new_location.start is the same, sort by new_location.end in descending order.
"""
    #Use the sorted function with a custom sort key
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
        return -1, -1  #If no matching index range is found, return -1, -1

    if start_line == end_line:
        end_line = -1  #If the index range spans only one line, set the end line to -1

    return start_line, end_line

def merge_intervals(intervals):
    """
Merge overlapping or contained intervals
:param intervals: List of intervals, each is a [start, end] list
:return: Merged list of intervals
"""
    #Sort by start
    intervals.sort(key=lambda x: x[0])

    merged = []
    current_interval = intervals[0]

    for interval in intervals[1:]:
        start, end = interval
        #If the current interval overlaps or contains the next interval
        if start <= current_interval[1]:
            #Merge intervals, take the maximum end
            current_interval[1] = max(current_interval[1], end)
        else:
            #If not overlapping, add the current interval to the result and update the current interval
            merged.append(current_interval)
            current_interval = interval

    #Add the last interval
    merged.append(current_interval)
    return merged


def extract_substring_from_file(file_path, start, end):
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
        lines = file.readlines()
    modified_lines = [lines[0]] + [' ' + line for line in lines[1:]]
    modified_content = ''.join(modified_lines)

    #Check if the index is within the file content range
    if start < 0 or end > len(modified_content) or start > end:
        print(f"The provided index range is invalid,{start},{end},{len(modified_content)}")
        end = len(modified_content)
        if start < 0:
            start = 0

    #Extract substring
    substring = modified_content[start:end]
    return substring


def calculate_total_coverage(nodes):
    """
    Calculate the total length covered by all nodes
    :param nodes: list of nodes, each node is a dictionary containing location (location is a dictionary containing start and end)
    :return: total covered length
    """
    #Extract all intervals
    intervals = []
    for node in nodes:
        if not node.new_location.isEmpty():
            intervals.append([node.new_location.start,node.new_location.end])

    if len(intervals) == 0:
        return 0
    #Merge overlapping or contained intervals
    merged_intervals = merge_intervals(intervals)

    #Calculate total length
    total_length = 0
    for interval in merged_intervals:
        total_length += interval[1] - interval[0] + 1  #Include both endpoints

    return total_length


def compare_tree(student_id, assignment_id, output_id, file_path):
    basename = os.path.splitext(file_path)[0]
    raw_file_path1 = os.path.join(data_dir, student_id, assignment_id, "first", basename)
    raw_file_path2 = os.path.join(data_dir, student_id, assignment_id, "last", basename)
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
        if node.type == "delete-tree" or node.type == "delete-node":  #Merge similar items
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
                    #Parent node is a newly added node in A
                    old_f_loc = get_old_location(match2, node.f_location)
                    if old_f_loc is not None:
                        for old_node in result1:
                            if old_node.new_location.include(old_f_loc):
                                if old_node.type != "move_tree" and old_node.type != "update-node":
                                    flag = True
                                    break
                    # #Enclosed by two newly added sibling nodes in A:
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
    #Remove duplicates
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
    #Merge adjacent items
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
    #Mark line position
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
    #Merge overlapping and adjacent
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

    #Check if output folder exists, create it if not
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
    #Write to excel
    if os.path.exists(excel_file):
        #If exists, read existing content
        df = pd.read_excel(excel_file)
    else:
        #If not exists, create an empty DataFrame
        df = pd.DataFrame(columns=["student_id", "file_name", "change_id", "line_num","command","Current assignment/past assignment",
                                   "Modify description","Modify type","Refactor type","Error type","Error subtype"])
    file_name,ext = os.path.splitext(os.path.basename(file_path))
    new_rows = []
    for index, node in enumerate(output, start=1):
        new_row = {
            "student_id": student_id,
            "file_name": file_name,
            "change_id": index,
            "line_num": node.getLineNum(),
            "command": getCommand(file_name,os.path.basename(dst_path1),os.path.basename(dst_path2)),
            "Current assignment/past assignment": None,
            "Modify Description": None,
            "Modify Type": None,
            "Refactor Type": None,
            "Error Type": None,
            "Error Subtype": None,
        }
        new_rows.append(new_row)
    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    df.to_excel(excel_file, index=False)
    return num


def collect_files(path, files_set):
    for root, dirs, files in os.walk(path):
        for file in files:
            files_set.add(os.path.relpath(os.path.join(root, file), path))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Filter and structure GumTree changes produced by compare.py."
    )
    parser.add_argument(
        "--data-root",
        default=os.environ.get("HIRETEST_DATA_ROOT", str(release_root() / "data")),
        help="Authorized submission-data root; see README.md.",
    )
    parser.add_argument(
        "--diff-root",
        required=True,
        help="Transition directory generated by compare.py.",
    )
    parser.add_argument(
        "--output-root",
        default=str(data_workspace_root() / "filtered_changes"),
        help="Writable directory for filtered change files.",
    )
    parser.add_argument(
        "--report",
        default=str(data_workspace_root() / "change_analysis.xlsx"),
        help="Output workbook for structured changes.",
    )
    return parser.parse_args()


#Perform initial filtering of code modifications from a text-level diff report generated by GumTree, and output the final results in a structured format to Excel for subsequent manual annotation or model training
if __name__ == "__main__":
    args = parse_args()
    data_dir = str(Path(args.data_root).expanduser().resolve())
    root_dir = str(Path(args.diff_root).expanduser().resolve())
    output_dir = str(Path(args.output_root).expanduser().resolve())
    excel_file = str(Path(args.report).expanduser().resolve())
    if not Path(data_dir).is_dir():
        raise FileNotFoundError(
            f"Data directory not found: {data_dir}. Obtain the authorized data package "
            "and configure it as described in README.md."
        )
    if not Path(root_dir).is_dir():
        raise FileNotFoundError(f"Diff directory not found: {root_dir}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    Path(excel_file).parent.mkdir(parents=True, exist_ok=True)
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
            #     # Delete folder and its contents
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
