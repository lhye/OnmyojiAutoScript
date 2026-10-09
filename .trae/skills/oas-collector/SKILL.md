---
name: oas-collector
description: 阴阳师客户端交互监听与数据采集。当需要采集玩家的真实点击操作与对应画面变化（点击前后多帧截图、页面切换记录）来理解任务流程、分析页面流转或构建训练数据时使用本技能。通过独立命令行工具运行，数据落盘为结构化 JSONL + 截图。
---

# OAS Collector 客户端交互监听与数据采集

## 功能简介

通过 ADB 持续监听阴阳师客户端：

- **点击监听**：`adb shell getevent -lt` 流式捕获触摸按下事件与屏幕坐标（自动换算为 1280x720 逻辑坐标，原始面板坐标同时保留）
- **画面采集**：点击前画面来自滚动帧缓冲（约 0.4s/帧，回溯约 13 秒历史）；点击后立即 1 帧 + 最多 4 帧续拍（0.5s 间隔），帧差低于阈值判定动画结束提前停止
- **页面识别**：复用项目 PageRegistry（约 40+ 页面），持续识别当前页面并记录 page_change 事件
- **画面变化**：帧差超阈值时记录 scene_change 事件（10s 节流）

## 何时使用

- 需要理解玩家某个玩法的手动操作流程（点了哪里、画面如何变化、页面如何跳转）
- 需要为 AI agent 构建带视觉上下文的交互数据集
- 需要采集特定页面/按钮的样例截图

## 如何运行

```bash
# 持续采集（Ctrl+C 停止），使用配置 oas1 的设备
python collector.py --config oas1

# 采集 120 秒后自动停止，自定义截图间隔
python collector.py --config oas1 --duration 120 --interval 0.3

# 关闭页面识别（启动更快）
python collector.py --config oas1 --no-page-detect
```

参数：`--config` 配置名（./config/<name>.json，决定设备 serial）；`--duration` 秒，0=持续；`--interval` 截图间隔；`--base` 存储目录；`--no-page-detect` 关闭页面识别。

要求：设备为 adb tcp 连接（不支持 adb over http）；采集期间手动在模拟器/手机上操作即可。

## 数据产出

```
./log/collector/<session_ts>/
  events.jsonl                     # 事件流，每行一个 JSON
  clicks/<event_id>/
    before.png                     # 点击前画面（来自帧缓冲）
    after_00.png ... after_04.png  # 点击后多帧
    meta.json                      # 本次点击完整元数据
```

events.jsonl 事件类型：

| type | 关键字段 |
|---|---|
| click | event_id, x, y（1280x720 逻辑坐标）, x_raw/y_raw, ts_press, panel, page_before, page_after |
| page_change | page_before, page_after, frame_ts |
| scene_change | diff（帧差均值）, frame_ts |

meta.json 在 click 字段基础上追加：`before_ts` / `before_age_ms`（点击前帧龄）、`after_ts[]`（各帧时间戳）、`early_stop`（是否因画面稳定提前停止补帧）。

## Python API（模块化调用）

核心代码位于 `module/collector/`：

```python
from module.collector.collector import CollectorService
from module.collector.page_detect import PageDetector
from module.collector.task_loop import TaskLoop

# 1. 整体启停
service = CollectorService(config, interval=0.4)
service.start()
service.stop()
service.click(x, y)  # handler 中可向客户端注入点击

# 2. 单独页面识别（任意 RGB ndarray）
detector = PageDetector()
page = detector.detect(image)   # 返回 Page 对象或 None，page.name 为页面名

# 3. 优先级任务循环（按 priority 从小到大匹配，首个命中执行 handler）
loop = service.task_loop
loop.register(name='my_task', priority=10, matcher=some_rule_image, handler=lambda img: ...)
loop.start()
```

## 注意事项

- 截图与点击注入共用 `module/device` 设备层，采集期间不要同时运行 OAS 主调度（script.py）
- 坐标系：meta 中 `x/y` 为 1280x720 逻辑坐标（与项目 RuleImage roi 一致），`x_raw/y_raw` 为触摸面板原始值
- MuMu 触摸协议特殊：无 `BTN_TOUCH`，用 `ABS_MT_TRACKING_ID`（≥0 按下 / -1 抬起）标记起止；面板为竖屏 720x1280，映射到横屏需交换 XY 并翻转 Y（已自动处理，原始坐标始终保留可重映射）
- getevent 捕获的是"按下即采集"，不等待释放，`ts_release` 恒为 0
