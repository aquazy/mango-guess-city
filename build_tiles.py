#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把猜城市用到的矢量瓦片裁剪成「一城一包」，供前端自托管加载。"""
import os, sys, re, json, math, gzip, struct, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
import mapbox_vector_tile as mvt

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
BASE = "https://tiles.openfreemap.org/planet/20261101_080013_pt"
CACHE = "/tmp/mvt-cache"
OUT = sys.argv[1] if len(sys.argv) > 1 else "tiles"
KEEP_LAYERS = ("water", "waterway", "transportation", "aeroway")
# 页面只用 class 做过滤；_construction / transit 等永远不会被渲染，直接删
VALID_CLASSES = {
    "minor", "service", "track", "path", "raceway", "busway", "taxiway", "runway",
    "tertiary", "secondary", "tertiary_link", "secondary_link",
    "motorway", "trunk", "primary", "motorway_link", "trunk_link", "primary_link",
    "rail",
}
# 特大瓦片兜底：删掉线宽 <1px、肉眼几乎不可见的低价值道路
LOW_VALUE = {"path", "track", "service", "raceway", "busway", "taxiway"}
BOX_W, BOX_H = 393.0, 852.0          # 画框内地图尺寸（与页面一致）

os.makedirs(CACHE, exist_ok=True)
os.makedirs(OUT, exist_ok=True)


def http_get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=45).read()
        except Exception as e:          # noqa: BLE001
            last = e
            time.sleep(0.8 * (i + 1))
    raise last


def fetch_tile(z, x, y):
    path = os.path.join(CACHE, f"{z}_{x}_{y}.pbf")
    if os.path.exists(path):
        return open(path, "rb").read()
    raw = http_get(f"{BASE}/{z}/{x}/{y}.pbf")
    with open(path, "wb") as f:
        f.write(raw)
    return raw


def _rdp(pts, tol):
    """Douglas-Peucker 折线简化（瓦片单位）。"""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        den = math.hypot(dx, dy)
        best, bi = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if den == 0:
                dist = math.hypot(px - ax, py - ay)
            else:
                dist = abs(dy * (px - ax) - dx * (py - ay)) / den
            if dist > best:
                best, bi = dist, i
        if best > tol and bi > 0:
            keep[bi] = True
            stack.append((a, bi))
            stack.append((bi, b))
    return [p for i, p in enumerate(pts) if keep[i]]


def _simplify_geom(geom, tol):
    t = geom.get("type")
    if t == "LineString":
        r = _rdp(geom["coordinates"], tol)
        return geom if len(r) < 2 else {"type": t, "coordinates": r}
    if t == "MultiLineString":
        out = [_rdp(c, tol) if len(c) > 2 else c for c in geom["coordinates"]]
        return {"type": t, "coordinates": out}
    if t == "Polygon":
        rings = [_rdp(r, tol) if len(r) > 3 else r for r in geom["coordinates"]]
        if any(len(r) < 4 for r in rings):        # 简化破坏了环 → 保留原几何
            return geom
        return {"type": t, "coordinates": rings}
    if t == "MultiPolygon":
        polys = []
        for p in geom["coordinates"]:
            rings = [_rdp(r, tol) if len(r) > 3 else r for r in p]
            if any(len(r) < 4 for r in rings):
                return geom                        # 整体回退，避免出现非法环
            polys.append(rings)
        return {"type": t, "coordinates": polys}
    return geom


def trim(raw, tol=5.0):
    """只留页面需要的 4 个图层 + class 属性，几何做轻量简化。"""
    d = mvt.decode(raw)
    layers = []
    for name, layer in d.items():
        if name not in KEEP_LAYERS:
            continue
        low = None
        if name == "transportation":
            low = LOW_VALUE
        feats = []
        for f in layer["features"]:
            cls = f["properties"].get("class")
            # class 白名单只针对道路：水域的 class 是 ocean/lake/river/pond，
            # waterway 是 river/canal/stream，以前一起被过滤掉，导致江河湖海
            # 在打包后整片消失，看起来像「地图没加载出来」。
            if name == "transportation":
                if cls is not None and cls not in VALID_CLASSES:
                    continue                      # 渲染时永远不可见的要素
                if low and cls in low:
                    continue                      # 超大瓦片会二次过滤
            g = _simplify_geom(f["geometry"], tol)
            feats.append({"geometry": g,
                          "properties": {k: v for k, v in f["properties"].items() if k == "class"}})
        if feats:
            layers.append({"name": name, "features": feats})
    if not layers:
        return None
    # 【关键】decode() 默认把 MVT 的 y 转成 y-up；encode 必须保持默认（y-up 输入），
    # 否则会把已经是 y-up 的坐标当 y-down 写回，整块瓦片上下镜像，
    # 相邻瓦片的水域/道路在边界处接不上，成图出现「一块一块的直角分界线」。
    return mvt.encode(layers, default_options={"extents": 4096})


