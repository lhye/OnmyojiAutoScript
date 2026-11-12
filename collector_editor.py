import argparse
import sys

from module.collector.editor import run


def main():
    parser = argparse.ArgumentParser(description='OAS 采集序列标注编辑器')
    parser.add_argument('--base', type=str, default='./log/collector', help='采集数据目录')
    parser.add_argument('--session', type=str, default=None, help='直接打开指定会话（目录名）')
    args = parser.parse_args()
    sys.exit(run(base=args.base, session=args.session))


if __name__ == '__main__':
    main()
