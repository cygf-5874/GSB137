"""cmsketch —— Count-Min Sketch 计数草图（仅标准库）。

支持普通累加与保守更新（conservative update）、同形草图逐格合并、
确定性的二进制序列化，以及按估计降序的 top-k 查询。所有行为只依赖
确定性的 BLAKE2b 派生哈希，不使用随机源、墙钟或容器迭代顺序。
"""

import hashlib
import struct


_MAGIC = b"CMS1"
_HEADER = struct.Struct(">4sHHqB")
_KEY_HEAD = struct.Struct(">BH")
_U64 = struct.Struct(">Q")

_KIND_BYTES = 0
_KIND_STR = 1
_KIND_OTHER = 2


def _key_bytes(key):
    if isinstance(key, bytes):
        return key
    if isinstance(key, str):
        return key.encode("utf-8")
    return str(key).encode("utf-8")


def _key_kind(key):
    if isinstance(key, str):
        return _KIND_STR
    if isinstance(key, bytes):
        return _KIND_BYTES
    return _KIND_OTHER


def _key_from_bytes(kb, kind):
    if kind == _KIND_BYTES:
        return bytes(kb)
    # _KIND_STR 还原为 str；_KIND_OTHER 以其 str(key) 的 UTF-8 形式还原。
    return kb.decode("utf-8")


def _is_int(value):
    # 显式排除 bool：bool 虽是 int 子类，但宽深/计数语义上不应接受。
    return isinstance(value, int) and not isinstance(value, bool)


