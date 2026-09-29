# cmsketch

Python 3 的 **Count-Min Sketch** 计数草图库。既有实现只支持单机累加与估计；
本次要在它上面补齐**合并、保守更新、序列化、top-k**。

- 语言/依赖：Python 3（标准库，`unittest`），**无第三方依赖**。
- 入口：`src/cmsketch.py`。
- 自检：`bash scripts/check.sh`（`check/` 是固定验收程序，**勿改**）。
- 既有用例：`python tests/run.py`（unittest，当前全绿）。

## 用法

```bash
python tests/run.py                 # 既有用例
bash scripts/check.sh               # 固定验收（加 -list / --only <组名> 可过滤）
```

目标对外接口（既有部分已在 `src/cmsketch.py` 里；**本次要补**的部分当前未实现）：

- 既有：`CountMinSketch(width, depth, seed=0)`、`add(key, count=1) -> self`、`estimate(key) -> int`
- 本次要补：`CountMinSketch(width, depth, seed=0, conservative=False)`、`merge(other) -> self`、
  `topk(k) -> list[tuple[key, int]]`、`serialize() -> bytes`、`CountMinSketch.deserialize(data) -> CountMinSketch`

## 本次要补的一层

1. 构造参数 `conservative`：为 `True` 时 `add` 走**保守更新**。
2. `merge(other)`：把另一张同形草图的计数逐格并入自身。
3. `serialize()` / `deserialize(data)`：确定性的字节序列化与还原。
4. `topk(k)`：返回重量级元素。

## 对外契约

1. 既有 `add` / `estimate` 行为**不得回归**：`estimate` 只对加入过的 key 有意义且 ≥ 真实计数；
   新草图里未加入过的 key 估计为 `0`；`add` 返回自身。
2. `merge(other)` **逐格求和**并返回自身；`width` 或 `depth` 与自身不一致时抛 `ValueError`，
   且此时不得改动自身。`merge` 满足**交换律**与**结合律**。
3. `conservative=True` 时 `add` 走保守更新：只把当前处于最小值那一档的计数器抬到
   `estimate(key) + count`；**不得破坏上界性质**（估计仍 ≥ 真实计数），且估计值**不劣于**
   普通更新（≤ 普通更新的估计）。
4. `serialize()` 返回 `bytes`：同一张草图连续两次调用**逐字节相同**；
   `deserialize(data)` 还原出 `width`/`depth`/`seed` 与全部计数器，往返后 `serialize()` **逐字节相同**，
   且 `estimate` / `topk` 结果一致。
5. 哈希**确定**：同一 `seed` 下同一 key 永远落到同一格；结果**不得**依赖 `dict`/`set` 迭代顺序，
   也不得依赖随机源。序列化里的 key 列表按 **key 的 UTF-8 字节序**排列。
6. 对某个 key 连续 `add`，其 `estimate` **单调不减**；任意时刻 `estimate(key) >= 真实计数`。
7. `topk(k)` 只统计已经 `add` 过的 key，返回 `(key, estimate)` 列表：按估计**降序**，
   并列时按 key 的 **UTF-8 字节序升序**；`k` 大于已见 key 数时返回全部 key（不报错）。
8. **空草图参与 `merge` 等于另一侧**（左并入空、空并入右，结果都与非空那一侧一致）。
9. `merge` 之后的上层 API（`estimate`、`topk`）与「按同样顺序逐条 `add` 两份输入」**等价**。

## 目录

```
src/cmsketch.py     库代码（既有 add/estimate 已实现；本次要补的部分当前未实现）
tests/run.py        既有用例（unittest，全绿）
check/check.py      固定验收程序（9 个场景，勿改）
scripts/check.sh    自检入口
```