# China Targeted Resume

`china-targeted-resume` 可将只读的 Markdown 职业知识库转换为面向目标公司和岗位、以证据为依据的简历。它会分析岗位要求、映射有来源支持的个人证据、记录差距与约束、审计简历中可见的陈述，并在本地渲染适合 ATS（Applicant Tracking System，申请人跟踪系统）的 PDF。

本仓库同时是：

- 一个 Python 3.14 命令行应用；以及
- 一个可安装的 OMP Skill，其编排说明位于 [`SKILL.md`](SKILL.md)。

## 生成内容

成功生成后，会在指定的输出根目录下创建一个新的、不会覆盖已有内容的运行目录：

```text
OUTPUT_ROOT/
└── company-slug--role-slug--YYYYMMDDTHHMMSSffffffZ/
    ├── resume-targeted.md
    ├── resume-ats.txt
    ├── resume-document.json
    ├── resume.html
    ├── resume.pdf
    ├── resume-preview.png
    ├── audit-report.md
    ├── content-validation.json
    ├── provenance.json
    ├── requirements.json
    ├── competencies.json
    ├── evidence-map.json
    ├── gaps.json
    ├── application-constraints.json
    ├── application-recommendation.json
    ├── confirmation-questions.md
    ├── interview-questions.md
    ├── source-manifest.json
    ├── run.json
    └── role-dossier/
```

运行目录不会被自动删除。每次调用都会创建一个带 UTC 时间戳的目录，因此不会静默覆盖之前的运行结果。

## 安全模型

- 职业知识库是只读的运行时输入。
- 输出根目录必须位于源根目录之外。
- 运行目录使用 `0700` 权限模式；生成的文件使用 `0600` 权限模式。
- 持久化索引只包含导航元数据和哈希，不包含源文件正文或联系方式。
- 公司调研内容绝不会变成候选人的个人经历。
- 未验证、有冲突、私密、过时或缺乏支持的陈述会被省略，或转换为待确认问题。
- 生成的 PDF 只有在确定性的内容检查与 PDF 检查全部通过后才会被接受。

## 环境要求

