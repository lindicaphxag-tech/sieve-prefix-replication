"""Node-based SIEVE that mirrors Sieve.c pointer semantics literally.

Queue: new objects at head. `prev` points toward head (newer), `next` toward
the tail (older). Hand (`pointer`) walks with `prev` and wraps to the tail.
On hit, freq is set to 1. On eviction the first node with freq == 0 is
removed and pointer becomes the evicted node's `prev`.
"""


class Node:
    __slots__ = ("key", "prev", "next", "freq")

    def __init__(self, key):
        self.key = key
        self.prev = None
        self.next = None
        self.freq = 0


class SieveLiteral:
    name = "SIEVE-literal"

    def __init__(self, capacity):
        self.c = capacity
        self.head = None
        self.tail = None
        self.table = {}
        self.pointer = None
        self.n = 0

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

    def request(self, key):
        node = self.table.get(key)
        if node is not None:
            node.freq = 1
            return 0
        if self.n >= self.c:
            obj = self.pointer if self.pointer is not None else self.tail
            while obj.freq > 0:
                obj.freq -= 1
                obj = obj.prev if obj.prev is not None else self.tail
            self.pointer = obj.prev
            self._remove(obj)
            del self.table[obj.key]
            self.n -= 1
        node = Node(key)
        self.table[key] = node
        self._prepend(node)
        self.n += 1
        return 1
