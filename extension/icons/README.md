# 图标

四个 PNG 是按尺寸真实光栅化的，不是从 128 缩放来的——16px 缩放后描边会糊成一团。

| 文件 | 源 | 说明 |
|---|---|---|
| `icon16.png` | `icon-16.svg` | 去掉框内黄条、框改为品牌黄、描边加粗到 15/128 |
| `icon32.png` / `icon48.png` / `icon128.png` | `icon.svg` | 深灰圆角底 + 浅灰字幕框 + 框内一条黄条 |

## 为什么 16 用另一个源

16px 的物理像素只有 256 个。字幕框描边按比例算只有 1.1px，再塞一条黄条，两者互相污染，实测缩成一块台阶。
16px 下黄框是唯一可辨的形状，所以单独构图。这不是妥协，是图标设计的常规做法。

四个候选（声波柱 / 文本行 / 声弧 / 字幕框）当时的 16px 渲染对比结论是：只有字幕框在 16px 下仍然「可辨且语义正确」。
声弧最清楚但读起来像通知或音量，语义偏「接收」不偏「记录」。

## 配色

| 名称 | 值 | 用途 |
|---|---|---|
| 墨底 | `#23272c` | 图标底色、深色界面 |
| 品牌黄 | `#f5c542` | 正在记录 / 强调 |
| 浅灰 | `#e8eaed` | 主形状（字幕框） |

## 重新生成

改完 SVG 后按尺寸逐个光栅化（需要 Edge）：

```bash
W='D:/projects/whisper-ext'          # 必须是绝对 Windows 路径
EDGE="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"

for s in 16 32 48 128; do
  src=$([ "$s" = "16" ] && echo "icon-16.svg" || echo "icon.svg")
  printf '<!doctype html><meta charset="utf-8"><style>html,body{margin:0;overflow:hidden}img{display:block;width:%dpx;height:%dpx}</style><img src="%s">' $s $s "$src" > "$W/icons/_t.html"
  "$EDGE" --headless=new --disable-gpu --hide-scrollbars --default-background-color=00000000 \
    --window-size=$s,$s --screenshot="$W/icons/icon$s.png" "file:///$W/icons/_t.html"
  sleep 2
done
rm -f "$W/icons/_t.html"
```

两个必须遵守的点：

1. **`--default-background-color=00000000` 不能省**。省掉后圆角外会被填成白底，图标在深色工具栏上会带四个白角。
2. **`file://` 后面必须拼绝对 Windows 路径**。Git Bash 里用 `$PWD` 会拼出 `file:////d/...`，Edge 报 `ERR_FILE_NOT_FOUND`
   但**退出码是 0**，看起来像成功了，实际一张图都没生成。

生成完逐个核对：像素尺寸对不对、是否 RGBA（RGB 视为失败）、文件体积有没有异常膨胀。
"生成成功"不等于"图是对的"。