def trim_small(raw, tol=5.0):
    """低价值道路保留（普通瓦片体积小，为视觉密度保留它们）。"""
    d = mvt.decode(raw)
    layers = []
    for name, layer in d.items():
        if name not in KEEP_LAYERS:
            continue
        feats = []
        for f in layer["features"]:
            cls = f["properties"].get("class")
            # 同上：只过滤 transportation，water / waterway / aeroway 全部保留
            if name == "transportation" and cls is not None and cls not in VALID_CLASSES:
                continue
            g = _simplify_geom(f["geometry"], tol)
            feats.append({"geometry": g,
                          "properties": {k: v for k, v in f["properties"].items() if k == "class"}})
        if feats:
            layers.append({"name": name, "features": feats})
    if not layers:
        return None
    # 【关键】decode() 默认把 MVT 的 y 转成 y-up；encode 必须保持默认（y-up 输入），
    # 否则会把已经是 y-up 的坐标当 y-down 写回，整块瓦片上下镜像，
    # 相邻瓦片的水域/道路在边界处接不上，成图出现「一块一块的直角分界线」。
    return mvt.encode(layers, default_options={"extents": 4096})


def city_zoom(span_km, lat):
    m_per_px = span_km * 1000.0 / BOX_W
    z = math.log2(156543.03392 * math.cos(lat * math.pi / 180) / m_per_px) + 1
    return max(4.0, min(15.5, z))


def tile_xy(lng, lat, z):
    n = 2 ** z
    x = (lng + 180.0) / 360.0 * n
    rad = max(-85.0, min(85.0, lat)) * math.pi / 180
    y = (1 - math.log(math.tan(rad) + 1 / math.cos(rad)) / math.pi) / 2 * n
    return x, y


def tiles_for(lng, lat, zr, z, pad=1):
    """按缩放 zr、目标层级 z，算出视口覆盖 + pad 圈缓冲的瓦片坐标。"""
    n = 2 ** z
    scale = 2.0 ** (zr - z)                    # 一个瓦片像素在当前缩放下占多少屏幕像素
    half_w = BOX_W / scale / 2.0 / 512.0
    half_h = BOX_H / scale / 2.0 / 512.0
    cx, cy = tile_xy(lng, lat, z)
    x0 = int(math.floor(cx - half_w)) - pad
    x1 = int(math.floor(cx + half_w)) + pad
    y0 = int(math.floor(cy - half_h)) - pad
    y1 = int(math.floor(cy + half_h)) + pad
    out = []
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            if 0 <= y < n:
                out.append((z, ((x % n) + n) % n, y))
    return out


