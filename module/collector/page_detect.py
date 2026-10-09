from module.atom.image import RuleImage
from module.logger import logger
from tasks.GameUi.page import PageRegistry


class PageDetector:
    """基于 PageRegistry 的页面识别：按注册顺序匹配 check_button，只读不点击

    匹配阈值使用各 RuleImage 自带 threshold，与 ui_get_current_page 行为一致。
    """

    def __init__(self):
        # 静态导入所有 tasks/**/page.py，填充 PageRegistry（无需 GameUi 实例）
        from tasks.GameUi.game_ui import GameUi
        GameUi._import_all_pages()
        self.pages = PageRegistry.all()
        logger.attr('PageDetector', f'{len(self.pages)} pages loaded')

    @staticmethod
    def _check_buttons(page) -> list:
        buttons = page.check_button
        if isinstance(buttons, list):
            return buttons
        return [buttons]

    def detect(self, image):
        """
        Args:
            image: RGB ndarray 截图

        Returns:
            Page: 匹配到的页面；未匹配返回 None
        """
        for page in self.pages:
            for button in self._check_buttons(page):
                try:
                    if button.match(image):
                        return page
                except Exception:
                    # 单个模板缺失等异常不影响整体识别
                    continue
        return None
