---
name: oas-runtime-debug
description: Debug OAS runtime failures via logs, error screenshots, live adb capture and template-match checks. Use when a task refuses to run, exits with an exception, or a game page is not recognised (任务无法执行, 报错日志, 识别失败). Do not use for writing new task features.
---

# OAS 运行时故障排查

目标：用最短路径从「任务报错 / 无法执行」走到「可验证的根因 + 可验证的修复」，不要靠猜。

## 0 先确认对象

- 多实例运行时，每个实例有独立 config 和日志：`log/<date>_<实例名>.txt`（如 `2026-11-08_2-水獭.txt`）。
- 读对应实例的日志，别拿另一个实例的日志当证据。

## 1 收集证据

```powershell
Get-ChildItem log -File | Sort-Object LastWriteTime -Descending | Select-Object -First 6 Name,LastWriteTime
Get-Content "log\<date>_<实例>.txt" -Tail 60
Get-ChildItem log\error -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 6 Name
```

错误目录 `log/error/<timestamp>/` 必含 `log.txt` 和失败瞬间截图（1280×720）。截图是第一手证据，优先级高于任何推断。

## 2 按现象分类

| 现象 | 含义 | 下一步 |
| --- | --- | --- |
| `AttributeError: ... has no attribute 'I_xxx'` | 代码引用了资产，但 assets.py 里没有定义 | §5 |
| `find_wq result: current -1` / OCR 只出标题字、area 全 0 | 界面停在非预期页面（弹窗或详情页没关） | §3 |
| `match fail 0.7x/0.8` 逼近阈值 | 版本更新导致 UI 变化 | §4 |
| `xxx timeout` / `failed too many times` | 兜底退出，真正原因在循环里某个 appear 一直不成立 | 找到该循环逐个验证 |

## 3 先用截图判定「卡在哪一页」

不要凭空推断页面状态，用模板对失败截图求分数，就能同时得到页面身份和按钮状态。

```powershell
.\toolkit\python.exe .trae\skills\oas-runtime-debug\scripts\verify_template.py <截图或目录> <模板.png> [--roi x,y,w,h] [--threshold 0.8]
```

- 带上 `--roi` 才等价于线上 `RuleImage` 的 roi_back 语义。
- 应命中的页面分数应明显高于阈值，不该命中的页面要明显低于阈值。

## 4 真机复现与素材更新

```powershell
& "D:\Program Files\Netease\MuMu\nx_main\adb.exe" -s 127.0.0.1:<port> exec-out screencap -p > shot.png
```

- 用 `adb shell input tap/swipe` 复现路径；注意动作可能不可逆（如取消追踪），先确认副作用再动手。
- 更新素材：从截图裁出目标区域存为 png（BGR），roi_back 要覆盖目标可能移动的范围，阈值 0.8。
- 必须双向验证：在「应该命中」的页面命中，在「不应该命中」的页面保持低分。经验安全线是命中 0.95+、误命中 <0.75。

## 5 资产定义一致性（本项目最常踩的坑）

- `self.I_xxx / C_xxx / O_xxx / S_xxx` 必须在该模块的 `assets.py` 中有定义；**目录里有同名 png 不代表可用**。
- `assets.py` 由 `dev_tools/assets_extract.py` 从 `image.json / click.json / ocr.json / swipe.json` 生成。手改 assets.py 时必须同步改 json，否则下次生成会被覆盖。
- 改动后跑一次全仓库引用扫描（用 Grep 工具，pattern `self\.(I|C|O|S)_[A-Z0-9_]+`），逐个核对是否有未定义名字。
- 教训：在临时脚本里手工 `RuleImage(...)` 验证通过，≠ 线上可用。名字必须真实存在于 assets.py。

## 6 修完的三件必做

1. `.\toolkit\python.exe -m py_compile <改动文件>`
2. **重启 OAS 进程**：常驻进程会缓存 `sys.modules` 与 assets 对象，改代码或素材后不重启不生效。出现「改了还是老行为 / 报旧错误」时，先看报错时间戳是否晚于进程启动时间。
3. 再看新日志确认行为变化；仍失败就重新从 §1 开始，不要在旧证据上继续推断。

## 7 临时文件纪律

调试脚本、临时截图放工作区外（如 `C:\Users\Administrator\Downloads\_oas_tmp`），不要留在仓库里；排查结束顺手清理仓库内的 `tmp_*.png` 之类残留。

## 附：本项目常用 API 语义

- `appear(img)`：只在 roi_back 内搜索，命中后把 roi_front 更新为命中位置。
- `appear_then_click(img)`：命中即点击。
- `ui_click(click, stop)`：反复点击 click，直到 stop 出现。
- `ui_click_until_disappear(click)`：反复点击 click 直到它不再出现；click 必须是 RuleImage（RuleClick 无法匹配）。
- 截图固定 1280×720，所有 roi 坐标基于该分辨率。
