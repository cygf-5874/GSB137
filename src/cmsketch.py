"""cmsketch —— Count-Min Sketch 计数草图（仅标准库）。

当前实现只支持「单机累加 + 估计」；合并、保守更新（conservative update）、
序列化与 top-k 属于**本次要补的一层**（见 README）。
"""

import hashlib


def _key_bytes(key):
    if isinstance(key, bytes):
        return key
    if isinstance(key, str):
        return key.encode("utf-8")
    return str(key).encode("utf-8")


class CountMinSketch:
    """固定宽深的计数草图：``width`` 列、``depth`` 行，``seed`` 决定哈希。"""

    def __init__(self, width, depth, seed=0):
        if not isinstance(width, int) or not isinstance(depth, int):
            raise ValueError("width/depth 必须是整数")
        if width <= 0 or depth <= 0:
            raise ValueError("width/depth 必须为正")
        if not isinstance(seed, int):
            raise ValueError("seed 必须是整数")
        self.width = width
        self.depth = depth
        self.seed = seed
        self._rows = [[0] * width for _ in range(depth)]
        self._keys = set()

    def _index(self, key, row):
        payload = (str(self.seed) + "|" + str(row) + "|").encode("ascii") + _key_bytes(key)
        digest = hashlib.blake2b(payload, digest_size=8).digest()
        return int.from_bytes(digest, "big") % self.width

    def add(self, key, count=1):
        """把 ``key`` 累加 ``count`` 次（``count >= 0``），返回自身。"""
        if not isinstance(count, int) or count < 0:
            raise ValueError("count 必须是非负整数")
        self._keys.add(key)
        for row in range(self.depth):
            self._rows[row][self._index(key, row)] += count
        return self

    def estimate(self, key):
        """返回 ``key`` 的估计计数（不小于真实计数）。"""
        return min(self._rows[row][self._index(key, row)] for row in range(self.depth))

    # ------------------------------------------------------------------
    # 以下属于本次要补的一层，当前尚未实现。
    # ------------------------------------------------------------------

    def merge(self, other):
        raise NotImplementedError

    def topk(self, k):
        raise NotImplementedError

    def serialize(self):
        raise NotImplementedError

    @staticmethod
    def deserialize(data):
        raise NotImplementedError