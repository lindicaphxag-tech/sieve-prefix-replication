"""Byte-capacity cache policies, independent implementations.

Capacity is bytes (the paper uses 0.1% and 10% of the trace footprint in
bytes). A request whose object is larger than the whole cache is always a
miss and is not inserted, which is what libCacheSim does.
"""

from collections import OrderedDict


class BytesBase:
    def __init__(self, capacity_bytes):
        self.cap = capacity_bytes
        self.used = 0

    def _room_for(self, size):
        return self.used + size <= self.cap


class BytesLRU(BytesBase):
    name = "LRU"

    def __init__(self, capacity_bytes):
        super().__init__(capacity_bytes)
        self.d = OrderedDict()

    def request(self, key, size):
        d = self.d
        if key in d:
            d.move_to_end(key)
            return 0
        if size > self.cap:
            return 1
        while self.used + size > self.cap and d:
            _, old_size = d.popitem(last=False)
            self.used -= old_size
        d[key] = size
        self.used += size
        return 1


class BytesFIFO(BytesBase):
    name = "FIFO"

    def __init__(self, capacity_bytes):
        super().__init__(capacity_bytes)
        self.d = OrderedDict()

    def request(self, key, size):
        d = self.d
        if key in d:
            return 0
        if size > self.cap:
            return 1
        while self.used + size > self.cap and d:
            _, old_size = d.popitem(last=False)
            self.used -= old_size
        d[key] = size
        self.used += size
        return 1


class Node:
    __slots__ = ("key", "size", "prev", "next", "flag")

    def __init__(self, key, size):
        self.key = key
        self.size = size
        self.prev = None
        self.next = None
        self.flag = 0


class QueueBytes(BytesBase):
    """Single doubly linked queue, newest at head, per-node flag."""

    def __init__(self, capacity_bytes):
        super().__init__(capacity_bytes)
        self.head = None
        self.tail = None
        self.table = {}

    def _prepend(self, node):
        node.prev = None
        node.next = self.head
        if self.head is not None:
            self.head.prev = node
        self.head = node
        if self.tail is None:
            self.tail = node

    def _remove(self, node):
        if node.prev is not None:
            node.prev.next = node.next
        else:
            self.head = node.next
        if node.next is not None:
            node.next.prev = node.prev
        else:
            self.tail = node.prev
        node.prev = None
        node.next = None

    def _drop(self, node):
        del self.table[node.key]
        self._remove(node)
        self.used -= node.size


class BytesSIEVE(QueueBytes):
    name = "SIEVE"

    def __init__(self, capacity_bytes):
        super().__init__(capacity_bytes)
        self.pointer = None

    def request(self, key, size):
        node = self.table.get(key)
        if node is not None:
            node.flag = 1
            return 0
        if size > self.cap:
            return 1
        while self.used + size > self.cap and self.head is not None:
            obj = self.pointer if self.pointer is not None else self.tail
            while obj.flag > 0:
                obj.flag = 0
                obj = obj.prev if obj.prev is not None else self.tail
            self.pointer = obj.prev
            self._drop(obj)
        node = Node(key, size)
        self.table[key] = node
        self._prepend(node)
        self.used += size
        return 1


class BytesCLOCK(QueueBytes):
    name = "CLOCK"

    def request(self, key, size):
        node = self.table.get(key)
        if node is not None:
            node.flag = 1
            return 0
        if size > self.cap:
            return 1
        while self.used + size > self.cap and self.head is not None:
            obj = self.tail
            while obj.flag > 0:
                obj.flag = 0
                obj = obj.prev if obj.prev is not None else self.tail
            self._drop(obj)
        node = Node(key, size)
        self.table[key] = node
        self._prepend(node)
        self.used += size
        return 1


class BytesFIFOReinsertion(QueueBytes):
    name = "FIFO-Reinsertion"

    def request(self, key, size):
        node = self.table.get(key)
        if node is not None:
            node.flag = 1
            return 0
        if size > self.cap:
            return 1
        while self.used + size > self.cap and self.head is not None:
            obj = self.tail
            if obj.flag > 0:
                obj.flag = 0
                self._remove(obj)
                self._prepend(obj)
                continue
            self._drop(obj)
        node = Node(key, size)
        self.table[key] = node
        self._prepend(node)
        self.used += size
        return 1


POLICIES = {
    p.name: p for p in (BytesLRU, BytesFIFO, BytesSIEVE, BytesCLOCK, BytesFIFOReinsertion)
}
