# cc-watermark-lab

CC_Codex 二期（26.11）**数据工程**产品线：**血缘水印台**（BlackSheep + Alpine CDN + SQLite）。

## 一句话骨架（自有，非外仓抄题）

**产出表水印模板 → 批次盖印 → 下游追索 → 缺口对账**

与现有七线正交（不是采集目录、ETL 管道、同步源、解析入库、编排流、种子摄取、留存裁撤）。
不碰外仓常见指纹（Feed 归并 / CDC 游标 / 质检签发 / Slicegate 类仓名）。

## 领域

- **所属领域**：数据工程
- **子方向**：数据血缘与水印（产出表盖印 / 追索闭环）

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | Python 3.12、BlackSheep、Uvicorn、SQLite |
| 前端 | 原生 JS SPA（全中文，底栏），雾灰底 + 青柠强调；不依赖外网 CDN |
| 测试 | pytest + httpx（本地秒级闭环，优先于 compose） |

## 基线已通主链

1. 产出表水印模板（表名 / 列名 / 现行版本）
2. 向运行批次盖印水印值
3. 按水印值追索下游批次
4. 缺口对账（已盖印 vs 应盖印）

## 齐检闸口（watermark-bug-15 修复）

**下游表放行必须过齐检门槛**：本批与顺藤全部上游批次的印记值齐备才生成齐检凭证，
凭证落库才允许放行。缺印、断链一律 `409` 拦在库外，不再静默放行。

- **齐检凭证唯一来源**：`app/gates/qi_check_gate.json`（不可变门槛文件），
  文件摘要钉死在 `app/services/gate.py`，改动即 `503` 停止放行。
- **旧门槛只读**：原“无齐检直接放行”门槛迁入 `app/gates/history/`，
  旧 `meta.released_*` 放行态在迁移时进入只读历史表并从现行数据清除。
- **同源口径**：齐印统计、放行动作、下游表附页、放行进度全部走
  `app/services/qi.py`，页面四处（闸口目录 / 印记值卡片 / 下游表附页 / 放行进度）同看。
- **排他写锁**：放行使用 `BEGIN IMMEDIATE`，两侧仓管同时点放行只有一个成功。
- **立即停止**：检测到“缺印已放行”记录时，放行动作整体 `503` 停止；
  顺藤复验会拦下这类记录（`withheld`），不再读到。

复现与二次验收步骤见 [`docs/复现步骤-齐检放行.md`](docs/复现步骤-齐检放行.md)。

预留切口（未做，供后续功能题）：模板换版生效窗、盖印作废回灌、批量盖印互斥、跨表依赖冻结、追索深度限制等。

## 本地（推荐反馈环）

```powershell
cd claude-workspace\cc-watermark-lab
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
python run.py
```

http://127.0.0.1:7000/login · **admin / 123456**

## Docker

```powershell
docker compose up -d --build
```

端口 **7000**。冒烟：`python ..\scripts\_smoke_lab_access.py --dir .`
