import argparse
import time

from module.config.config import Config
from module.logger import logger


def main():
    parser = argparse.ArgumentParser(description='OAS 客户端交互监听与数据采集（供 AI agent 使用）')
    parser.add_argument('--config', type=str, default='oas1', help='用户配置名，对应 ./config/<name>.json')
    parser.add_argument('--duration', type=int, default=0, help='采集时长（秒），0 表示持续运行')
    parser.add_argument('--interval', type=float, default=0.4, help='截图间隔（秒）')
    parser.add_argument('--base', type=str, default='./log/collector', help='数据存储目录')
    parser.add_argument('--no-page-detect', action='store_true', help='关闭页面识别')
    args = parser.parse_args()

    logger.set_file_logger(f'collector_{args.config}')
    logger.hr('OAS Collector', level=1)

    from module.collector.collector import CollectorService
    service = CollectorService(
        config=Config(args.config),
        interval=args.interval,
        base=args.base,
        enable_page_detect=not args.no_page_detect,
    )
    service.start()
    try:
        start_time = time.time()
        while True:
            time.sleep(1)
            if args.duration > 0 and time.time() - start_time >= args.duration:
                logger.info(f'Duration {args.duration}s reached')
                break
    except KeyboardInterrupt:
        logger.info('KeyboardInterrupt received')
    finally:
        service.stop()


if __name__ == '__main__':
    main()
