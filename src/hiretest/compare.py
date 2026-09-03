import os
import re
import subprocess
from collections import defaultdict, Counter
import zipfile
import glob
import pandas as pd
from unrar import rarfile

# 定义根目录和结果目录

root_dir = 'compare/data'
# dst_dir = 'compare/mid_data'
dst_dir = 'compare/mid_data_1681_1682'
final_dir = 'compare/final_data_1681_1682'

# 作业编号列表（假设作业编号是已知的，并且按照顺序排列）
assignments = ['1527', '1526', '1641', '1681', '1682', '1705']


def run_gumtree_textdiff(path1, path2, output_path):
    output_dir = os.path.dirname(output_path)

    # 检查输出文件夹是否存在，如果不存在则创建它
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    new_output_path = output_path + '.txt'

    filename = os.path.basename(output_path)

    # 分割文件名和后缀
    filename_without_ext, ext = os.path.splitext(filename)
    # 构建命令行指令
    if ext == '.java':
        command = ['gumtree.bat', 'textdiff','-m','gumtree-simple-id-theta', path1, path2, '-o', new_output_path]
    elif ext == '.cpp' or ext == '.hpp':
        command = ['gumtree.bat', 'textdiff','-g', 'cpp-srcml','-m','gumtree-simple-id-theta', path1, path2,  '-o', new_output_path]
    elif ext == '.h' or ext == '.c':
        command = ['gumtree.bat','textdiff' , '-g', 'c-srcml','-m','gumtree-simple-id-theta', path1, path2, '-o', new_output_path]

    else:
        print(ext)
        print(new_output_path)
        return

    # 使用subprocess.run()执行指令

    result = subprocess.run(command, capture_output=True, text=True,shell=True)

    # 检查执行结果
    if result.returncode != 0:
        print("gumtree error")


def run_gumtree_parse(path, output_path):
    output_dir = os.path.dirname(output_path)

    # 检查输出文件夹是否存在，如果不存在则创建它
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    new_output_path = output_path + '.txt'

    filename = os.path.basename(output_path)

    # 分割文件名和后缀
    filename_without_ext, ext = os.path.splitext(filename)
    # 构建命令行指令
    if ext == '.java':
        command = ['gumtree.bat', 'parse', path, '-o', new_output_path]
    elif ext == '.cpp' or ext == '.hpp':
        command = ['gumtree.bat', 'parse','-g', 'cpp-srcml', path,  '-o', new_output_path]
    elif ext == '.h' or ext == '.c':
        command = ['gumtree.bat','parse' , '-g', 'c-srcml', path, '-o', new_output_path]

    else:
        return

    # 使用subprocess.run()执行指令

    result = subprocess.run(command, capture_output=True, text=True,shell=True)

    # 检查执行结果
    if result.returncode != 0:
        print("gumtree error")


def del_match(file_path):
    print(file_path)
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()

        # 初始化结果列表
        result = []
        # 初始化删除标志
        deleting = False
        change = False
        line_before = ''
        for line in lines:
            if line.strip() == "match":
                # 遇到 "==="
                if result and line_before == "===":
                    # 如果上一行是 "==="，开始删除
                    deleting = True
                    change = True
                    # 移除上一行
                    result.pop()
            elif line.strip() == "===" and deleting:
                result.append(line)
                deleting = False  # 退出删除状态
            elif deleting:
                # 如果处于删除状态，跳过当前行
                continue
            else:
                # 不处于删除状态，正常添加行到结果中
                result.append(line)
                # 如果当前行是 "match"，但不立即删除，只记录状态
                if line.strip() == "match":
                    print('why occur match')
                    # 确保之前的行是 "==="，这个条件已在前面处理过
                    pass
            line_before = line.strip()
            # 如果遇到新的 "===" 并且当前不在删除状态，结束删除


        # 将结果写回文件，或者你可以选择其他处理方式
        with open(file_path, 'w', encoding='utf-8') as file:
            file.writelines(result)
        if change == True:
            print(f"finish {file_path}")


