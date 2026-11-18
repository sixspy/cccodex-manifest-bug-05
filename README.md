# cc-manifest-lab

CC_Codex 二期（26.11）**数据工程**产品线：**湖区落地清单台**（Litestar + Preact CDN + SQLite）。

## 一句话骨架（自有，非外仓抄题）

**湖区落地批次 → 对象指纹登记 → 清单闭合 → 可见性对账**

与现有七线正交（不是采集目录、ETL 管道、同步源、解析入库、编排流、种子摄取、留存裁撤）。
不碰外仓常见指纹（Feed 归并 / CDC 游标 / 质检签发 / Slicegate 类仓名）。

## 领域

- **所属领域**：数据工程
- **子方向**：数仓与数据湖（落地清单 / 对象登记闭环）

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | Python 3.12、Litestar、Uvicorn、SQLite |
| 前端 | 原生 JS SPA（全中文，侧栏），靛青竖纹 + 亮青强调；不依赖外网 CDN |
| 测试 | pytest + httpx（本地秒级闭环，优先于 compose） |

## 基线已通主链

1. 湖区落地批次列表（收集中 / 已闭合）
2. 向批次登记对象键与内容指纹
3. 闭合清单（对象数固化，拒绝空批）
4. 可见性对账报告（闭合批 vs 开放批 vs 孤儿对象）

## 闭合计数口径（唯一选边）

**提交瞬间现场重数（`live_recount_at_submit`）**。点闭合时，服务在 `BEGIN IMMEDIATE`
写锁内重新统计本批 `status='已登记'` 的对象数，校验与固化数都使用这一次重数结果；
不使用“打开面板时冻结的快照”参与校验，两套计数不混用。

- 门槛：至少 **1** 个实有对象（`CLOSE_MIN_OBJECTS`）。
- 空批即停：现场重数 < 门槛直接 400 拒收，批次保持「收集中」，不留「已闭合」。
- 拦截留痕：每次尝试写入 `close_attempts`（对象数、门槛、口径、通过/拦截、原因），
  空批面板、收集列表、解析验收台与本机库四处可核。
- 并发：两侧同时点闭合时由 `BEGIN IMMEDIATE` 串行化，后者读到已提交状态并返回 409，
  不会双成功留下空的「已闭合」。

## 解析任务拉清单

`POST /api/batches/{id}/manifest-pull`：仅已闭合且清单非空的批次可拉取。

| 情况 | HTTP | 代码 |
|------|------|------|
| 批次未闭合 | 409 | `batch_not_closed` |
| 已闭合但清单为 0 个对象 | 422 | `empty_manifest` |
| 固化数 ≠ 实有清单数 | 409 | `manifest_mismatch` |

拒收与接收都会写入 `manifest_pulls`，在解析验收台可见。

## 四处同查

- 空批面板：批次详情页，实有对象 / 门槛 / 口径与最近拦截记录。
- 收集列表：每行「对象 / 门槛」与闭合判定芯片（可闭合 / 拦截 / 已闭合 / 空清单拦截）。
- 对象进度：详情页进度条与「实有 N / 门槛 M」。
- 解析验收台：全批次门槛核对 + 空批拦截统计 + 空已闭合异常 + 拉清单记录。

预留切口（未做，供后续功能题）：清单换版生效窗、闭合作废回开放、批量失败闭互斥、跨区依赖冻结、清单回灌等。

## 本地（推荐反馈环）

```powershell
cd claude-workspace\cc-manifest-lab
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
python run.py
```

http://127.0.0.1:6900/login · **admin / 123456**

## Docker

```powershell
docker compose up -d --build
```

端口 **6900**。冒烟：`python ..\scripts\_smoke_lab_access.py --dir .`
