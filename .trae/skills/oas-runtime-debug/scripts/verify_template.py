#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""模板匹配验证工具(必须用 OAS 自带解释器运行, 系统 python 缺依赖)。

用法:
    toolkit\\python.exe .trae/skills/oas-runtime-debug/scripts/verify_template.py \
        <image 或 image 目录> <template.png> [--roi x,y,w,h] [--threshold 0.8]

- 不给 --roi: 全图搜索, 用于判断"这个模板在整个画面上是否会出现"
- 给 --roi: 按 RuleImage.roi_back 语义搜索, 与线上 OAS 的判断完全一致
- 目录作为输入时会遍历其下所有 png, 便于评估误匹配率

输出每张图的最高分与命中位置, 以及 HIT / miss 结论。
"""
import argparse
import os
import sys

import cv2


def iter_images(path):
    if os.path.isdir(path):
        for name in sorted(os.listdir(path)):
            if name.lower().endswith(('.png', '.jpg', '.jpeg')):
                yield os.path.join(path, name)
    else:
        yield path


def parse_roi(text):
    parts = [int(v) for v in text.split(',')]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError('roi 需要 4 个整数: x,y,w,h')
    return parts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('images', help='截图文件或目录')
    parser.add_argument('template', help='模板 png 路径')
    parser.add_argument('--roi', type=parse_roi, default=None, help='搜索区域 x,y,w,h, 对应 roi_back')
    parser.add_argument('--threshold', type=float, default=0.8)
    args = parser.parse_args()

    tpl = cv2.imread(args.template)
    if tpl is None:
        sys.exit(f'模板读取失败: {args.template}')

    for path in iter_images(args.images):
        img = cv2.imread(path)
        if img is None:
            print(f'{os.path.basename(path)}: 读取失败')
            continue
        ox, oy = 0, 0
        if args.roi:
            x, y, w, h = args.roi
            img = img[y:y + h, x:x + w]
            ox, oy = x, y
        if img.size == 0:
            print(f'{os.path.basename(path)}: roi 越界')
            continue
        res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        flag = 'HIT' if max_val > args.threshold else 'miss'
        print(f'{os.path.basename(path)}: {max_val:.4f} {flag} at {ox + max_loc[0]},{oy + max_loc[1]}')


if __name__ == '__main__':
    main()
