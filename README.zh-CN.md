# HiReTest

中文 | [English](README.md)

HiReTest 是一种面向递进式编程作业的历史修复引导测试生成方法。它比较修复代码与继承代码之间的变化，识别与修复有关的修改，将其与作业约束结合，并使用大语言模型生成和审查测试。本仓库包含 HiReTest 的实现、公开提示词模板，以及主方法在五个 SysY 编译器作业阶段上的公开产物。

这是第一个稳定公开版本，版本号为 `1.0.0`。

## 发布范围

本仓库只发布 **HiReTest 主方法本身**的实现和实验结果。对比方法的实现、适配代码、配置、生成结果，以及消融实验和人工评估材料均不在本次发布范围内。

论文中的对比实验基于相应方法的公开实现，并按照论文所述设置完成。本仓库是 HiReTest 主方法发布仓库，不是论文全部对比实验的完整复现包。

## 仓库结构

```text
.
├── artifacts/                # 已发布的 HiReTest 测试用例和结果工作簿
├── prompts/public_templates/ # 公开的生成、约束和审查提示词
├── requirements/core.txt     # HiReTest 的 Python 依赖
├── scripts/                  # artifact 清单生成脚本
├── src/hiretest/             # HiReTest 实现和评估器
├── .env.example              # 不含真实密钥的环境变量模板
├── CITATION.cff              # 引用元数据
├── LICENSE                   # MIT 许可证
└── pyproject.toml            # Python 项目元数据
```

## 已发布产物

```text
artifacts/
├── cases/Hiretest/
│   ├── 1to2/
│   ├── 2to3/
│   ├── 3to4/
│   ├── 4to5/
│   └── 5to6/
├── results/Hiretest/
│   ├── analysis_1to2.xlsx
│   ├── analysis_2to3.xlsx
│   ├── analysis_3to4.xlsx
│   ├── analysis_4to5.xlsx
│   └── analysis_5to6.xlsx
└── manifest.json
```

| 阶段 | 测试程序数 | 输入文件数 | 结果工作簿 |
| --- | ---: | ---: | --- |
| `1to2` | 213 | 0 | `analysis_1to2.xlsx` |
| `2to3` | 389 | 0 | `analysis_2to3.xlsx` |
| `3to4` | 93 | 0 | `analysis_3to4.xlsx` |
| `4to5` | 240 | 240 | `analysis_4to5.xlsx` |
| `5to6` | 59 | 59 | `analysis_5to6.xlsx` |

前三个阶段中的每个 `caseN.txt` 都是完整的 SysY 源程序。`4to5` 和 `5to6` 阶段中的每个测试由 `caseN.txt` 源程序和对应的 `inputN.txt` 标准输入文件组成。

`artifacts/manifest.json` 记录了公开文件、数量和 SHA-256 校验值。

## HiReTest 实现

主方法流水线位于 `src/hiretest/`：

- `compare.py` 和 `analyse.py` 比较相邻程序版本并分析 AST 级变化。这里的 “compare” 是比较历史程序版本，不是运行对比方法。
- `data_preprocessing.py` 将历史变化与标签转换为模型可用的数据。
- `train.py` 训练和评估修复变化分类模型。
- `export_positive_predictions.py` 导出被模型判断为修复相关的代码变化。
- `get_results.py` 提取源代码上下文并构造历史修复引导提示词。
- `ask_for_llm.py` 通过配置的大语言模型 API 生成、检查和修正候选测试。
- `test.py` 编译、执行生成的测试并生成结果工作簿。
- `reproduce_test.py` 提供重新评估已发布 HiReTest 测试的命令行入口。
- `runtime.ll` 提供后端阶段使用的 LLVM 兼容 SysY 输入输出运行时。

`prompts/public_templates/` 中的公开文件包括五个阶段的生成提示词、处理后和原始阶段约束，以及测试审查提示词。

## 安装

项目需要 Python 3.10 或更高版本，建议使用虚拟环境。

```bash
python -m venv .venv
```

在 Windows 上激活：

```powershell
.\.venv\Scripts\Activate.ps1
```

在 Linux/macOS 上激活：

```bash
source .venv/bin/activate
```

安装项目及其核心依赖：

```bash
python -m pip install -r requirements/core.txt
python -m pip install -e .
```

## 检查公开产物

运行以下命令，确认脚本能够识别五个公开阶段：

```bash
python -m hiretest.reproduce_test --case-root artifacts/cases --stage all --dry-run
```

公开产物发生变化后，使用以下命令重建完整性清单：

```bash
python scripts/build_artifact_manifest.py
```

## 重新评估公开测试

本仓库不包含原始学生提交、身份信息、成绩、参考实现及其他课程保密输入。完整重新评估需要获得授权的数据包，并通过 `.env.example` 配置本地 MARS 和 LLVM。

Windows 示例：

```powershell
python -m hiretest.reproduce_test `
  --case-root artifacts/cases `
  --stage 1to2 `
  --students-dir D:\path\to\authorized\data_2025\data
```

新生成的复现工作簿默认写入 `artifacts/reproduced/`，不会覆盖已经发布的工作簿。

评估器会在需要时使用以下环境变量：

- `HIRETEST_DATA_ROOT` 和 `HIRETEST_DERIVED_DATA_ROOT` 指向仓库外的授权数据。
- `HIRETEST_REPAIR_PROMPT_ROOT` 指向无法公开的授权历史修复提示词。
- `HIRETEST_MARS_JAR` 指向单独获取的 MARS 安装。
- `HIRETEST_LLI` 指向 LLVM 的 `lli`。
- `HIRETEST_RUNTIME_LL` 可用于覆盖仓库中的 `src/hiretest/runtime.ll`。
- `HIRETEST_REFERENCE_IDS_*` 使用假名化标识指定授权参考实现。
- `OPENAI_BASE_URL`、`OPENAI_API_KEY` 和 `OPENAI_MODEL` 配置测试生成使用的大语言模型 API。

不要提交填写了真实信息的 `.env` 文件。

## 数据与隐私

本仓库发布的是生成的测试产物，而不是底层学生数据。原始和派生学生数据、身份、成绩、私有提示词、模型检查点、参考实现和 API 凭据必须保存在公开仓库之外。

如果公开或受控数据集已经存入 Zenodo，请在此处补充其稳定 DOI 链接并说明访问条件。不要填写未经确认的地址。

## 引用

如果你使用了 HiReTest，请引用对应论文和所使用的 artifact 版本。`CITATION.cff` 已记录当前作者、版本号和许可证；公开仓库地址和论文 DOI 可在确定后补充。

## 许可证

HiReTest 的原创源代码和公开实验产物采用 MIT License，详见 `LICENSE`。第三方工具和依赖继续遵循各自的许可证。
