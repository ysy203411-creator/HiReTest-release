import argparse
import os
import re
import subprocess
import glob
from pathlib import Path

import pandas as pd

try:
    from .paths import data_workspace_root, release_root
except ImportError:  # Support direct execution from src/hiretest.
    from paths import data_workspace_root, release_root

# Runtime paths are configured by CLI arguments or environment variables.
root_dir = str(Path(os.environ.get("HIRETEST_DATA_ROOT", release_root() / "data")))
dst_dir = str(data_workspace_root() / "version_diffs")

# The selected adjacent assignment IDs are supplied at runtime.
assignments = []


def run_gumtree_textdiff(path1, path2, output_path):
    output_dir = os.path.dirname(output_path)

    #Check if output folder exists, create it if not
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    new_output_path = output_path + '.txt'

    filename = os.path.basename(output_path)

    #Split filename and extension
    filename_without_ext, ext = os.path.splitext(filename)
    #Build command line instruction
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

    #Execute instruction using subprocess.run()

    result = subprocess.run(command, capture_output=True, text=True,shell=True)

    #Check execution result
    if result.returncode != 0:
        print("gumtree error")


def run_gumtree_parse(path, output_path):
    output_dir = os.path.dirname(output_path)

    #Check if output folder exists, create it if not
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    new_output_path = output_path + '.txt'

    filename = os.path.basename(output_path)

    #Split filename and extension
    filename_without_ext, ext = os.path.splitext(filename)
    #Build command line instruction
    if ext == '.java':
        command = ['gumtree.bat', 'parse', path, '-o', new_output_path]
    elif ext == '.cpp' or ext == '.hpp':
        command = ['gumtree.bat', 'parse','-g', 'cpp-srcml', path,  '-o', new_output_path]
    elif ext == '.h' or ext == '.c':
        command = ['gumtree.bat','parse' , '-g', 'c-srcml', path, '-o', new_output_path]

    else:
        return

    #Execute instruction using subprocess.run()

    result = subprocess.run(command, capture_output=True, text=True,shell=True)

    #Check execution result
    if result.returncode != 0:
        print("gumtree error")


def del_match(file_path):
    print(file_path)
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()

        #Initialize result list
        result = []
        #Initialize delete flag
        deleting = False
        change = False
        line_before = ''
        for line in lines:
            if line.strip() == "match":
                #Encounter "==="
                if result and line_before == "===":
                    #If the previous line is "===", start deletion
                    deleting = True
                    change = True
                    #Remove the previous line
                    result.pop()
            elif line.strip() == "===" and deleting:
                result.append(line)
                deleting = False  #Exit deletion mode
            elif deleting:
                #If in deletion mode, skip the current line
                continue
            else:
                #Not in deletion mode, add the line to the result normally
                result.append(line)
                #If the current line is "match", but do not delete immediately, just record the state
                if line.strip() == "match":
                    print('why occur match')
                    #Ensure the previous line is "===", this condition has already been handled earlier
                    pass
            line_before = line.strip()
            #If encountering a new "===" and not in deletion mode, end deletion


        #Write the result back to the file, or you can choose other processing methods
        with open(file_path, 'w', encoding='utf-8') as file:
            file.writelines(result)
        if change == True:
            print(f"finish {file_path}")


def compare3code(path1,path2,path3,output_path):
    #Get all file paths under three paths
    files1 = set()
    files2 = set()
    files3 = set()

    def collect_files(path, files_set):
        ignore_dirs = {".git",".idea", "__MACOSX","META-INF",".vscode",".settings"}  #Set of default ignored folders
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

    #Find files present in all three versions
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


def get_student_score(input_folder, output_excel_path, homework_ids):
    students_data = {}

    #Traverse each student folder
    for student_id in os.listdir(input_folder):
        student_dir = os.path.join(input_folder, student_id)
        if not os.path.isdir(student_dir):
            continue  #Skip non-folders

        student_scores = {}
        for hw_id in homework_ids:
            hw_dir = os.path.join(student_dir, hw_id)
            if not os.path.isdir(hw_dir):
                student_scores[hw_id] = 0.0
                continue

                #Find last and first files
            last_files = glob.glob(os.path.join(hw_dir, 'last_*.txt'))
            if last_files:
                filename = os.path.basename(last_files[0])  #Take the first last file
            else:
                first_files = glob.glob(os.path.join(hw_dir, 'first_*.txt'))
                if first_files:
                    filename = os.path.basename(first_files[0])  #Take the first first file
                else:
                    student_scores[hw_id] = 0.0
                    continue

            #Use regex to extract scores
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

    #Create DataFrame and ensure column order
    df = pd.DataFrame.from_dict(students_data, orient='index', columns=homework_ids)

    #Ensure output directory exists
    os.makedirs(os.path.dirname(output_excel_path), exist_ok=True)

    #Export to Excel
    df.to_excel(output_excel_path)


