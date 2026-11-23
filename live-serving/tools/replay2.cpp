// replay2.cpp - prefix-cache replay with two hit metrics and four victim rules.
// Used by ALGORITHM_2026.md: lru | sieve | orphan | capchain <m>
// metric=block  : a block counts as a hit if it is resident (PrefixSim's accounting)
// metric=prefix : only the contiguous resident prefix counts (what vLLM engines report)
//
// build: g++ -O2 -std=c++17 -o replay2 replay2.cpp -lzstd
// run  : ./replay2 trace/chutes.lcp.zst 65536 lru prefix
//        ./replay2 trace/chutes.lcp.zst 65536 capchain prefix 256
//
// Semantics: three phases per request (match -> make room -> access), the arriving
// request's blocks pinned throughout so a request never evicts itself, uniform cost,
// block-id = prefix. Validated against PrefixSim on chutes 64k LRU: 0.726831.
#include <zstd.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <vector>

static const int HDR = 8192, REQ = 68, ENT = 16;
static const uint32_t NIL = 0;

struct Ctx {
  uint32_t cap; int64_t nuniq;
  uint8_t* tier; uint8_t* visited; uint32_t* prev; uint32_t* next; uint32_t* parent;
  uint32_t head, tail, count; uint64_t evicts, hits, accs;
  uint32_t* pinset; uint32_t mask;
};

static inline int is_pinned(Ctx* c, uint32_t id) {
  uint32_t h = (id * 2654435761u) & c->mask;
  for (int i = 0; i < 8; i++) { uint32_t v = c->pinset[(h + i) & c->mask]; if (v == id) return 1; if (v == 0) return 0; }
  return 0;
}
static inline void list_push(Ctx* c, uint32_t id) {
  c->prev[id] = NIL; c->next[id] = c->head;
  if (c->head) c->prev[c->head] = id; else c->tail = id;
  c->head = id;
}
static inline void list_remove(Ctx* c, uint32_t id) {
  uint32_t a = c->prev[id], b = c->next[id];
  if (a) c->next[a] = b; else c->head = b;
  if (b) c->prev[b] = a; else c->tail = a;
}

static uint32_t pick(Ctx* c, int mode) {
  uint32_t x = c->tail;
  while (x && is_pinned(c, x)) x = c->prev[x];
  if (!x) return 0;
  if (mode == 1) {                       // sieve: second chance from the tail
    int g = 0;
    while (x && c->visited[x] && g++ < 8192) {
      c->visited[x] = 0;
      uint32_t y = c->prev[x]; if (!y) y = c->head;
      if (!y) break;
      x = y; while (x && is_pinned(c, x)) x = c->prev[x];
    }
    return x;
  }
  if (mode == 2) {                       // orphan-first: prefer a block whose parent is gone
    int g = 0; uint32_t y = x;
    while (y && g++ < 64) {
      uint32_t p = c->parent[y];
      if (p == 0 || c->tier[p] == 0) return y;   // root never orphan; parent absent = unreachable
      y = c->prev[y];
      while (y && is_pinned(c, y)) y = c->prev[y];
    }
  }
  return x;
}

