from module.atom.gif import RuleGif
from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr
from module.logger import logger
from tasks.GameUi.matcher import AllMatcher, AnyMatcher, AtomMatcher, Matcher, NotMatcher
from tasks.GameUi.page import PageRegistry


class PageDetector:
    """基于 PageRegistry 的只读页面识别

    页面条件由 Matcher 组合（RuleImage / RuleGif / RuleOcr / 自定义函数）。
    这里按静态截图求值，只处理图片类条件：
    - OCR 与自定义函数依赖运行时任务对象，标记为“未知”，不参与判断，避免逐帧 OCR 拖慢采集
    - 未命中任何页面返回 None
    """

    def __init__(self):
        # 扫描导入所有 tasks/*/page.py，填充 PageRegistry（无需 GameUi 实例）
        PageRegistry.load_all_pages()
        self.pages = PageRegistry.all()
        logger.attr('PageDetector', f'{len(self.pages)} pages loaded')

    def detect(self, image):
        """
        Args:
            image: RGB ndarray 截图

        Returns:
            Page: 匹配到的页面；未匹配返回 None
        """
        for page in self.pages:
            matcher = page.recognizer
            if matcher is None:
                continue
            try:
                if self._evaluate(matcher, image) is True:
                    return page
            except Exception:
                # 单个页面模板缺失等异常不影响整体识别
                continue
        return None

    def _evaluate(self, matcher: Matcher, image) -> bool | None:
        """三态求值：True 命中 / False 未命中 / None 无法判断（OCR、自定义函数）"""
        if isinstance(matcher, AtomMatcher):
            target = matcher.target
            if isinstance(target, (RuleImage, RuleGif)):
                return bool(target.match(image))
            if isinstance(target, RuleOcr):
                return None
            return None
        if isinstance(matcher, AnyMatcher):
            unknown = False
            for child in matcher.children:
                result = self._evaluate(child, image)
                if result is True:
                    return True
                if result is None:
                    unknown = True
            return None if unknown else False
        if isinstance(matcher, AllMatcher):
            unknown = False
            for child in matcher.children:
                result = self._evaluate(child, image)
                if result is False:
                    return False
                if result is None:
                    unknown = True
            return None if unknown else True
        if isinstance(matcher, NotMatcher):
            result = self._evaluate(matcher.child, image)
            return None if result is None else not result
        return None
