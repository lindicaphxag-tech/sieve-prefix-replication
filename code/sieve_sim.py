"""Independent Python implementations of cache eviction policies.

Written from published algorithm descriptions. The vendored C++ code in the
artifact (libCacheSim) is not used, so this is a replication (new code)
rather than a reproduction (same code).
"""

from collections import OrderedDict


class OrderedPolicy:
    """LRU / FIFO share an ordered map; insertion or move-to-head differ."""

    def __init__(self, capacity):
        self.c = capacity
        self.d = OrderedDict()

    def request(self, key):
        if key in self.d:
            self.on_hit(key)
            return 0
        if len(self.d) >= self.c:
            self.d.popitem(last=False)
        self.d[key] = None
        if len(self.d) > self.c:
            self.d.popitem(last=False)
        return 1

    def on_hit(self, key):
        raise NotImplementedError


class LRU(OrderedPolicy):
    name = "LRU"

    def on_hit(self, key):
        self.d.move_to_end(key, last=True)


class FIFO(OrderedPolicy):
    name = "FIFO"

    def on_hit(self, key):
        return None


class QueuePolicy:
    """A single doubly linked queue with per-slot metadata, oldest at tail."""

    def __init__(self, capacity):
        self.c = capacity
        self.key2slot = {}
        self.slot2key = []
        self.prev = []
        self.next = []
        self.meta = []
        self.head = -1
        self.tail = -1
        self.free = []

    def _new_slot(self):
        if self.free:
            slot = self.free.pop()
            self.prev[slot] = -1
            self.next[slot] = -1
            return slot
        slot = len(self.slot2key)
        self.slot2key.append(None)
        self.prev.append(-1)
        self.next.append(-1)
        self.meta.append(0)
        return slot

    def _link_head(self, slot):
        self.prev[slot] = -1
        self.next[slot] = self.head
        if self.head != -1:
            self.prev[self.head] = slot
        self.head = slot
        if self.tail == -1:
            self.tail = slot

    def _unlink(self, slot):
        p, n = self.prev[slot], self.next[slot]
        if p != -1:
            self.next[p] = n
        else:
            self.head = n
        if n != -1:
            self.prev[n] = p
        else:
            self.tail = p
        self.prev[slot] = -1
        self.next[slot] = -1

    def _drop(self, slot):
        key = self.slot2key[slot]
        del self.key2slot[key]
        self.slot2key[slot] = None
        self._unlink(slot)
        self.free.append(slot)

    def _insert(self, key):
        slot = self._new_slot()
        self.slot2key[slot] = key
        self.key2slot[key] = slot
        self.meta[slot] = 0
        self._link_head(slot)

    def _evict_one(self):
        raise NotImplementedError


class SIEVE(QueuePolicy):
    name = "SIEVE"

    def __init__(self, capacity):
        super().__init__(capacity)
        self.hand = -1

    def _evict_one(self):
        hand = self.hand if self.hand != -1 else self.tail
        while self.meta[hand] == 1:
            self.meta[hand] = 0
            hand = self.prev[hand]
            if hand == -1:
                hand = self.tail
        victim = hand
        nxt = self.prev[victim]
        self._drop(victim)
        self.hand = nxt if nxt != -1 else (self.tail if self.tail != -1 else -1)

    def request(self, key):
        slot = self.key2slot.get(key)
        if slot is not None:
            self.meta[slot] = 1
            return 0
        if len(self.key2slot) >= self.c and self.tail != -1:
            self._evict_one()
        self._insert(key)
        if self.hand == -1:
            self.hand = self.tail
        return 1


class CLOCK(QueuePolicy):
    name = "CLOCK"

    def _evict_one(self):
        hand = self.tail
        while self.meta[hand] == 1:
            self.meta[hand] = 0
            hand = self.prev[hand]
            if hand == -1:
                hand = self.tail
        self._drop(hand)

    def request(self, key):
        slot = self.key2slot.get(key)
        if slot is not None:
            self.meta[slot] = 1
            return 0
        if len(self.key2slot) >= self.c and self.tail != -1:
            self._evict_one()
        self._insert(key)
        return 1


class FIFOReinsertion(QueuePolicy):
    name = "FIFO-Reinsertion"

    def request(self, key):
        slot = self.key2slot.get(key)
        if slot is not None:
            self.meta[slot] = 1
            return 0
        while len(self.key2slot) >= self.c and self.tail != -1:
            victim = self.tail
            if self.meta[victim] == 1:
                self.meta[victim] = 0
                self._unlink(victim)
                self._link_head(victim)
                continue
            self._drop(victim)
        self._insert(key)
        return 1


class LFU:
    name = "LFU"

    def __init__(self, capacity):
        self.c = capacity
        self.freq = {}

    def request(self, key):
        n = self.freq.get(key)
        if n is not None:
            self.freq[key] = n + 1
            return 0
        if len(self.freq) >= self.c:
            victim = min(self.freq, key=self.freq.get)
            del self.freq[victim]
        self.freq[key] = 1
        return 1


POLICIES = {
    p.name: p for p in (LRU, FIFO, SIEVE, CLOCK, FIFOReinsertion, LFU)
}


def run(policy_cls, keys, capacity, label=None):
    policy = policy_cls(capacity)
    misses = 0
    for key in keys:
        misses += policy.request(key)
    ratio = misses / len(keys)
    print("%-18s C=%-7d misses=%-9d ratio=%.6f" % (label or policy_cls.name, capacity, misses, ratio), flush=True)
    return misses, ratio
