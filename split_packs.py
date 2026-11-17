#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把已生成的「一城一包」拆成两层：
    tiles/c<id>.bin   基础层（首屏那一级瓦片，飞到城市就能画）
    tiles/c<id>d.bin  细节层（放大一级才用到，页面里延后/按需取）
体积不变（甚至略大一点点，因为两份 gzip 头），但首屏要下的字节少了 4~6 成。

用法：python3 split_packs.py [tiles_dir]
"""
import os, sys, gzip, json, struct

MAGIC = b"MGT1"


def read_pack(path):
    body = gzip.decompress(open(path, "rb").read())
    assert body[:4] == MAGIC, path
    n = struct.unpack("<I", body[4:8])[0]
    idx = json.loads(body[8:8 + n].decode())
    return idx, body[8 + n:]


def write_pack(path, idx, data):
    entries, blobs, off = {}, [], 0
    for key in sorted(idx):
        o, ln = idx[key]
        entries[key] = [off, ln]
        blobs.append(data[o:o + ln])
        off += ln
    j = json.dumps(entries, separators=(",", ":")).encode()
    body = MAGIC + struct.pack("<I", len(j)) + j + b"".join(blobs)
    gz = gzip.compress(body, 9)
    with open(path, "wb") as f:
        f.write(gz)
    return len(gz), len(entries)


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "tiles"
    files = sorted(f for f in os.listdir(d) if f.startswith("c") and f.endswith(".bin"))
    tot_before = tot_base = tot_detail = 0
    worst = []
    for f in files:
        path = os.path.join(d, f)
        if f.endswith("d.bin"):
            continue
        idx, data = read_pack(path)
        zs = sorted({int(k.split("/")[0]) for k in idx})
        base = {k: v for k, v in idx.items() if int(k.split("/")[0]) == zs[0]}
        detail = {k: v for k, v in idx.items() if int(k.split("/")[0]) != zs[0]}
        before = os.path.getsize(path)
        b, _ = write_pack(path, base, data)
        dd = 0
        dp = path[:-4] + "d.bin"
        if detail:
            dd, _ = write_pack(dp, detail, data)
        elif os.path.exists(dp):
            os.remove(dp)
        tot_before += before
        tot_base += b
        tot_detail += dd
        worst.append((before, b, dd, f))
    worst.sort(key=lambda x: -x[0])
    print(f"files={len(files)}  before={tot_before/1048576:.1f}MB  "
          f"base={tot_base/1048576:.1f}MB  detail={tot_detail/1048576:.1f}MB")
    print("首屏平均 %.0fKB（原来 %.0fKB）"
          % (tot_base / len(files) / 1024, tot_before / len(files) / 1024))
    for before, b, dd, f in worst[:6]:
        print(f"  {f:<12} {before/1024:6.0f}KB → base {b/1024:5.0f}KB + detail {dd/1024:5.0f}KB")


if __name__ == "__main__":
    main()
