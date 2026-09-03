@echo off
REM validate_sysy.bat - 位于 Fuzz4All 根目录
REM 用途：验证 Fuzz4All 生成的 SysY 测试用例

set FUZZ_FILE=%1
set PROJECT_ROOT=%~dp023373332\1856\last

REM 检查输入
if "%FUZZ_FILE%"=="" (
    echo [ERROR] 用法: validate_sysy.bat ^<fuzz_file_path^>
    exit /b 1
)
if not exist "%FUZZ_FILE%" (
    echo [ERROR] 测试用例文件不存在: %FUZZ_FILE%
    exit /b 1
)

REM 进入被测系统目录
cd /d "%PROJECT_ROOT%"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] 无法进入被测系统目录: %PROJECT_ROOT%
    exit /b 1
)

REM 清空输出文件
type nul > symbol.txt
type nul > error.txt

REM 复制测试用例到 testfile.txt
copy /Y "%FUZZ_FILE%" testfile.txt >nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] 无法复制测试用例
    exit /b 1
)

REM 编译（如果 .class 不存在）
if not exist Compiler.class (
    javac Compiler.java
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] 编译失败
        exit /b 1
    )
)

REM 运行被测程序
java Compiler
set EXIT_CODE=%ERRORLEVEL%

REM 检查输出文件是否非空
for %%i in (symbol.txt) do set SYMBOL_SIZE=%%~zi
for %%i in (error.txt) do set ERROR_SIZE=%%~zi

REM 判断合法性：正常退出 + 至少一个输出文件非空
if %EXIT_CODE% EQU 0 (
    if %SYMBOL_SIZE% GTR 0 goto VALID
    if %ERROR_SIZE% GTR 0 goto VALID
)

exit /b 1

:VALID
exit /b 0