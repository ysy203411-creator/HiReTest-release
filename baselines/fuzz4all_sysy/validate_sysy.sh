#!/bin/bash
# validate_sysy.sh - Linux 版本

if [ $# -ne 1 ]; then
    echo "[ERROR] 用法: validate_sysy.sh <fuzz_file_path>"
    exit 1
fi

FUZZ_FILE="$1"
if [ ! -f "$FUZZ_FILE" ]; then
    echo "[ERROR] 测试用例文件不存在: $FUZZ_FILE"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="${FUZZ4ALL_SYSY_PROJECT_ROOT:-$SCRIPT_DIR/23373332/1856/last}"

cd "$PROJECT_ROOT" || {
    echo "[ERROR] 无法进入被测系统目录: $PROJECT_ROOT"
    exit 1
}

> symbol.txt
> error.txt
cp -f "$FUZZ_FILE" testfile.txt || {
    echo "[ERROR] 无法复制测试用例"
    exit 1
}

if [ ! -f Compiler.class ]; then
    javac Compiler.java || {
        echo "[ERROR] 编译失败"
        exit 1
    }
fi

java Compiler
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    if [ $(wc -c < symbol.txt) -gt 0 ] || [ $(wc -c < error.txt) -gt 0 ]; then
        exit 0
    fi
fi

exit 1
