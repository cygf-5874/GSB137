#!/usr/bin/env python3
"""cmsketch 固定验收程序（固定件）。

用法（在仓库根目录）：
  python check/check.py            跑全部场景
  python check/check.py -list      列出全部 `组/名`
  python check/check.py --only <组> 只跑某一组

输出：逐场景 `PASS <组>/<名>` 或 `FAIL <组>/<名>  期望=… 实际=…`，
结尾 `结果：通过 x/N`；全过 exit 0，否则 exit 1；失败不早退。
判据只描述对外可见性质（估计值、排序、往返），不使用墙钟 / 随机源，
也不假设哈希函数的具体形式（只用「同一 seed 下同一 key 得到同一格」这一确定性）。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, os.pardir, "src"))

from cmsketch import CountMinSketch  # noqa: E402


def key_bytes(key):
    return key.encode("utf-8") if isinstance(key, str) else bytes(key)


def show(value):
    text = repr(value)
    return text if len(text) <= 220 else text[:220] + "…"


def expect_equal(expected, actual, label):
    if expected != actual:
        raise AssertionError("%s：期望=%s 实际=%s" % (label, show(expected), show(actual)))


def expect_true(cond, label, actual):
    if not cond:
        raise AssertionError("%s：实际=%s" % (label, show(actual)))


def make(width, depth, seed, conservative=None):
    if conservative is None:
        return CountMinSketch(width, depth, seed=seed)
    return CountMinSketch(width, depth, seed=seed, conservative=conservative)


def build(width, depth, seed, stream, conservative=None):
    cms = make(width, depth, seed, conservative)
    for key, count in stream:
        cms.add(key, count)
    return cms


def estimates(cms, keys):
    return {k: cms.estimate(k) for k in keys}


STREAM_A = [("alpha", 4), ("beta", 9), ("gamma", 1), ("alpha", 3)]
STREAM_B = [("beta", 2), ("delta", 6), ("gamma", 5)]
STREAM_C = [("alpha", 1), ("epsilon", 8)]
KEYS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]


def sc_legacy_exact():
    cms = make(64, 4, seed=7)
    cms.add("only", 5)
    expect_equal(5, cms.estimate("only"), "单 key 精确")
    expect_equal(0, cms.estimate("absent"), "未加入 key 估计为 0")

    cms2 = make(64, 4, seed=7)
    cms2.add("k")
    expect_equal(1, cms2.estimate("k"), "默认计数 1")


def sc_legacy_bound():
    cms = build(64, 5, seed=11, stream=STREAM_A)
    truth = {"alpha": 7, "beta": 9, "gamma": 1}
    for key, want in truth.items():
        expect_true(cms.estimate(key) >= want, "上界 %s >= %d" % (key, want), cms.estimate(key))

    before = cms.estimate("alpha")
    cms.add("alpha", 2)
    after = cms.estimate("alpha")
    expect_true(after >= before, "add 后估计单调不减", (before, after))

    narrow = build(2, 2, seed=5, stream=[("k%d" % i, i + 1) for i in range(20)])
    for i in range(20):
        expect_true(narrow.estimate("k%d" % i) >= i + 1,
                    "窄草图仍满足上界 k%d" % i, narrow.estimate("k%d" % i))


def sc_merge_sum():
    a = build(48, 4, seed=3, stream=STREAM_A)
    b = build(48, 4, seed=3, stream=STREAM_B)
    merged = a.merge(b)
    reference = build(48, 4, seed=3, stream=STREAM_A + STREAM_B)
    expect_equal(estimates(reference, KEYS), estimates(merged, KEYS),
                 "merge 等价于按顺序逐条 add")
    expect_true(merged is a, "merge 返回自身", merged)


def sc_merge_algebra():
    def fresh(stream, conservative=None):
        return build(48, 4, seed=3, stream=stream, conservative=conservative)

    expect_equal(estimates(fresh(STREAM_A).merge(fresh(STREAM_B)), KEYS),
                 estimates(fresh(STREAM_B).merge(fresh(STREAM_A)), KEYS), "merge 交换律")

    left = fresh(STREAM_A).merge(fresh(STREAM_B)).merge(fresh(STREAM_C))
    right = fresh(STREAM_A).merge(fresh(STREAM_B).merge(fresh(STREAM_C)))
    expect_equal(estimates(left, KEYS), estimates(right, KEYS), "merge 结合律")

    empty = make(48, 4, seed=3)
    expect_equal(estimates(fresh(STREAM_A), KEYS), estimates(make(48, 4, seed=3).merge(fresh(STREAM_A)), KEYS),
                 "空 sketch 在左侧")
    expect_equal(estimates(fresh(STREAM_A), KEYS), estimates(fresh(STREAM_A).merge(empty), KEYS),
                 "空 sketch 在右侧")


def sc_merge_mismatch():
    a = build(16, 3, seed=1, stream=STREAM_A)
    before = estimates(a, KEYS)
    for bad in (make(16, 4, seed=1), make(17, 3, seed=1)):
        try:
            a.merge(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("宽深不一致时 merge 必须抛 ValueError")
    expect_equal(before, estimates(a, KEYS), "失败的 merge 不得改动自身")


def sc_upper_both_modes():
    truth = {"alpha": 7, "beta": 9, "gamma": 1, "delta": 6, "epsilon": 8}
    for mode in (False, True):
        cms = build(32, 4, seed=13, stream=STREAM_A + STREAM_B + STREAM_C, conservative=mode)
        for key, want in truth.items():
            expect_true(cms.estimate(key) >= want,
                        "conservative=%s 上界 %s>=%d" % (mode, key, want), cms.estimate(key))


def sc_upper_tighter():
    truth = {"alpha": 8, "beta": 11, "gamma": 6, "delta": 6, "epsilon": 8}
    stream = STREAM_A + STREAM_B + STREAM_C
    plain = build(32, 4, seed=21, stream=stream, conservative=False)
    cons = build(32, 4, seed=21, stream=stream, conservative=True)
    for key in truth:
        c = cons.estimate(key)
        p = plain.estimate(key)
        expect_true(c >= truth[key], "保守更新仍满足上界 %s" % key, c)
        expect_true(c <= p, "保守更新不劣于普通更新 %s" % key, (c, p))


def sc_roundtrip():
    a = build(32, 4, seed=17, stream=STREAM_A + STREAM_B)
    data = a.serialize()
    expect_true(isinstance(data, (bytes, bytearray)), "serialize 返回 bytes", type(data).__name__)
    expect_equal(bytes(data), bytes(a.serialize()), "serialize 两次逐字节相同")

    b = CountMinSketch.deserialize(data)
    expect_equal(a.width, b.width, "宽还原")
    expect_equal(a.depth, b.depth, "深还原")
    expect_equal(a.seed, b.seed, "seed 还原")
    expect_equal(bytes(data), bytes(b.serialize()), "往返后 serialize 逐字节相同")
    expect_equal(estimates(a, KEYS), estimates(b, KEYS), "往返后估计相同")
    expect_equal(a.topk(4), b.topk(4), "往返后 top-k 相同")

    cons = build(32, 4, seed=17, stream=STREAM_A, conservative=True)
    cdata = cons.serialize()
    back = CountMinSketch.deserialize(cdata)
    expect_equal(estimates(cons, KEYS), estimates(back, KEYS), "保守草图往返后估计相同")


def sc_topk():
    heavy = make(1000, 5, seed=3)
    heavy.add("heavy", 100)
    expect_equal([("heavy", 100)], heavy.topk(3), "单一重元素 top-1")

    tied = make(1, 1, seed=0)
    for key in ("b", "a", "c"):
        tied.add(key)
    expect_equal([("a", 3), ("b", 3), ("c", 3)], tied.topk(10), "并列按 key 字节序")
    expect_equal([("a", 3), ("b", 3)], tied.topk(2), "top-k 截断")

    cms = build(64, 4, seed=5, stream=STREAM_A + STREAM_B + STREAM_C)
    res = cms.topk(5)
    expect_equal(5, len(res), "top-k 长度")
    order = [(-est, key_bytes(key)) for key, est in res]
    expect_equal(sorted(order), order, "估计降序、并列按 key 字节序")
    expect_equal(res, cms.topk(5), "top-k 确定性")

    full = build(64, 4, seed=5, stream=STREAM_A + STREAM_B + STREAM_C)
    expect_equal(5, len(full.topk(100)), "k 大于 key 数时返回全部 key")


SCENARIOS = [
    ("legacy", "exact-fresh-sketch", "既有 add/estimate 精确与默认计数", sc_legacy_exact),
    ("legacy", "monotone-and-bound", "既有累加单调不减且满足上界", sc_legacy_bound),
    ("merge", "sum-equivalence", "merge 等价于逐条 add", sc_merge_sum),
    ("merge", "algebra", "merge 交换/结合/空元", sc_merge_algebra),
    ("merge", "shape-mismatch", "宽深不一致抛 ValueError", sc_merge_mismatch),
    ("upper", "both-modes", "两种更新模式都满足上界", sc_upper_both_modes),
    ("upper", "conservative-tighter", "保守更新不劣于普通更新", sc_upper_tighter),
    ("roundtrip", "serialize-deserialize", "序列化往返确定", sc_roundtrip),
    ("topk", "order", "top-k 排序稳定", sc_topk),
]


def main(argv):
    list_only = "-list" in argv or "--list" in argv
    only = None
    if "--only" in argv:
        idx = argv.index("--only")
        if idx + 1 >= len(argv):
            sys.stderr.write("--only 缺少取值\n")
            return 2
        only = argv[idx + 1]

    if list_only:
        for group, name, _expect, _run in SCENARIOS:
            sys.stdout.write("%s/%s\n" % (group, name))
        return 0

    passed = 0
    ran = 0
    for group, name, expect, run in SCENARIOS:
        if only is not None and group != only:
            continue
        ran += 1
        label = "%s/%s" % (group, name)
        try:
            run()
            passed += 1
            sys.stdout.write("PASS %s\n" % label)
        except Exception as exc:  # noqa: BLE001
            detail = "%s: %s" % (type(exc).__name__, exc)
            sys.stdout.write("FAIL %s  期望=%s 实际=%s\n" % (label, expect, show(detail)))

    if ran == 0:
        sys.stdout.write("结果：通过 0/0（没有匹配的场景：--only %s）\n" % only)
        return 1

    sys.stdout.write("结果：通过 %d/%d\n" % (passed, ran))
    return 0 if passed == ran else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))