int main(int argc, char** argv) {
  if (argc < 4) { fprintf(stderr, "usage: replay2 <trace> <blocks> <lru|sieve|orphan|capchain> [block|prefix] [m]\n"); return 1; }
  const char* path = argv[1];
  uint32_t cap = (uint32_t)atof(argv[2]);
  const char* pol = argv[3];
  int mode = strcmp(pol, "lru") == 0 ? 0 : strcmp(pol, "sieve") == 0 ? 1 : strcmp(pol, "orphan") == 0 ? 2 : 3;
  int prefix_metric = argc > 4 && strcmp(argv[4], "prefix") == 0;
  uint32_t max_admit = (mode == 3 && argc > 5) ? (uint32_t)atof(argv[5]) : 0;
  FILE* f = fopen(path, "rb"); if (!f) { perror("open"); return 1; }
  ZSTD_DStream* ds = ZSTD_createDStream(); ZSTD_initDStream(ds);
  std::vector<char> in(1 << 20), out(1 << 22), acc; size_t gpos = 0;

  Ctx c; memset(&c, 0, sizeof(c)); c.cap = cap;
  bool hdr = false; int64_t pend = 0;
  std::vector<uint32_t> ids; ids.reserve(1 << 14);

  auto process = [&]() {
    const char* buf = acc.data(); size_t n = acc.size(); size_t pos = gpos;
    while (pos < n) {
      if (!hdr) {
        if (n - pos < (size_t)HDR) { gpos = pos; return; }
        int64_t nn; memcpy(&nn, buf + pos + 32, 8); c.nuniq = nn;
        size_t nu = (size_t)nn + 2;
        c.tier = (uint8_t*)calloc(nu, 1);
        c.prev = (uint32_t*)calloc(nu, 4); c.next = (uint32_t*)calloc(nu, 4);
        c.parent = (uint32_t*)calloc(nu, 4);
        if (mode == 1) c.visited = (uint8_t*)calloc(nu, 1);
        c.mask = (1u << 15) - 1; c.pinset = (uint32_t*)calloc(c.mask + 1, 4);
        if (!c.tier || !c.prev || !c.next || !c.parent || !c.pinset) { fprintf(stderr, "alloc fail\n"); exit(2); }
        pos += HDR; hdr = true; continue;
      }
      if (pend > 0) {
        if (n - pos < (size_t)ENT) { gpos = pos; return; }
        uint64_t bid; memcpy(&bid, buf + pos, 8); pos += ENT;
        if (bid == 0 || bid > (uint64_t)c.nuniq) { fprintf(stderr, "bad id\n"); exit(3); }
        ids.push_back((uint32_t)bid);
        if (--pend) continue;
        uint32_t nb = (uint32_t)ids.size();
        memset(c.pinset, 0, sizeof(uint32_t) * (c.mask + 1));
        for (uint32_t i = 0; i < nb; i++) {
          uint32_t id = ids[i], h = (id * 2654435761u) & c.mask;
          for (int k = 0; k < 8; k++) { uint32_t s = (h + k) & c.mask; if (!c.pinset[s]) { c.pinset[s] = id; break; } }
        }
        uint32_t nres = 0, contig = 0;
        for (uint32_t i = 0; i < nb; i++) if (c.tier[ids[i]]) nres++;
        if (prefix_metric) { while (contig < nb && c.tier[ids[contig]]) contig++; }
        c.hits += prefix_metric ? contig : nres; c.accs += nb;
        int64_t need = (int64_t)nres - ((int64_t)c.cap - (int64_t)c.count);
        int64_t done = 0;
        while (done < need) {
          uint32_t v = pick(&c, mode); if (!v) break;
          list_remove(&c, v); c.tier[v] = 0; if (c.visited) c.visited[v] = 0;
          c.count--; c.evicts++; done++;
        }
        for (uint32_t i = 0; i < nb; i++) {
          uint32_t id = ids[i];
          if (c.tier[id]) { if (c.visited) c.visited[id] = 1; list_remove(&c, id); list_push(&c, id); }
          else { if (mode == 3 && i >= max_admit) continue;
                 c.tier[id] = 1; c.parent[id] = i ? ids[i-1] : 0; list_push(&c, id); c.count++; }
        }
        ids.clear();
      } else {
        if (n - pos < (size_t)REQ) { gpos = pos; return; }
        uint32_t nb; memcpy(&nb, buf + pos + 48, 4); pos += REQ;
        pend = nb; ids.clear();
      }
    }
    gpos = pos;
  };

  for (;;) { size_t rd = fread(in.data(), 1, in.size(), f); if (!rd) break;
    ZSTD_inBuffer ib = {in.data(), rd, 0};
    while (ib.pos < ib.size) { ZSTD_outBuffer ob = {out.data(), out.size(), 0};
      size_t rc = ZSTD_decompressStream(ds, &ob, &ib); if (ZSTD_isError(rc)) { fprintf(stderr, "zstd\n"); return 2; }
      if (ob.pos) acc.insert(acc.end(), out.data(), out.data() + ob.pos); }
    process(); if (gpos > (1u << 20)) { acc.erase(acc.begin(), acc.begin() + gpos); gpos = 0; } }
  process();
  printf("POLICY %s metric=%s cap=%u accesses=%llu hits=%llu hit_ratio=%.6f evictions=%llu\n",
         pol, prefix_metric ? "prefix" : "block", cap, (unsigned long long)c.accs,
         (unsigned long long)c.hits, c.accs ? (double)c.hits / (double)c.accs : 0.0,
         (unsigned long long)c.evicts);
  return 0;
}