- Linux
- Python 3.14 或更高版本
- [`uv`](https://docs.astral.sh/uv/)
- Playwright Chromium
- 安装在 `/usr/share/fonts` 下的 Noto Sans CJK SC 或 Source Han Sans SC

在 Arch Linux 上，可通过以下命令安装字体依赖：

```bash
sudo pacman -S --needed noto-fonts-cjk
```

安装项目依赖和 Chromium：

```bash
cd /path/to/china-targeted-resume
uv sync
uv run playwright install chromium
```

确认 CLI 可用：

```bash
uv run china-targeted-resume --help
```

下文所有示例均使用 `uv run china-targeted-resume`。如果已全局安装该软件包，可省略 `uv run`。

## 教程：准备源路径和输出路径

为当前 shell 设置路径：

```bash
export SOURCE_ROOT=/path/to/read-only-career-knowledge-base
export OUTPUT_ROOT=/path/to/private-resume-output
```

`OUTPUT_ROOT` 不能等于 `SOURCE_ROOT`，也不能位于 `SOURCE_ROOT` 之下。

## 教程：发现公司和岗位

列出源适配器识别到的公司：

```bash
uv run china-targeted-resume list-companies \
  --source "$SOURCE_ROOT"
```

列出某个确切公司 ID 或显示名称下的岗位：

```bash
uv run china-targeted-resume list-roles \
  --source "$SOURCE_ROOT" \
  --company COMPANY
```

在后续命令中使用返回的标识符。如果有多个公司或岗位匹配，请明确选择一个，而不是猜测。

## 教程：根据完整且当前有效的 JD 生成简历

完整且当前有效的职位描述会产生 Tier A、`exact-current-jd` 分析。必须且只能提供 `--jd-file`、`--jd-text` 或 `--jd-url` 中的一个参数。

使用本地 UTF-8 JD 文件：

```bash
uv run china-targeted-resume generate \
  --source "$SOURCE_ROOT" \
  --company COMPANY \
  --role "ROLE TITLE" \
  --jd-file /path/to/job-description.md \
  --mode targeted_application \
  --language zh-CN \
  --pages 2 \
  --template ats-simple \
  --output "$OUTPUT_ROOT"
```

使用 HTTPS JD URL：

```bash
uv run china-targeted-resume generate \
  --source "$SOURCE_ROOT" \
  --company COMPANY \
  --role "ROLE TITLE" \
  --jd-url https://jobs.example.invalid/ROLE \
  --mode targeted_application \
  --language zh-CN \
  --pages 2 \
  --template ats-simple \
  --output "$OUTPUT_ROOT"
```

该命令会输出 JSON，其中包含 `run_dir` 和各个生成产物的路径。请保留 `run_dir`；后续验证和刷新命令会用到它。

## 教程：仅知道岗位时生成简历

如果没有完整且当前有效的 JD，请省略所有 JD 选项。当源中包含确切岗位以及注明日期的公司调研资料时，流水线会以 Tier B 继续执行：

```bash
uv run china-targeted-resume generate \
  --source "$SOURCE_ROOT" \
  --company COMPANY \
  --role "ROLE TITLE" \
  --mode targeted_application \
  --language zh-CN \
  --pages 2 \
  --template human-readable \
  --output "$OUTPUT_ROOT"
```

Tier B 输出会在审计产物中记录来源时效、缺失的要求、冲突、推断侧重点以及覆盖范围限制，而不会将这些内容作为简历事实呈现。

## 教程：检查已完成的运行

将变量设置为 `generate` 返回的确切时间戳目录：

```bash
export RUN_DIR="$OUTPUT_ROOT/company-slug--role-slug--YYYYMMDDTHHMMSSffffffZ"
```

重新执行内容审计：

```bash
uv run china-targeted-resume validate-content \
  --run "$RUN_DIR"
```

独立检查 PDF：

```bash
uv run china-targeted-resume inspect-pdf \
  --pdf "$RUN_DIR/resume.pdf" \
  --pages 2 \
  --expected-name "CANDIDATE NAME"
```

`--pages` 是可接受的页数上限。当上限为两页时，一页 PDF 也能通过检查。

打开以下文件进行人工审阅：

```text
RUN_DIR/resume-targeted.md
RUN_DIR/resume.pdf
RUN_DIR/resume-preview.png
RUN_DIR/audit-report.md
RUN_DIR/content-validation.json
```

只有在内容审计没有错误、PDF 检查成功，并且预览中没有裁切、重叠、CJK 文字损坏、项目符号格式异常，也没有在简历可见区域出现审计或来源追踪措辞时，本次运行才算完成。

## 教程：单独重建各个阶段

重建确定性的证据映射：

```bash
uv run china-targeted-resume build-evidence-map \
  --run "$RUN_DIR"
```

重新渲染已有的规范化简历文档：

```bash
uv run china-targeted-resume render \
  --document "$RUN_DIR/resume-document.json" \
  --output "$RUN_DIR/resume.pdf"
```

输出目录必须保持私密，并且不能通过符号链接穿越路径边界。

## 教程：分析请求 JSON

`analyze-role` 接受经过验证的 `RunRequest` JSON 文档。完整约定见 [`schemas/request.schema.json`](schemas/request.schema.json)。

示例：

```json
{
  "schema_version": 1,
  "source_adapter": "markdown-career-v1",
  "source_root": "/path/to/read-only-career-knowledge-base",
  "output_root": "/path/to/private-resume-output",
  "company_ref": "COMPANY",
  "role_ref": "ROLE TITLE",
  "jd": {
    "text": null,
    "file": "/path/to/job-description.md",
    "url": null
  },
  "output_mode": "targeted_application",
  "language": "zh-CN",
  "target_pages": 2,
  "template": "ats-simple",
  "persist_role_research": false,
  "refresh_external_sources": false,
  "export_roadmap_handoff": false,
  "application_constraints": {}
}
```

执行分析：

```bash
uv run china-targeted-resume analyze-role \
  --request /path/to/request.json
```

除非已明确审阅并批准将其持久化到源仓库，否则岗位档案会保留在本次运行目录中。

## 教程：刷新岗位或证据分析

JD 或公司调研发生变化后，刷新岗位分析：

```bash
uv run china-targeted-resume refresh-role \
  --role "$RUN_DIR"
```

负责归属的个人数据源发生变化后，刷新证据映射：

```bash
uv run china-targeted-resume refresh-match \
  --role "$RUN_DIR"
```

刷新操作会创建新的、不会覆盖已有内容的输出，而不是重写源知识库。路线图条目绝不会提升匹配状态；经过验证的工作必须先记录到正确的个人数据归属文件中。

## 教程：导出已确认的差距

路线图移交必须显式执行，并且是单向的。只有在审阅差距并决定创建独立学习计划后，才应导出：

```bash
uv run china-targeted-resume export-roadmap-handoff \
  --role "$RUN_DIR" \
  --severity Critical,Major \
  --output "$RUN_DIR/roadmap-handoff.json"
```

该命令会导出已确认的差距，但不会创建学习计划，也不会更改当前证据状态。

## 输出模式和模板

输出模式：

- `targeted_application`：允许使用已确认的、仅限求职申请场景的 P2 证据。
- `public_portfolio`：排除仅限求职申请的材料，并按要求排除私密联系方式。
- `master_resume`：生成更广泛、以证据为依据的简历，不会把信息不足的目标伪装成确切岗位。

模板：

- `ats-simple`：保守的单栏 ATS 布局。
- `human-readable`：保持相同的语义阅读顺序，但采用更面向人工阅读的视觉呈现。

页数限制必须是 1 到 6 之间的整数。系统会先从语义层面压缩内容，再缩小排版尺寸；同时会继续强制执行已配置的最小字号和页边距限制。

## 使用 OMP Skill

安装后的 Skill 可让 OMP 会话理解自然语言请求，并编排确定性的 CLI。Skill 仍要求明确指定源边界和输出边界。

示例提示词：

```text
Use my career knowledge base at /path/to/career-db and the JD at
/path/to/job-description.md to generate a two-page zh-CN ATS resume for
Company A's exact AI Infrastructure Engineer role. Save all artifacts under
/path/to/private-output and report the content and PDF audit results.
```

Skill 应解析目标层级、运行 CLI、仅提出会对结果产生实质影响的确认问题，并报告带时间戳的运行目录。它不得将生成的简历文本写回 `personal-data/`。

## 测试

运行完整的确定性测试套件：

```bash
uv run pytest -q
```

## 构建和打包

构建 Python 发行包和经过筛选的 Skill 归档：

```bash
uv build
uv run python scripts/package_skill.py
```

预期产物：

```text
dist/china_targeted_resume-0.1.0.tar.gz
dist/china_targeted_resume-0.1.0-py3-none-any.whl
dist/china-targeted-resume.skill
```

经过筛选的 `.skill` 归档包含运行时代码、schema、参考文档、模板、脚本、`SKILL.md` 和英文 README。它不包含测试、评估工作区、缓存、真实源数据或生成的简历输出。

## 评估工作区

Skill Creator 评估工作流会创建一个同级目录，例如：

```text
<project-parent>/china-targeted-resume-workspace
```

其中包含各次迭代输出、使用 Skill 与基线的对比、评分、计时、基准数据和 `review.html`。Python 包不会导入该目录，`.skill` 归档也不会包含它，运行 CLI 或安装后的 Skill 均不依赖它。

需要保留可复现的基准测试历史时，请保留该目录。只有在不再需要这些评估记录时，才归档或删除它。

## 查找生成的运行结果

生成的简历保存在 `--output` 指定的根目录下，而不是项目仓库或评估工作区中。

例如：

```text
<output-root>/
└── company-slug--role-slug--YYYYMMDDTHHMMSSffffffZ/
```

每次运行都包含简历、PDF、预览、审计、来源追踪、证据映射和岗位档案。流水线不会在测试后删除运行结果。

如果文件管理器中没有显示该目录：

1. 将完整绝对路径粘贴到位置栏；
2. 刷新父目录；
3. 确认打开的是通过 `--output` 传入的确切根目录；
4. 在终端中对完整路径运行 `stat`。

## 故障排除

### 缺少 Chromium 可执行文件

```bash
uv run playwright install chromium
```

### 缺少 CJK 字体

请在 `/usr/share/fonts` 下安装 Noto Sans CJK SC 或 Source Han Sans SC。在 Arch Linux 上：

```bash
sudo pacman -S --needed noto-fonts-cjk
```

### 输出路径与源路径重叠

请选择职业知识库之外的输出根目录。源路径和输出路径不能相同，输出路径也不能是源路径的后代目录。

### 现有输出根目录权限过宽

使用私密输出目录：

```bash
chmod 700 "$OUTPUT_ROOT"
```

生成的文件会自动限制为 `0600` 权限模式。

### 公司或岗位存在歧义

运行 `list-companies` 和 `list-roles`，然后传入确切的返回标识符。流水线会有意避免在多个匹配项之间进行猜测。

### PDF 已存在，但验证失败

阅读 `content-validation.json` 和 `audit-report.md`，修复有来源支持的内容问题或渲染问题，然后重新运行 `validate-content`、`render` 和 `inspect-pdf`。仅有文件存在并不代表验收通过。

## 更多文档

- [`SKILL.md`](SKILL.md)：OMP 编排约定
- [`references/source-adapter.md`](references/source-adapter.md)：源发现与隔离
- [`references/role-resolution.md`](references/role-resolution.md)：Tier A-D 解析
- [`references/evidence-policy.md`](references/evidence-policy.md)：事实与披露门禁
- [`references/role-dossier-contract.md`](references/role-dossier-contract.md)：七文件岗位档案边界
- [`references/output-contract.md`](references/output-contract.md)：产物约定
- [`references/resume-audit.md`](references/resume-audit.md)：内容与 PDF 验收
- [`references/privacy-policy.md`](references/privacy-policy.md)：隐私与保留规则
- [`references/roadmap-handoff.md`](references/roadmap-handoff.md)：显式差距导出
