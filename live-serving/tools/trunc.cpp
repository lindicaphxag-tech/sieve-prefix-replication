// trunc.cpp - cut an .lcp.zst trace to its first N requests, keeping it zstd-compressed.
// Used for window experiments (e.g. does SIEVE beat LRU in chutes' opening window?).
// build: g++ -O2 -o trunc trunc.cpp -lzstd
// run  : ./trunc trace/chutes.lcp.zst trace/chutes_head.lcp.zst 30000
#include <stdlib.h>
#include <string.h>
#include <zstd.h>
#include <stdio.h>
#include <stdint.h>
#include <vector>

int main(int argc, char** argv) {
  if (argc < 4) { fprintf(stderr, "usage: trunc <in.lcp.zst> <out.lcp.zst> <n_requests>\n"); return 1; }
  FILE* f = fopen(argv[1], "rb");
  size_t N = (size_t)atol(argv[3]);
  ZSTD_DStream* ds = ZSTD_createDStream(); ZSTD_initDStream(ds);
  std::vector<char> in(1 << 20), out(1 << 22), keep; keep.reserve(1 << 25);
  std::vector<char> zbuf(1 << 22);
  FILE* g = fopen(argv[2], "wb");
  ZSTD_CStream* cs = ZSTD_createCStream(); ZSTD_initCStream(cs, 1);
  size_t nreq = 0; bool hdr = false; uint32_t nent = 0; size_t pos = 0; bool done = false;

  auto writeout = [&](const char* p, size_t n) {
    ZSTD_inBuffer ib = {p, n, 0};
    while (ib.pos < ib.size) {
      ZSTD_outBuffer ob = {zbuf.data(), zbuf.size(), 0};
      ZSTD_compressStream(cs, &ob, &ib);
      fwrite(zbuf.data(), 1, ob.pos, g);
    }
  };

  auto run = [&]() -> bool {
    while (true) {
      size_t avail = keep.size() - pos;
      if (!hdr) { if (avail < 8192) return false; pos += 8192; hdr = true; continue; }
      if (nent == 0) {
        if (avail < 68) return false;
        uint32_t nb; memcpy(&nb, keep.data() + pos + 48, 4);
        pos += 68; nent = nb;
        if (nb == 0) { if (++nreq >= N) return true; }
        continue;
      }
      if (avail < 16u * nent) return false;
      pos += 16u * nent; nent = 0;
      if (++nreq >= N) return true;
    }
  };

  for (;;) {
    size_t rd = fread(in.data(), 1, in.size(), f); if (!rd) break;
    ZSTD_inBuffer ib = {in.data(), rd, 0};
    while (ib.pos < ib.size) {
      ZSTD_outBuffer ob = {out.data(), out.size(), 0};
      ZSTD_decompressStream(ds, &ob, &ib);
      if (ob.pos) {
        keep.insert(keep.end(), out.data(), out.data() + ob.pos);
        if (run()) { done = true; break; }
      }
    }
    if (pos > (1u << 20)) { writeout(keep.data(), pos); keep.erase(keep.begin(), keep.begin() + pos); pos = 0; }
    if (done) break;
  }
  writeout(keep.data(), pos);
  ZSTD_outBuffer ob = {zbuf.data(), zbuf.size(), 0};
  ZSTD_endStream(cs, &ob);
  fwrite(zbuf.data(), 1, ob.pos, g);
  fclose(g);
  printf("requests=%zu kept=%zu\n", nreq, pos);
  return 0;
}