def compare3code(path1,path2,path3,output_path):
    # 获取三个路径下的所有文件路径
    files1 = set()
    files2 = set()
    files3 = set()

    def collect_files(path, files_set):
        ignore_dirs = {".git",".idea", "__MACOSX","META-INF",".vscode",".settings"}  # 默认忽略的文件夹集合
        ignore_extensions = {".txt", ".class", ".json",".DS_Store",".zip",".md",".exe",".pdf"}
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            for file in files:
                _, ext = os.path.splitext(file)
                if ext.lower() not in ignore_extensions:
                    files_set.add(os.path.relpath(os.path.join(root, file), path))

    collect_files(path1, files1)
    collect_files(path2, files2)
    collect_files(path3, files3)

    # 找出三个版本中都存在的文件
    common_files = files1.intersection(files2).intersection(files3)

    for file in common_files:
        file1 = os.path.join(path1, file)
        file2 = os.path.join(path2, file)
        file3 = os.path.join(path3, file)
        outputA = os.path.join(output_path, 'A',file)
        outputB = os.path.join(output_path, 'B', file)
        run_gumtree_textdiff(file1, file2,outputA)
        run_gumtree_textdiff(file2, file3, outputB)
        ast_path1 = os.path.join(output_path, '1',file)
        ast_path2 = os.path.join(output_path, '2', file)
        ast_path3 = os.path.join(output_path, '3', file)
        run_gumtree_parse(file1, ast_path1)
        run_gumtree_parse(file2, ast_path2)
        run_gumtree_parse(file3, ast_path3)


def get_student_score(input_folder, output_excel_path):
    homework_ids = ['1527', '1526', '1641', '1681', '1682', '1705']
    students_data = {}

    # 遍历每个学生文件夹
    for student_id in os.listdir(input_folder):
        student_dir = os.path.join(input_folder, student_id)
        if not os.path.isdir(student_dir):
            continue  # 跳过非文件夹

        student_scores = {}
        for hw_id in homework_ids:
            hw_dir = os.path.join(student_dir, hw_id)
            if not os.path.isdir(hw_dir):
                student_scores[hw_id] = 0.0
                continue

                # 查找last和first文件
            last_files = glob.glob(os.path.join(hw_dir, 'last_*.txt'))
            if last_files:
                filename = os.path.basename(last_files[0])  # 取第一个last文件
            else:
                first_files = glob.glob(os.path.join(hw_dir, 'first_*.txt'))
                if first_files:
                    filename = os.path.basename(first_files[0])  # 取第一个first文件
                else:
                    student_scores[hw_id] = 0.0
                    continue

            # 使用正则表达式提取分数
            match = re.fullmatch(r'(?:last|first)_([0-9.]+)\.txt', filename, re.IGNORECASE)
            if match:
                try:
                    score = float(match.group(1))
                except ValueError:
                    score = 0.0
            else:
                score = 0.0
            student_scores[hw_id] = score

        students_data[student_id] = student_scores

    # 创建DataFrame并确保列顺序
    df = pd.DataFrame.from_dict(students_data, orient='index', columns=homework_ids)

    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_excel_path), exist_ok=True)

    # 导出到Excel
    df.to_excel(output_excel_path)


