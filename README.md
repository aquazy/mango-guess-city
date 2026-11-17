# 芒果猜城市 ·网页版

一个纯前端的地图猜城市小游戏：从白色路网剪影中猜出城市，还可以生成随机城市墙纸、挑战限时模式。

## 玩法

- **芒果猜城市**：根据路网猜城市，十题一组，结算显示成绩。
- **限时挑战**：在限定时间内连续作答，隐藏随机国际与底部工具栏。
- **生成墙纸**：随机国内 / 国际城市，一键生成可保存的城市路网墙纸；出现过的城市排到队尾，不重复。

## 本地运行

瓦片通过 `fetch()` 加载，浏览器不允许从 `file://` 读取，请起一个本地静态服务器：

```bash
python3 -m http.server 8000
# 打开 http://localhost:8000/index.html
```

不需要 npm 安装依赖，MapLibre GL 已放在 `vendor/` 目录。

## 项目结构

| 文件 | 说明 |
| --- | --- |
| `index.html` | 全部页面逻辑与样式（单文件应用） |
| `vendor/` | 本地 MapLibre GL |
| `tiles/c<id>.bin` | 160 座城市的矢量瓦片包（MGT1 格式，gzip 压缩） |
| `build_tiles.py` | 从 OpenFreeMap 原始数据切图、裁剪并打成城市包 |
| `split_packs.py` | 早期按层级拆包的辅助脚本 |

## 瓦片与显示规则

- 每座城市一个 `tiles/c<id>.bin`，内含该城市所需的矢量瓦片，字段只有渲染需要的 `class`。
- 跨度大的城市（旧 s > 30km）首屏按「覆盖市域再放大一倍」显示，包内保存 `z基础层 … z12` 多层金字塔，放大时由 MapLibre 自动换层加载更细的路网；小城市保持单层 z12。
- 包外区域会回落到 OpenFreeMap 的同层级原始瓦片，避免粗细路网拼接出现分界线。
- 瓦片包 URL 带 `?v=` 版本串；重新打包后需要修改 `index.html` 里的版本号，避免旧缓存。

重新打某个城市的包：

```bash
ONLY=26,28 python3 build_tiles.py tiles   # 26=北京，28=上海
python3 build_tiles.py tiles              # 全部 160 城
```

## 数据来源与署名

地图数据来自 [OpenFreeMap](https://openfreemap.org/)（planet 20261101_080013_pt），底层数据 © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright)，按 ODbL 许可证使用。

作者：陈芒果。
