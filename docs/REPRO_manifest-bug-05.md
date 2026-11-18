# 复现说明：空对象收集批也能点闭合（manifest-bug-05）

## 现象（修复前）

- 零对象批次点「闭合清单」返回 200，`ok: true`，`object_count: 0`。
- 批次被置为「已闭合」，`closed_object_count = 0`，`close_runs` 落一条 0 对象记录。
- 前端提示「清单已闭合」，不显示任何拦截原因。
- 两侧调度同时点闭合时，无写锁，两次都可能成功（双成功），留下空的「已闭合」。

## 根因

1. `app/services/close.py`：统计出 `n` 后没有门槛校验，直接 UPDATE 状态并固化为 `n`。
2. `app/db.py`：`get_db()` 未取写锁，check-then-write 非原子；两侧调度可同时读到「收集中」。
3. `app/main.py`：闭合接口即使失败也没有可展示的计数值/原因字段，解析任务无拉清单接口。
4. 前端：空批面板、对象进度、收集列表判定、解析验收台均不存在，只有一句「清单已闭合」。

## 复现（修复前基线）

```bash
pytest tests/test_main_chain.py::test_empty_batch_cannot_close
# FAILED: assert 200 == 400  ← 空批返回 200，闭合成功
```

或起服务后：

```bash
curl -b cookie -X POST http://127.0.0.1:6900/api/batches/2/close -d '{}' -H 'Content-Type: application/json'
# {"ok":true,"run":{...,"object_count":0}}   ← 空批闭合成功
```

## 修复后验证

### 口径与门槛

- 唯一口径：**提交瞬间现场重数**（`live_recount_at_submit`）。
- 门槛：实有对象 ≥ 1。
- 校验与固化数来自同一把 `BEGIN IMMEDIATE` 写锁内的同一次重数。

### 服务端

```bash
# 1) 空批闭合 → 400，回白话 + 计数值
curl -b cookie -X POST http://127.0.0.1:7190/api/batches/2/close -d '{}' -H 'Content-Type: application/json'
# {"ok":false,"error":"空批不能闭合：本批实有对象 0 个，门槛要求至少 1 个（口径：提交瞬间现场重数）。",
#  "code":"empty_batch","object_count":0,"threshold":1,"count_mode":"live_recount_at_submit","chip":"拦截"}

# 2) 本机库核拦截记录
sqlite3 instance/manifest_lab.db \
  "SELECT batch_id,object_count,threshold,count_mode,accepted,code FROM close_attempts ORDER BY id DESC LIMIT 3;"

# 3) 确认没有留下空已闭合
sqlite3 instance/manifest_lab.db \
  "SELECT id,status,closed_object_count FROM landing_batches WHERE id=2;"   # 收集中|空

# 4) 解析任务拉清单 → 未闭合 409 / 空清单 422
curl -b cookie -X POST http://127.0.0.1:7190/api/batches/2/manifest-pull -d '{}' -H 'Content-Type: application/json'
# {"ok":false,"error":"批次未闭合，解析任务拒收空清单。","code":"batch_not_closed"}
```

### 四处界面

打开批次 2（支付铜区，空批）：

1. **空批面板**（详情页）：红色「空批拦截」芯片、实有对象 0 / 门槛 1、口径、最近拦截记录。
2. **收集列表**：该行「对象 / 门槛」显示 `0 / 1`，判定列显示「拦截」及原因。
3. **对象进度**：进度条为 0%，文案「实有对象 0 / 门槛 1 · 低于门槛」。
4. **解析验收台**：门槛、计数口径、空批（收集中需拦截）计数、该批「拦截」芯片与最近拦截代码；
   拉清单记录里能看到 `empty_manifest` / `batch_not_closed` 拒收。

### 并发

```bash
pytest tests/test_empty_close.py -k concurrent
```

- 空批两侧同时闭合：两次都返回 `empty_batch`，批次仍「收集中」，`close_runs` 0 条。
- 非空批两侧同时闭合：恰好一次 `ok`、一次 `already_closed`，`close_runs` 1 条。

### 全量

```bash
pytest
# 15 passed
```

## 涉及文件

- `app/services/policy.py`（新增）：口径常量、门槛、判定与芯片。
- `app/services/close.py`：写锁内重数 + 门槛 + 留痕。
- `app/services/batches.py`：列表/详情补现场计数、判定、最近拦截。
- `app/services/manifests.py`（新增）：解析任务拉清单，空清单拒收。
- `app/services/visibility.py`：验收台数据、空已闭合统计。
- `app/db.py`：`BEGIN IMMEDIATE`、`close_attempts` / `manifest_pulls` 表、老库补列。
- `app/main.py`：闭合错误回结构化 payload；新增拉清单/验收台/拦截记录接口。
- `static/js/app.js`、`static/css/manifest.css`、`static/index.html`：四处界面。
- `tests/test_empty_close.py`（新增）：门槛、留痕、拒收、并发、迁移。