def get_student_submit_count(input_folder, output_excel_path):
    homework_ids = ['1527', '1526', '1641', '1681', '1682', '1705']
    students_data = {}

    # 遍历每个学生文件夹
    for student_id in os.listdir(input_folder):
        student_dir = os.path.join(input_folder, student_id)
        if not os.path.isdir(student_dir):
            continue  # 跳过非文件夹

        submission_counts = {}
        for hw_id in homework_ids:
            hw_dir = os.path.join(student_dir, hw_id)
            total_submissions = 0

            # 检查作业文件夹是否存在
            if os.path.exists(hw_dir) and os.path.isdir(hw_dir):
                # 遍历子作业文件夹
                for sub_hw in os.listdir(hw_dir):
                    sub_hw_path = os.path.join(hw_dir, sub_hw)
                    if os.path.isdir(sub_hw_path):
                        # 统计提交文件夹数量
                        submissions = [name for name in os.listdir(sub_hw_path)
                                       if os.path.isdir(os.path.join(sub_hw_path, name))]
                        total_submissions += len(submissions)

            submission_counts[hw_id] = total_submissions

        students_data[student_id] = submission_counts

    # 创建DataFrame并保持列顺序
    df = pd.DataFrame.from_dict(students_data, orient='index', columns=homework_ids)

    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_excel_path), exist_ok=True)

    # 导出到Excel
    df.to_excel(output_excel_path)


def get_basic_data():
    assign_num = {'1527':0, '1526':0, '1641':0, '1681':0, '1682':0, '1705':0}
    pass_num = {'1527': 0, '1526': 0, '1641': 0, '1681': 0, '1682': 0, '1705': 0}
    for student_id in os.listdir(root_dir):
        student_path = os.path.join(root_dir, student_id)
        for assignment_id in assignments:
            assignment_path = os.path.join(student_path, assignment_id)
            if os.path.exists(assignment_path):
                if assignment_id == '1682':
                    print(student_id)
                assign_num[assignment_id] += 1
                score_path1 = os.path.join(assignment_path, 'first_100.0.txt')
                score_path2 = os.path.join(assignment_path, 'last_100.0.txt')
                if os.path.isfile(score_path1) or os.path.isfile(score_path2):
                    pass_num[assignment_id] += 1
    print(f"assign_num:{assign_num}")
    print(f"pass_num:{pass_num}")

def traverse_data():
    flag = 0
    # 遍历所有学生文件夹
    for student_id in os.listdir(root_dir):
        # if student_id == "22371105":
        #     flag = 1
        #     continue
        # if flag == 0:
        #     continue
        student_path = os.path.join(root_dir, student_id)
        if os.path.isdir(student_path):
            # 遍历学生的所有作业文件夹
            path1 = '' #前一次作业最后一次提交
            path2 = '' #后一次作业第一次提交
            path3 = '' #后一次作业最后一次提交
            for assignment_id in assignments:
                assignment_path = os.path.join(student_path, assignment_id)
                if not os.path.exists(assignment_path):
                    continue
                submit_list = os.listdir(assignment_path)
                if assignment_id != '1681' and assignment_id != '1682':
                    continue
                if assignment_id == assignments[3] and (len(submit_list) == 4 or len(submit_list) == 5):
                    score_path = os.path.join(student_path, assignment_id,'last_100.0.txt')
                    if not os.path.isfile(score_path):
                        break
                    path1 = os.path.join(student_path, assignment_id,'last')
                elif assignment_id == assignments[3] and (len(submit_list) == 2 or len(submit_list) == 3):
                    score_path = os.path.join(student_path, assignment_id,'first_100.0.txt')
                    if not os.path.isfile(score_path):
                        break
                    path1 = os.path.join(student_path, assignment_id, 'first')
                elif len(submit_list) == 4 or len(submit_list) == 5:
                    if path1 != '':
                        path2 = os.path.join(student_path, assignment_id, 'first')
                        path3 = os.path.join(student_path, assignment_id, 'last')
                        output_path = os.path.join(dst_dir, student_id,assignment_id)
                        compare3code(path1,path2,path3,output_path)
            print(f"{student_id} finish")


if __name__ == "__main__":
    traverse_data() #遍历学生提交记录，生成 Diff 和 AST 文件
    # get_basic_data() #统计各作业的“总提交人数”与“满分通过人数”
    # get_student_score('compare/data', 'compare/student_scores.xlsx') #提取并汇总所有学生的最终成绩到 Excel
    # get_student_submit_count('src_classification', 'compare/student_submit_count.xlsx') #统计并汇总所有学生的提交次数到 Excel