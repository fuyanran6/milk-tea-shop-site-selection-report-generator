# 奶茶店选址 AI 分析评估助手

对一个奶茶候选铺位做**可溯源**的可行性评估，输出完整十节报告，支持网页阅读与 Word / PNG / SVG 下载。

**在线仓库：** [github.com/fuyanran6/milk-tea-shop-site-selection-report-generator](https://github.com/fuyanran6/milk-tea-shop-site-selection-report-generator)

---

## 这个项目能做什么

输入一个城市里的候选点位（或直接使用内置演示点），系统会：

1. **采集周边数据** — 通过高德 Web 服务 API 拉取多半径 POI（茶饮竞品、商场、学校、办公、社区、交通等）；演示点使用内置脱敏数据
2. **结构化计分** — 按 `config/scoring.yaml` 计算需求匹配、竞争环境、消费场景、财务评估四项子分与综合建议（推荐 / 谨慎 / 不推荐）
3. **生成十节报告** — 决策摘要、商圈与场景、需求匹配、竞争分析、交通可达、经营可行性、风险、结论、分析图、数据附录
4. **绑定证据链** — 每条关键结论对应证据 ID 与数据来源，报告末尾可展开查看
5. **导出文件** — Word 报告、选址分析图（PNG / SVG）；本地环境还可生成竞争与 POI 统计图表

无高德 Key、无 LLM Key 时，仍可通过**演示点**完整体验全流程。

---

## 快速体验（无需配置）

### 本地运行

**环境要求：** Python 3.12+

```powershell
# 1. 克隆仓库
git clone https://github.com/fuyanran6/milk-tea-shop-site-selection-report-generator.git
cd milk-tea-shop-site-selection-report-generator

# 2. 创建虚拟环境并安装依赖
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. 启动服务
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

浏览器打开 **http://127.0.0.1:8000**，按以下步骤操作：

1. 点击 **「跳过登录，使用演示点」**
2. 点击 **「演示点」** 加载内置样例（人民广场商圈脱敏数据）
3. 点击 **「生成完整报告」**
4. 阅读十节正文，下载 Word / PNG / SVG

> 演示报告会标注「演示点报告」，不代表对真实地址的分析结论。

### 分析真实地点

分析真实候选点需要**高德 Web 服务 Key**（不是 JS API Key）：

1. 注册 / 登录账号
2. 在 **个人中心** 填写高德 Web 服务 Key 与 JS API Key（地图显示用）
3. 在表单中检索地点、地图选点，选填面积、月租、品牌定位等经营信息
4. 点击生成（真实地点约需 20～40 秒）

也可在 `.env` 中配置服务端 Key，供所有访客共用（消耗你的配额）：

```powershell
copy .env.example .env
# 编辑 .env，填写 AMAP_WEB_KEY、AMAP_JS_KEY 等
```

---

## 功能说明

### 报告结构（十章）

| 章节 | 内容 |
|------|------|
| 决策摘要 | 综合分、建议档位、核心原因、决策含义 |
| 商圈与场景 | 场景类型判定（商场型 / 办公型 / 社区型等） |
| 消费者与需求匹配 | 500m 配套结构与需求子分 |
| 竞争分析 | 300m / 500m 茶饮密度、连锁占比、竞争压力 |
| 交通与可达性 | 地铁、公交站距离与可达性说明 |
| 经营可行性 | 租金压力、客单与杯量（需用户填写才做财务评估） |
| 风险因素 | 竞争过密、需求偏弱、财务未核等 |
| 结论与建议 | 可执行下一步（蹲点、谈判、租约核对） |
| 选址分析图 | 底图 + 竞品 / 配套圈层可视化 |
| 数据说明与来源附录 | 数据来源、计分口径、知识库引用 |

### 计分规则

- 权重在 `config/scoring.yaml` 中配置，**改分只改此文件**
- 默认：需求 35 + 竞争 30 + 消费场景 15 + 财务 20
- 未填写租金 / 面积等经营信息时，财务项不计分，综合分最高 80，并提示「财务未核」
- 存在否决规则（如租金超安全线）时，建议档位会被下调
- **LLM 不参与改分**，分数全部由程序计算

### 账号与 Key 管理

- 支持注册 / 登录，Key 保存在本地 SQLite（`data/users.db`，已 gitignore）
- 每个用户可保存自己的高德 Key，下次无需重复填写
- Key 在界面上脱敏显示，不会写入日志或提交到 Git

### 可选 LLM 增强

在 `.env` 中配置 `LLM_API_KEY`（默认兼容 DeepSeek API）后，报告正文由 AI 撰写；未配置时使用模板填槽，**同样禁止编造 POI、客流或评分**。

### 本地知识库（RAG）

`知识库/` 目录存放选址方法论短文（商场型选铺、竞争分析、三日蹲点、租约风险等）。生成报告时按章节检索相关片段，附在对应段落末尾。

---

## 部署到公网（Vercel）

1. 将代码推送到 GitHub
2. 在 [vercel.com/new](https://vercel.com/new) 导入仓库
3. Vercel 会自动识别 FastAPI 入口 `app/main.py`
4. 在 **Settings → Environment Variables** 配置（可选）：
   - `AMAP_WEB_KEY` / `AMAP_JS_KEY` / `AMAP_SECURITY_JS_CODE`
   - `LLM_API_KEY` / `LLM_API_BASE` / `LLM_MODEL`
5. 部署完成后，将公网 URL 生成二维码即可扫码访问

**Vercel 限制说明：**

- 无状态环境，用户数据与报告写入 `/tmp`，刷新后可能失效
- 云端无 matplotlib / Pillow，分析图与统计图表会简化；演示点使用预构建包，体验不受影响
- 报告页支持 `sessionStorage` 兜底，同一次会话内可正常阅读与下载

本地 CLI 部署：

```powershell
npx vercel login
npx vercel --prod
```

---

## 目录结构

```
app/
  main.py              # Vercel 入口（含启动失败兜底页）
  web.py               # FastAPI 路由、用户认证、报告页
  users.py             # 账号与 Key 存储（SQLite）
  pipeline/            # 数据采集 → 计分 → 生成 → 导出流水线
  templates/           # 首页与报告页 HTML
  static/              # 样式、脚本、演示视频
config/
  scoring.yaml         # 计分权重与阈值（唯一改分入口）
data/
  demo/                # 演示点 POI 数据与预构建报告包
  eval/                # 评测检查清单
知识库/                 # 本地 RAG 知识短文
scripts/
  run_eval_check.py    # 改配置后的回归检查
output/                # 生成报告输出（gitignore，本地运行时产生）
```

---

## 设计原则（数据可信）

- **禁止编造** POI 数量、客流、评分、回本周期
- **无 Key 且非演示点** → 明确提示，不生成假周边
- **分数由程序计算**，LLM 只写叙述，不得修改数字
- **每条结论绑定证据 ID**，可追溯到高德 POI 或用户输入
- **Key 不上仓库、不写日志**（`.env` 与 `data/users.db` 已忽略）

---

## 评测回归

固定检查清单见 `data/eval/eval_checklist.yaml`（含 3 个演示场景）。修改 `scoring.yaml` 或 Prompt 后运行：

```powershell
python scripts/run_eval_check.py
```

---

## 技术栈

| 类别 | 技术 |
|------|------|
| 后端 | Python 3.12 · FastAPI · Jinja2 · httpx |
| 数据 | 高德 Web 服务 API · OpenStreetMap（建筑轮廓，可选） |
| 存储 | SQLite（用户账号）· 本地文件（报告输出） |
| 导出 | python-docx（Word）· 自研 SVG / PNG 渲染 |
| 图表 | matplotlib（仅本地环境，可选安装） |
| 知识库 | 本地 Markdown 检索 |
| 部署 | Vercel Serverless / 本地 uvicorn |

---

## 常见问题

**Q：没有高德 Key 能用吗？**  
可以。点击「跳过登录」→「演示点」即可完整体验，无需任何 Key。

**Q：Web 服务 Key 和 JS API Key 有什么区别？**  
Web 服务 Key 用于服务端 POI 查询与地理编码；JS API Key 用于浏览器地图显示。须在高德控制台分别创建，不能混用。

**Q：综合分是官方标准吗？**  
不是。综合分是本工具按 `scoring.yaml` 计算的辅助参考，需结合现场蹲点、租约谈判等综合判断。

**Q：报告能保存多久？**  
本地部署时保存在 `output/` 目录；Vercel 部署时为临时存储，建议生成后立即下载 Word / PNG。

---

## 许可证

本项目代码公开于 GitHub。使用高德 API 须遵守[高德开放平台服务条款](https://lbs.amap.com/home/terms/)，API 调用产生的费用由 Key 持有者承担。