def build_pack(cid, name, lng, lat, span):
    zr = city_zoom(span, lat)
    # MapLibre 在 zoom 非整数时请求 floor(zoom) 层的瓦片，必须用 floor 对齐
    z0 = max(8, min(13, int(math.floor(zr))))
    # 多层金字塔（2026-11-16）：基础层 floor(city_zoom)<12 的城市（旧规则「先覆盖
    # 市域再放大一级」），包里放 z0..12 每一层，放大时逐级加载更细的路网。
    # 每层的覆盖框 = 屏幕在 max(zr, z) 缩放下的范围 + 1 圈 pad：
    #   z <= zr 的层铺满初始视野（用户在这一层平移看全市不缺瓦片）；
    #   z >  zr 的层只铺该层自己的一屏（屏幕随放大变小，pad 后够日常平移；
    #   包外平移由前端境外兜底补「同层级原始瓦片」，详略一致不会出现分界线）。
    # 注意：不能只给细节层打屏幕中心 0.6 屏（旧版做法）——放大时屏幕一部分
    # 命中细节层、一部分用父级补位，才会出现「不同地图块道路粗细不一样」。
    # z0 == 12 的城市保持单层包不变（视野本来就在 z12 一屏内）。
    if z0 < 12:
        levels = range(z0, 13)
    else:
        levels = (z0,)
    want = []
    for z in levels:
        want += tiles_for(lng, lat, max(zr, z), z, pad=1)

    uniq = sorted(set(want))
    tiles, stats = {}, {"raw": 0, "trim": 0, "hit": 0, "miss": 0}
    for (z, x, y) in uniq:
        try:
            raw = fetch_tile(z, x, y)
        except Exception:                       # noqa: BLE001
            stats["miss"] += 1
            continue
        stats["raw"] += len(raw)
        t = trim_small(raw)
        if t and len(t) > 110 * 1024:
            # 特大瓦片（路网特别密的大城市）：删掉肉眼不可见的低价值道路
            t = trim(raw)
        if not t:
            continue
        stats["hit"] += 1
        stats["trim"] += len(t)
        tiles[f"{z}/{x}/{y}"] = t

    if not tiles:
        return None, stats

    # 单层包：该城市用到的所有层级拼进一份 c<id>.bin（与线上前端一致）
    entries, blobs, off = {}, [], 0
    for key in sorted(tiles):
        t = tiles[key]
        entries[key] = [off, len(t)]
        blobs.append(t)
        off += len(t)
    idx = json.dumps(entries, separators=(",", ":")).encode()
    body = b"MGT1" + struct.pack("<I", len(idx)) + idx + b"".join(blobs)
    gz = gzip.compress(body, 9)
    with open(os.path.join(OUT, f"c{cid}.bin"), "wb") as f:
        f.write(gz)
    zs = sorted({int(k.split('/')[0]) for k in tiles})
    return {"id": cid, "name": name, "z0": zs[0], "zmax": zs[-1], "levels": zs,
            "files": len(blobs),
            "raw_kb": stats["raw"] // 1024, "trim_kb": stats["trim"] // 1024,
            "pack_kb": len(gz) // 1024}, stats


def main():
    h = open("index.html", encoding="utf-8").read()
    pat = re.compile(r"\['([^']+)'\s*,\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*,\s*(\d+)\]")
    seen, cities = set(), []
    for n, lng, lat, span in pat.findall(h):
        if n in seen:
            continue
        seen.add(n)
        cities.append((n, float(lng), float(lat), int(span)))
    print(f"cities: {len(cities)}")

    limit = int(os.environ.get("LIMIT", "0"))
    work = list(enumerate(cities))
    only = os.environ.get("ONLY")
    if only:
        picks = {int(x) for x in only.split(",")}
        work = [w for w in work if w[0] in picks]
    elif limit:
        work = work[:limit]

    rows = []
    with ThreadPoolExecutor(max_workers=28) as ex:
        futs = [ex.submit(build_pack, i, n, lng, lat, span)
                for i, (n, lng, lat, span) in work]
        for i, f in enumerate(futs):
            try:
                info, st = f.result()
                if info:
                    rows.append(info)
                    print(f"[{i:3d}] {info['name']:<10} 层级{info['levels']} files={info['files']:3d} "
                          f"raw={info['raw_kb']:5d}KB trim={info['trim_kb']:5d}KB pack={info['pack_kb']:4d}KB")
            except Exception as e:              # noqa: BLE001
                print(f"[{i:3d}] FAIL {e}")

    total = sum(r["pack_kb"] for r in rows)
    print(f"\npacks={len(rows)} total={total/1024:.1f}MB avg={total/max(1,len(rows)):.0f}KB")
    # 若各城市 z0 有变化，必须同步更新 index.html 里的 PACK_ZOOM（按 id 顺序），
    # 否则切城市时 source.maxzoom 会切到错误层级 → 整屏只剩底色（2026-11-14 修复）
    with open(os.path.join(OUT, "_report.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
