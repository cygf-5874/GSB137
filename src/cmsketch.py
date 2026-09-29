"""cmsketch —— Count-Min Sketch 计数草图（仅标准库）。

支持普通累加 / 保守更新（conservative update）、逐格合并（merge）、
确定性字节序列化（serialize/deserialize）与 top-k。
"""

import hashlib

FORMAT_VERSION = 1
_MAGIC = b"CMSK"
_TAG_STR = 0
_TAG_BYTES = 1
_FLAG_CONSERVATIVE = 1


def _key_bytes(key):
    if isinstance(key, bytes):
        return key
    if isinstance(key, str):
        return key.encode("utf-8")
    return str(key).encode("utf-8")


def _uvarint_encode(value):
    parts = bytearray()
    while value >= 0x80:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value)
    return bytes(parts)


def _svarint_encode(value):
    return _uvarint_encode((value << 1) ^ (value >> 63))


class CountMinSketch:
    """固定宽深的计数草图：``width`` 列、``depth`` 行，``seed`` 决定哈希。"""

    FORMAT_VERSION = FORMAT_VERSION

    def __init__(self, width, depth, seed=0, conservative=False):
        if not isinstance(width, int) or isinstance(width, bool):
            raise ValueError("width/depth 必须是整数")
        if not isinstance(depth, int) or isinstance(depth, bool):
            raise ValueError("width/depth 必须是整数")
        if width <= 0 or depth <= 0:
            raise ValueError("width/depth 必须为正")
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ValueError("seed 必须是整数")
        if not isinstance(conservative, bool):
            raise ValueError("conservative 必须是布尔值")
        self.width = width
        self.depth = depth
        self.seed = seed
        self.conservative = conservative
        self._rows = [[0] * width for _ in range(depth)]
        self._keys = set()

    def _index(self, key, row):
        payload = (str(self.seed) + "|" + str(row) + "|").encode("ascii") + _key_bytes(key)
        digest = hashlib.blake2b(payload, digest_size=8).digest()
        return int.from_bytes(digest, "big") % self.width

    def add(self, key, count=1):
        """把 ``key`` 累加 ``count`` 次（``count >= 0``），返回自身。"""
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("count 必须是非负整数")
        self._keys.add(key)
        if self.conservative:
            values = [self._rows[row][self._index(key, row)] for row in range(self.depth)]
            target = min(values) + count
            for row, current in enumerate(values):
                if current < target:
                    self._rows[row][self._index(key, row)] = target
        else:
            for row in range(self.depth):
                self._rows[row][self._index(key, row)] += count
        return self

    def estimate(self, key):
        """返回 ``key`` 的估计计数（不小于真实计数）。"""
        return min(self._rows[row][self._index(key, row)] for row in range(self.depth))

    def merge(self, other):
        """把同形草图 ``other`` 逐格并入自身，返回自身。

        ``width`` / ``depth``（或内部版本）不一致时抛 ``ValueError``，
        且自身不发生任何改动。合并满足交换律、结合律，空草图为单位元。
        """
        if not isinstance(other, CountMinSketch):
            raise TypeError("merge 对象必须是 CountMinSketch")
        if getattr(other, "FORMAT_VERSION", None) != FORMAT_VERSION:
            raise ValueError("merge 对象版本不兼容")
        if other.width != self.width or other.depth != self.depth:
            raise ValueError("merge 对象的 width/depth 必须与自身一致")
        for row in range(self.depth):
            own = self._rows[row]
            theirs = other._rows[row]
            for col in range(self.width):
                own[col] += theirs[col]
        self._keys.update(other._keys)
        return self

    def topk(self, k):
        """返回已加入 key 的 ``(key, estimate)`` 列表。

        按估计降序；估计并列时按 key 的 UTF-8 字节序升序。
        ``k`` 大于已见 key 数时返回全部 key。
        """
        if not isinstance(k, int) or isinstance(k, bool) or k < 0:
            raise ValueError("k 必须是非负整数")
        items = [(key, self.estimate(key)) for key in self._keys]
        items.sort(key=lambda item: (-item[1], _key_bytes(item[0])))
        return items[:k]

    def _encode_key(self, key):
        if isinstance(key, bytes):
            return _TAG_BYTES, key
        if isinstance(key, str):
            return _TAG_STR, key.encode("utf-8")
        return _TAG_STR, str(key).encode("utf-8")

    def serialize(self):
        """返回确定性的字节表示；同一草图两次调用逐字节相同。"""
        parts = [_MAGIC, bytes([FORMAT_VERSION])]
        flags = _FLAG_CONSERVATIVE if self.conservative else 0
        parts.append(bytes([flags]))
        parts.append(_uvarint_encode(self.width))
        parts.append(_uvarint_encode(self.depth))
        parts.append(_svarint_encode(self.seed))
        for row in self._rows:
            for value in row:
                parts.append(_uvarint_encode(value))
        encoded = []
        for key in self._keys:
            tag, payload = self._encode_key(key)
            encoded.append((payload, tag))
        encoded.sort(key=lambda item: (item[0], item[1]))
        parts.append(_uvarint_encode(len(encoded)))
        for payload, tag in encoded:
            parts.append(bytes([tag]))
            parts.append(_uvarint_encode(len(payload)))
            parts.append(payload)
        return b"".join(parts)

    @staticmethod
    def deserialize(data):
        """从 ``serialize()`` 的字节还原草图；坏数据抛 ``ValueError``。"""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise ValueError("序列化数据必须是 bytes")
        data = bytes(data)
        pos = 0
        size = len(data)

        def take(num):
            nonlocal pos
            if pos + num > size:
                raise ValueError("序列化数据被截断")
            chunk = data[pos:pos + num]
            pos += num
            return chunk

        def uvarint():
            nonlocal pos
            result = 0
            shift = 0
            while True:
                if pos >= size:
                    raise ValueError("序列化数据被截断")
                byte = data[pos]
                pos += 1
                result |= (byte & 0x7F) << shift
                if not (byte & 0x80):
                    break
                shift += 7
            return result

        if take(4) != _MAGIC:
            raise ValueError("序列化数据魔数不匹配")
        version = take(1)[0]
        if version != FORMAT_VERSION:
            raise ValueError("序列化数据版本不支持")
        flags = take(1)[0]
        width = uvarint()
        depth = uvarint()
        encoded_seed = uvarint()
        seed = (encoded_seed >> 1) ^ -(encoded_seed & 1)

        if width <= 0 or depth <= 0:
            raise ValueError("序列化数据中的 width/depth 非法")
        if flags & ~_FLAG_CONSERVATIVE:
            raise ValueError("序列化数据含有未知标志位")

        sketch = CountMinSketch(
            width, depth, seed=seed,
            conservative=bool(flags & _FLAG_CONSERVATIVE),
        )
        for row in range(depth):
            target_row = sketch._rows[row]
            for col in range(width):
                target_row[col] = uvarint()

        key_count = uvarint()
        for _ in range(key_count):
            tag = take(1)[0]
            length = uvarint()
            payload = take(length)
            if tag == _TAG_STR:
                try:
                    key = payload.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError("序列化数据中的 str key 不是合法 UTF-8") from exc
            elif tag == _TAG_BYTES:
                key = payload
            else:
                raise ValueError("序列化数据含有未知 key 类型")
            sketch._keys.add(key)

        if pos != size:
            raise ValueError("序列化数据含有多余字节")
        return sketch