def get_student_submit_count(input_folder, output_excel_path, homework_ids):
    students_data = {}

    #Traverse each student folder
    for student_id in os.listdir(input_folder):
        student_dir = os.path.join(input_folder, student_id)
        if not os.path.isdir(student_dir):
            continue  #Skip non-folders

        submission_counts = {}
        for hw_id in homework_ids:
            hw_dir = os.path.join(student_dir, hw_id)
            total_submissions = 0

            #Check if the assignment folder exists
            if os.path.exists(hw_dir) and os.path.isdir(hw_dir):
                #Traverse sub-assignment folders
                for sub_hw in os.listdir(hw_dir):
                    sub_hw_path = os.path.join(hw_dir, sub_hw)
                    if os.path.isdir(sub_hw_path):
                        #Count submitted folders
                        submissions = [name for name in os.listdir(sub_hw_path)
                                       if os.path.isdir(os.path.join(sub_hw_path, name))]
                        total_submissions += len(submissions)

            submission_counts[hw_id] = total_submissions

        students_data[student_id] = submission_counts

    #Create DataFrame and preserve column order
    df = pd.DataFrame.from_dict(students_data, orient='index', columns=homework_ids)

    #Ensure output directory exists
    os.makedirs(os.path.dirname(output_excel_path), exist_ok=True)

    #Export to Excel
    df.to_excel(output_excel_path)


def get_basic_data():
    assign_num = {assignment_id: 0 for assignment_id in assignments}
    pass_num = {assignment_id: 0 for assignment_id in assignments}
    for student_id in os.listdir(root_dir):
        student_path = os.path.join(root_dir, student_id)
        for assignment_id in assignments:
            assignment_path = os.path.join(student_path, assignment_id)
            if os.path.exists(assignment_path):
                assign_num[assignment_id] += 1
                score_path1 = os.path.join(assignment_path, 'first_100.0.txt')
                score_path2 = os.path.join(assignment_path, 'last_100.0.txt')
                if os.path.isfile(score_path1) or os.path.isfile(score_path2):
                    pass_num[assignment_id] += 1
    print(f"assign_num:{assign_num}")
    print(f"pass_num:{pass_num}")

def traverse_data():
    flag = 0
    #Traverse all student folders
    for student_id in os.listdir(root_dir):
        # if student_id == "22371105":
        #     flag = 1
        #     continue
        # if flag == 0:
        #     continue
        student_path = os.path.join(root_dir, student_id)
        if os.path.isdir(student_path):
            #Traverse all assignments folders for each student
            path1 = '' #Last submission of the previous assignment
            path2 = '' #First submission of the next assignment
            path3 = '' #Last submission of the next assignment
            for assignment_id in assignments:
                assignment_path = os.path.join(student_path, assignment_id)
                if not os.path.exists(assignment_path):
                    continue
                submit_list = os.listdir(assignment_path)
                if assignment_id == assignments[0] and (len(submit_list) == 4 or len(submit_list) == 5):
                    score_path = os.path.join(student_path, assignment_id,'last_100.0.txt')
                    if not os.path.isfile(score_path):
                        break
                    path1 = os.path.join(student_path, assignment_id,'last')
                elif assignment_id == assignments[0] and (len(submit_list) == 2 or len(submit_list) == 3):
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

def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate GumTree diffs for one adjacent assignment transition."
    )
    parser.add_argument(
        "--data-root",
        default=os.environ.get("HIRETEST_DATA_ROOT", str(release_root() / "data")),
        help="Authorized submission-data root; see README.md.",
    )
    parser.add_argument(
        "--derived-root",
        default=str(data_workspace_root()),
        help="Writable directory for generated intermediate data.",
    )
    parser.add_argument("--from-assignment", required=True, help="Earlier assignment ID.")
    parser.add_argument("--to-assignment", required=True, help="Later assignment ID.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    root_dir = str(Path(args.data_root).expanduser().resolve())
    assignments = [args.from_assignment, args.to_assignment]
    dst_dir = str(
        Path(args.derived_root).expanduser().resolve()
        / "version_diffs"
        / f"{args.from_assignment}_to_{args.to_assignment}"
    )
    if not Path(root_dir).is_dir():
        raise FileNotFoundError(
            f"Data directory not found: {root_dir}. Obtain the authorized data package "
            "and configure it as described in README.md."
        )
    traverse_data()