class CountMinSketch:
    """固定宽深的计数草图：``width`` 列、``depth`` 行，``seed`` 决定哈希。

    ``conservative`` 为 ``True`` 时，:meth:`add` 只抬升当前取得最小估计的
    那些计数器，使估计不劣于普通更新且仍不低于真实计数。
    """

    def __init__(self, width, depth, seed=0, conservative=False):
        if not _is_int(width) or not _is_int(depth):
            raise ValueError("width/depth 必须是整数")
        if width <= 0 or depth <= 0:
            raise ValueError("width/depth 必须为正")
        if not _is_int(seed):
            raise ValueError("seed 必须是整数")
        if not isinstance(conservative, bool):
            raise ValueError("conservative 必须是布尔值")
        self.width = width
        self.depth = depth
        self.seed = seed
        self.conservative = conservative
        self._rows = [[0] * width for _ in range(depth)]
        # key 的 UTF-8 字节 -> (类型标志, 原始 key)；字节序即排序键。
        self._keys = {}

    def _index(self, key, row):
        payload = (str(self.seed) + "|" + str(row) + "|").encode("ascii") + _key_bytes(key)
        digest = hashlib.blake2b(payload, digest_size=8).digest()
        return int.from_bytes(digest, "big") % self.width

    def _indices(self, key):
        return [self._index(key, row) for row in range(self.depth)]

    def add(self, key, count=1):
        """把 ``key`` 累加 ``count`` 次（``count >= 0``），返回自身。"""
        if not _is_int(count) or count < 0:
            raise ValueError("count 必须是非负整数")
        kb = _key_bytes(key)
        if kb not in self._keys:
            self._keys[kb] = (_key_kind(key), key)
        if count == 0:
            return self
        indices = self._indices(key)
        if self.conservative:
            current = min(self._rows[row][indices[row]] for row in range(self.depth))
            target = current + count
            for row, col in enumerate(indices):
                cell = self._rows[row][col]
                if cell == current:
                    self._rows[row][col] = target
                elif cell < target:
                    # 兜底分支：current 本就是最小值，正常情况下不会走到。
                    self._rows[row][col] = target
        else:
            for row, col in enumerate(indices):
                self._rows[row][col] += count
        return self

    def estimate(self, key):
        """返回 ``key`` 的估计计数（不小于真实计数）。"""
        indices = self._indices(key)
        return min(self._rows[row][indices[row]] for row in range(self.depth))

    def merge(self, other):
        """把另一张同形草图逐格并入自身，返回自身。

        ``width``/``depth`` 必须一致，否则抛 :class:`ValueError` 且自身不变。
        合并是逐格求和，因此满足交换律与结合律；空草图参与合并等于另一侧。
        """
        if not isinstance(other, CountMinSketch):
            raise ValueError("只能合并 CountMinSketch 实例")
        if other.width != self.width or other.depth != self.depth:
            raise ValueError("width/depth 与自身不一致，无法合并")
        for row in range(self.depth):
            target = self._rows[row]
            source = other._rows[row]
            for col in range(self.width):
                target[col] += source[col]
        for kb, entry in other._keys.items():
            if kb not in self._keys:
                self._keys[kb] = entry
        return self

    def topk(self, k):
        """返回最重的至多 ``k`` 个 ``(key, estimate)``。

        按估计降序；估计相同按 key 的 UTF-8 字节序升序。``k`` 大于已见
        key 数时返回全部；``k`` 非正时返回空列表。
        """
        if not _is_int(k):
            raise ValueError("k 必须是整数")
        if k <= 0:
            return []
        scored = [
            (entry[1], self.estimate(entry[1]), kb)
            for kb, entry in self._keys.items()
        ]
        scored.sort(key=lambda item: (-item[1], item[2]))
        return [(key, score) for key, score, _kb in scored[:k]]

    def serialize(self):
        """返回确定性的 ``bytes`` 表示；同一状态两次调用逐字节相同。"""
        parts = [_HEADER.pack(
            _MAGIC, self.width, self.depth, self.seed, 1 if self.conservative else 0
        )]
        parts.append(_U64.pack(len(self._keys)))
        for kb in sorted(self._keys):
            kind, key = self._keys[kb]
            payload = _key_bytes(key)
            parts.append(_KEY_HEAD.pack(kind, len(payload)))
            parts.append(payload)
        for row in range(self.depth):
            for col in range(self.width):
                parts.append(_U64.pack(self._rows[row][col]))
        return b"".join(parts)

    @staticmethod
    def deserialize(data):
        """从 :meth:`serialize` 的字节还原草图（含全部计数器与 key 集合）。"""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise ValueError("序列化数据必须是 bytes")
        data = bytes(data)
        if len(data) < _HEADER.size:
            raise ValueError("数据过短，缺少头部")
        magic, width, depth, seed, flag = _HEADER.unpack_from(data, 0)
        if magic != _MAGIC:
            raise ValueError("魔数或版本不匹配")
        if flag not in (0, 1):
            raise ValueError("conservative 标志非法")
        if width <= 0 or depth <= 0 or not _is_int(seed):
            raise ValueError("width/depth/seed 非法")
        offset = _HEADER.size
        if offset + 8 > len(data):
            raise ValueError("数据截断：缺少 key 计数")
        (key_count,) = _U64.unpack_from(data, offset)
        offset += 8
        sketch = CountMinSketch(width, depth, seed=seed, conservative=bool(flag))
        for _ in range(key_count):
            if offset + _KEY_HEAD.size > len(data):
                raise ValueError("数据截断：缺少 key 头部")
            kind, klen = _KEY_HEAD.unpack_from(data, offset)
            offset += _KEY_HEAD.size
            if kind not in (_KIND_BYTES, _KIND_STR, _KIND_OTHER):
                raise ValueError("key 类型标志非法")
            if offset + klen > len(data):
                raise ValueError("数据截断：缺少 key 内容")
            kb = data[offset:offset + klen]
            offset += klen
            try:
                restored = _key_from_bytes(kb, kind)
            except UnicodeDecodeError:
                raise ValueError("文本 key 不是合法 UTF-8")
            sketch._keys[kb] = (kind, restored)
        cell_size = _U64.size
        needed = offset + width * depth * cell_size
        if len(data) != needed:
            raise ValueError("计数器区长度与 width/depth 不符")
        row_fmt = ">%dQ" % width
        for row in range(depth):
            base = offset + row * width * cell_size
            sketch._rows[row] = list(struct.unpack_from(row_fmt, data, base))
        return sketch
