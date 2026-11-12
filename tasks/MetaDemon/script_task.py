# This Python file uses the following encoding: utf-8
# 超鬼王（祸至无日）任务
# 流程：活动入口 -> 每日领取 -> 购买30勾玉礼包 -> 一星合成 -> 队伍预设 -> 召唤1~4星战斗循环
import re
from datetime import datetime, timedelta
from time import sleep

from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.RightActivity.right_activity import RightActivity
from tasks.GameUi.game_ui import GameUi
from tasks.MetaDemon.assets import MetaDemonAssets


class ScriptTask(GeneralBattle, RightActivity, GameUi, MetaDemonAssets):

    def run(self):
        self.md_run()
        self.set_next_run(task="MetaDemon", success=True)
        raise TaskEnd

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def md_run(self):
        self.md_enter_activity()
        self.md_claim_daily()
        self.md_buy_gift()
        self.md_craft_star1()
        self.md_setup_team()
        self.md_battle_loop()

    def md_enter_activity(self):
        logger.hr('超鬼王 进入活动', 2)
        timer = Timer(20).start()
        while 1:
            self.screenshot()
            if self.appear(self.I_MD_MAIN_TITLE):
                return
            if timer.reached():
                logger.warning('进入超鬼王活动界面超时')
                self.set_next_run(task="MetaDemon", success=False)
                raise TaskEnd
            if self.appear_then_click(self.I_MD_ACTIVITY_ICON, interval=1.5):
                continue
            # 活动图标不在可视区域时展开右侧活动栏
            if self.appear_then_click(self.I_TOGGLE_BUTTON, interval=1.5):
                continue
            sleep(0.5)

    def md_claim_daily(self):
        logger.hr('超鬼王 每日领取', 2)
        for _ in range(8):
            self.screenshot()
            # 领取后会弹出全屏「获得奖励」面板，先点右侧空白关掉
            if self.appear(self.I_UI_REWARD, threshold=0.6):
                self.ui_reward_appear_click()
                sleep(1)
                continue
            # 每日补给面板：首次进入才出现，已领取时只需关闭
            if self.appear(self.I_MD_SUPPLY_TITLE):
                self.click(self.C_MD_SUPPLY_CLOSE)
                sleep(1)
                continue
            if self.appear_then_click(self.I_MD_DAILY_RECEIVE, interval=1):
                sleep(1.2)
                continue
            break

    def md_buy_gift(self):
        logger.hr('超鬼王 购买每日30勾玉礼包', 2)
        self.md_wait_main()
        self.click(self.C_MD_GIFT)
        if not self.md_wait_shop(wait_time=6):
            logger.warning('未进入礼包界面，跳过购买')
            return
        last_limit = None
        for _ in range(6):
            self.screenshot()
            cur, total = self.md_shop_limit()
            if cur is not None and total and cur >= total:
                logger.info(f'礼包已买满 {cur}/{total}')
                break
            if last_limit is not None and (cur, total) == last_limit:
                logger.warning(f'购买后限购次数未变化（{cur}/{total}），停止购买')
                break
            last_limit = (cur, total)
            # 精确位置OCR确认是30勾玉的裂变之眼，其他礼包不买
            if not self.md_is_30_jade():
                logger.warning('未识别到30勾玉礼包，停止购买')
                break
            self.click(self.C_MD_BUY_30)
            sleep(0.8)
            self.click(self.C_MD_BUY_MAX)  # 数量拉到最大
            sleep(0.4)
            self.click(self.C_MD_BUY_CONFIRM)  # 确认购买
            sleep(1.5)
        # 购买成功会弹出「获得奖励」，先关掉再关商店
        for _ in range(3):
            self.screenshot()
            if not self.appear(self.I_UI_REWARD, threshold=0.6):
                break
            self.ui_reward_appear_click()
            sleep(1)
        self.click(self.C_MD_CLOSE)
        sleep(1)

    def md_craft_star1(self):
        logger.hr('超鬼王 一星裂变之眼合成', 2)
        self.md_wait_main()
        self.click(self.C_MD_CRAFT)
        if not self.wait_until_appear(self.I_MD_CRAFT_TITLE, wait_time=6):
            logger.warning('未进入合成界面，跳过合成')
            return
        prev_stock = None
        same_count = 0
        for _ in range(15):
            self.screenshot()
            if not self.appear(self.I_MD_CRAFT_ROW_1):
                # 合成结果弹窗可能还没关掉，补点一次再确认
                self.click(self.C_MD_CRAFT_RESULT)
                sleep(1)
                if not self.appear(self.I_MD_CRAFT_ROW_1):
                    break
            stock = self.md_wait_craft_stock(wait_time=6)
            if stock is None:
                logger.warning('一星持有数读取失败，停止合成')
                break
            if stock < 3:
                logger.info(f'一星裂变之眼剩余 {stock}，停止合成')
                break
            if prev_stock is not None and stock is not None and stock >= prev_stock:
                same_count += 1
                if same_count >= 2:
                    logger.warning(f'一星数量未减少（{stock}），可能合成券不足，停止合成')
                    break
            else:
                same_count = 0
            prev_stock = stock
            if not self.md_click_rule(self.I_MD_CRAFT_ROW_1):
                break
            sleep(0.8)  # 选中一星行后游戏会自动放入3个，不要再点一键卸载
            self.click(self.C_MD_CRAFT_START)
            sleep(1.8)
            self.click(self.C_MD_CRAFT_RESULT)  # 关闭合成结果弹窗
            sleep(1)
        self.click(self.C_MD_CLOSE_CRAFT)
        sleep(1)

    def md_setup_team(self):
        logger.hr('超鬼王 队伍预设', 2)
        self.md_wait_main()
        if not self.md_click_rule(self.I_MD_PRESET_ROW):
            logger.warning('未找到预设入口，跳过队伍设置')
            return
        if not self.wait_until_appear(self.I_MD_TEAM_TAB_ACTIVITY, wait_time=6):
            logger.warning('队伍面板未打开，跳过队伍设置')
            return
        self.md_click_rule(self.I_MD_TEAM_TAB_ACTIVITY)
        sleep(1)
        switched = False
        for _ in range(2):
            if not self.md_click_rule(self.I_MD_TEAM_FIRST):
                break
            sleep(1.2)
            if self.appear(self.I_UI_CONFIRM):
                self.click(self.I_UI_CONFIRM)
                switched = True
                sleep(1)
                break
        logger.info(f'御魂切换：{"弹窗已确认" if switched else "两次点击未见弹窗"}')
        # 队伍面板是主界面上的常驻侧栏，不需要关闭；后续"全部队列"可直接点在右侧栏上

    def md_battle_loop(self):
        logger.hr('超鬼王 召唤与战斗循环', 2)
        while 1:
            if not self.md_wait_main(timeout=30):
                logger.warning('战斗后未回到活动界面')
                self.set_next_run(task="MetaDemon", success=False)
                raise TaskEnd

            exhaustion = self.md_exhaustion()
            if exhaustion is not None and exhaustion >= 100:
                logger.info(f'疲劳度 {exhaustion} >= 100，6 小时后再运行')
                self.set_next_run(task="MetaDemon", success=True,
                                  target=datetime.now() + timedelta(hours=6), server=False)
                raise TaskEnd

            if not self.md_open_summon():
                logger.warning('未能打开召唤队列弹窗')
                self.set_next_run(task="MetaDemon", success=False)
                raise TaskEnd

            star = self.md_pick_star()
            if star is None:
                logger.info('召唤队列中已无 1~4 星裂变之眼，明天再打')
                target = (datetime.now() + timedelta(days=1)).replace(
                    hour=0, minute=10, second=0, microsecond=0)
                self.set_next_run(task="MetaDemon", success=True, target=target, server=False)
                raise TaskEnd

            logger.info(f'召唤 {star} 星裂变之眼')
            self.click(self.C_MD_SUMMON_NOW)
            sleep(2)
            # 召唤成功后鬼王出现在场景中，再点右下角「挑战」进入战斗
            if not self.wait_until_appear(self.I_MD_CHALLENGE, wait_time=10):
                logger.warning('召唤后未出现挑战按钮')
                self.set_next_run(task="MetaDemon", success=False)
                raise TaskEnd
            self.appear_then_click(self.I_MD_CHALLENGE)
            sleep(2)
            if self.wait_until_appear(self.I_MD_TEAM_BATTLE, wait_time=3):
                self.md_click_rule(self.I_MD_TEAM_BATTLE)
                sleep(2)

            if not self.run_general_battle(GeneralBattleConfig()):
                logger.warning('战斗失败，结束任务')
                self.set_next_run(task="MetaDemon", success=True)
                raise TaskEnd

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    def md_wait_main(self, timeout: int = 15) -> bool:
        # 队伍侧栏覆盖主界面时标题仍在左上角，所以标题可见即视为已回到主界面
        if self.wait_until_appear(self.I_MD_MAIN_TITLE, wait_time=timeout):
            return True
        return self.wait_until_appear(self.I_MD_MAIN_TITLE, wait_time=3, skip_first_screenshot=True)

    def md_open_summon(self) -> bool:
        if self.appear(self.I_MD_SUMMON_TITLE):
            return True
        for _ in range(3):
            self.click(self.C_MD_QUEUE)
            if self.wait_until_appear(self.I_MD_SUMMON_TITLE, wait_time=4):
                return True
        return False

    def md_pick_star(self):
        """点击队列最左侧的低/中星卡片（1~4星）；最左只剩 5/6 星时返回 None"""
        self.screenshot()
        image = self.device.image
        hits = []
        for rule, label in ((self.I_MD_CARD_LOW, '1~2星'),
                            (self.I_MD_CARD_MID, '3~4星'),
                            (self.I_MD_CARD_HIGH, '5~6星')):
            if rule.match(image):
                hits.append((rule.roi_front[0], rule, label))
        if not hits:
            return None
        left = min(item[0] for item in hits)
        for x, rule, label in hits:
            if x > left + 8:
                continue
            # 最左侧是 5/6 星，说明 1~4 星已耗尽
            if rule is self.I_MD_CARD_HIGH:
                return None
            self.click(rule)
            sleep(0.6)
            return label
        return None

    def md_is_30_jade(self) -> bool:
        """礼包价格OCR，必须含 "30" 才允许购买"""
        text = str(self.O_MD_SHOP_PRICE.ocr(self.device.image))
        return '30' in text

    def md_click_rule(self, rule) -> bool:
        self.screenshot()
        if not rule.match(self.device.image):
            return False
        self.click(rule)
        return True

    def md_exhaustion(self):
        self.screenshot()
        cu, res, total = self.O_MD_EXHAUSTION_NEW.ocr(self.device.image)
        # 只有完整读到 x/100 才采信，避免顶部栏被遮挡时误读成 0
        try:
            if int(total) != 100:
                return None
            return int(cu)
        except (TypeError, ValueError):
            return None

    def md_shop_limit(self):
        result = self.O_MD_SHOP_LIMIT.ocr(self.device.image)
        numbers = re.findall(r'(\d+)\s*/\s*(\d+)', str(result))
        if numbers:
            return int(numbers[0][0]), int(numbers[0][1])
        return None, None

    def md_wait_shop(self, wait_time: int = 6) -> bool:
        """礼包界面用OCR轮询判断（RuleOcr 未设 keyword 时 appear 恒为 False）"""
        timer = Timer(wait_time).start()
        while 1:
            self.screenshot()
            cur, total = self.md_shop_limit()
            if cur is not None and total:
                return True
            if timer.reached():
                return False
            sleep(0.4)

    def md_craft_stock(self):
        result = str(self.O_MD_CRAFT_STOCK.ocr(self.device.image))
        matched = re.search(r'[：:]\s*(\d+)', result)
        if matched:
            return int(matched.group(1))
        numbers = re.findall(r'\d+', result)
        if numbers:
            return int(numbers[-1])
        return None

    def md_wait_craft_stock(self, wait_time: int = 6):
        """合成动画期间数字会滚动读不到，轮询直到读到为止"""
        timer = Timer(wait_time).start()
        while 1:
            self.screenshot()
            stock = self.md_craft_stock()
            if stock is not None:
                return stock
            if timer.reached():
                return None
            sleep(0.4)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run()
