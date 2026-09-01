# 奶茶店选址 AI 分析评估助手

第一期 Web MVP：对一个奶茶候选点做**可溯源**可行性评估，输出完整十节报告，支持 Word / PNG / DXF 下载。

> 严格遵循 `产品需求文档.md` V1.3。本期只做 Web，不做 Grasshopper 插件。

## 快速开始（电脑小白版）

### 1. 安装 Python

确保已安装 **Python 3.7+**（推荐 3.10+）。命令行输入 `python --version` 检查。

### 2. 进入项目目录

```powershell
cd "E:\cursor experiment\商圈选址可行性简报"
```

### 3. 创建虚拟环境并安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4. 配置环境变量（可选）

```powershell
copy .env.example .env
```

- **不填 Key 也能跑**：点击「演示点 A / B」即可完整生成报告与下载。
- 查任意真地点：在网页表单填写您自己的 **高德 Web 服务 Key**（不是 JS Key）。
- 可选 LLM Key：有则 AI 写正文；无则用模板填槽（仍禁止编造）。

### 5. 启动服务

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

浏览器打开：**http://127.0.0.1:8000**

### 6. 演示流程

1. 点击 **演示点 A · 过密商场** 或 **演示点 B · 偏空社区**
2. 点击 **生成完整报告**
3. 阅读决策摘要与十节正文
4. 下载 Word / PNG / DXF

## 公网部署与二维码

部署到任意 PaaS（Railway、Render、Vercel、云服务器等）后，把公网 URL 生成二维码即可扫码打开——**二维码只是 URL 入口**，本期已实现网页本身。

### 部署到 Vercel

1. 将代码推送到 GitHub / Gitee / GitLab
2. 打开 [vercel.com/new](https://vercel.com/new)，导入仓库
3. Vercel 会自动识别 FastAPI（入口：`app/main.py`），无需额外构建命令
4. 在 **Settings → Environment Variables** 配置（可选）：
   - `AMAP_WEB_KEY` / `AMAP_JS_KEY` / `AMAP_SECURITY_JS_CODE` — 高德 Key
   - `LLM_API_KEY` / `LLM_API_BASE` / `LLM_MODEL` — AI 正文生成
5. 点击 Deploy

**说明**：Vercel 为无状态环境，用户账号与报告文件写入 `/tmp`；报告页通过 sessionStorage 兜底加载。Word/PNG 下载在同一次会话内可用，刷新后可能失效。演示点无需 Key 即可体验。

本地 CLI 部署：

```powershell
npx vercel login
npx vercel --prod
```

## 目录结构

```
app/                 FastAPI 应用与流水线
config/scoring.yaml  计分权重与否决阈值（改分只改此文件）
data/demo/           脱敏演示点 JSON（≥2 个）
data/eval/           3 点评测检查清单
知识库/               本地 RAG 短文
output/              生成报告与导出文件（gitignore）
```

## 铁律摘要

- 禁止编造 POI、客流、评分、回本
- 分数由 `scoring.yaml` + 程序计算，LLM 不得改分
- 每条结论绑定证据 ID
- Key 不上仓库、不写日志
- 无 Key 非演示点：提示填 Key，不生成假周边

## 评测

固定 3 点检查清单见 `data/eval/eval_checklist.yaml`。改 Prompt 或阈值后对照同一批点验证。

```powershell
python scripts/run_eval_check.py
```

## 技术栈

Python 3 · FastAPI · Jinja2 · httpx · python-docx · ezdxf · matplotlib · 本地知识库检索
