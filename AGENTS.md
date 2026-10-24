# AGENTS.md — 多宿主安装说明

FigSmith 是一个**纯文件技能树**。没有编译，没有注册表，没有守护进程。
「安装」= 把树复制到宿主 Agent 扫描 `SKILL.md` 的目录。

---

## 1. 安装

```bash
# bash
./install.sh                                  # 全量
./install.sh --core-only                      # 只装内核
./install.sh --domain paper-figure            # 内核 + 单域
./install.sh --target /custom/path            # 指定宿主目录

# powershell
.\install.ps1                                 # 全量
.\install.ps1 -CoreOnly                       # 只装内核
.\install.ps1 -Domain paper-figure            # 内核 + 单域
.\install.ps1 -Target "$HOME\.codex\skills"   # 指定宿主目录
```

---

## 2. 各宿主的目录约定

| 宿主 | 技能目录 | 说明 |
|---|---|---|
| **opencode** | `~/.config/opencode/skill/` 或项目内 `.opencode/skill/` | 原生 `read` 工具可直接读图，验收闭环开箱即用 |
| **Claude Code** | `~/.claude/skills/` | 默认目标。`SKILL.md` 的 frontmatter 需带 `name` 和 `description` |
| **Codex** | `~/.codex/skills/`（或 `AGENTS.md` 同级 `skills/`） | 读取规则同 Claude Code |

示例：

```bash
./install.sh --target ~/.config/opencode/skill     # opencode
./install.sh --target ~/.claude/skills             # Claude Code
.\install.ps1 -Target "$HOME\.codex\skills"        # Codex
```

安装后目录形如 `<target>/figsmith/`，宿主扫到 `figsmith/domains/*/SKILL.md` 即生效。

---

## 3. 环境依赖

必要：

- Python 3.10+
- 依赖见 `requirements.txt`（已锁版本）：`pip install -r requirements.txt`
  —— numpy、matplotlib、Pillow、reportlab、python-pptx、fontTools

按需：

| 后端 | 额外依赖 | 缺失时 |
|---|---|---|
| `backends/png.py` 浏览器光栅化 | 系统 Chrome / Edge | 自动降级到 Pillow 光栅化（文字 shaping 精度下降，几何仍准确） |
| `backends/pdf.py` | reportlab | PDF 输出不可用 |
| `backends/pptx.py` | python-pptx | PPTX 输出不可用 |
| `backends/drawio.py` | 无（纯 XML + zlib） | — |
| `backends/html2pdf.py` | 系统 Chrome / Edge | **不可用**（PDF 导出必须靠浏览器 print-to-pdf，无降级路径） |
| `core/tokens/loader.py` 文本度量 | fontTools | 降级到 CJK/latin 估算（可能造成拆行位置偏移） |

**不依赖联网字体。** 缺字体时按 token 里的 `*_fallback` 降级；用 `python -m core.tokens.loader --check` 查本机缺哪一级。

---

## 4. 验证安装

```bash
cd <target>/figsmith
python -m core.ir examples/arch-diagram/layered-arch/arch.ir.json   # IR 合法
python -m core.verify.check_contrast examples/arch-diagram/layered-arch/arch.png
python -m backends.svg examples/arch-diagram/layered-arch/arch.ir.json -o /tmp/t.svg
python -m core.tokens.loader --check                               # 令牌一致性
python tools/regress.py                                            # 回归套件
python tests/test_verify.py                                        # 验收奕约单测
```

全部通 = 装好了。`tools/` 与 `tests/` 已随树安装，上面的命令在安装目录里就能跑。

---

## 5. 给 Agent 的入口

宿主加载 FigSmith 后，先读 `core/METHOD.md`（唯一方法论来源），
再按任务类型进对应域包：

```
任务 → domains/<域>/SKILL.md → references/（按需）→ 生成 → core/verify/ 自检 → 裁判
```

域包清单见 `README.md`。**没有 SKILL.md 的域不算存在。**

---

## 6. 已知宿主差异

| 差异 | 影响 | 处理 |
|---|---|---|
| 部分宿主 `read` 不接受 PDF | PDF 交付物无法直接验收 | 走 PNG 代理回渲，见 `docs/vision-probe-report.md` |
| 各宿主 SKILL.md 的 frontmatter 字段名不一 | 技能可能不被发现 | 各域 SKILL.md 只写 `name` + `description`，公共字段最小化 |
| 路径分隔符 | Windows 下脚本需 `\` | 所有脚本用 `pathlib`，不用硬编码分隔符 |
