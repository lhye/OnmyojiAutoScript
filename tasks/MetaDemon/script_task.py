# This Python file uses the following encoding: utf-8
# 超鬼王（祸至无日）任务
# 流程：活动入口 -> 每日领取 -> 购买30勾玉礼包 -> 一星合成 -> 队伍预设 -> 召唤1~4星战斗循环
import re
from datetime import datetime, timedelta
from time import sleep

import cv2
import numpy as np

from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.RightActivity.right_activity import RightActivity
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main
from tasks.MetaDemon.assets import MetaDemonAssets


class ScriptTask(GeneralBattle, RightActivity, GameUi, MetaDemonAssets):

    def run(self):
        self.md_goto_courtyard()
        self.md_run()
        self.set_next_run(task="MetaDemon", success=True)
        raise TaskEnd

    def md_goto_courtyard(self):
        """任务可能从战斗或其他活动页启动，先回庭院，超鬼王的入口只在庭院右侧栏"""
        self.screenshot()
        if self.appear(self.I_MD_MAIN_TITLE):
            return
        logger.hr('超鬼王 回到庭院', 2)
        try:
            self.goto_page(page_main)
        except Exception as e:  # noqa: BLE001
            logger.warning(f'回到庭院失败，继续尝试直接进入活动：{e}')

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
        timer = Timer(60).start()
        while 1:
            self.screenshot()
            if self.appear(self.I_MD_MAIN_TITLE):
                return
            if timer.reached():
                logger.warning('进入超鬼王活动界面超时')
                self.set_next_run(task="MetaDemon", success=False)
                raise TaskEnd
            # 庭院：右侧栏里已有超鬼王图标则直接点，一步进主界面
            if self.appear_then_click(self.I_MD_ACTIVITY_ICON, interval=1.5):
                continue
            # 庭院：点「活动」进入活动总览
            if self.appear_then_click(self.I_ACT_LIST_EXPAND, interval=1.5):
                continue
            # 活动总览：点「前往活动」
            if self.appear_then_click(self.I_ACT_LIST_GOTO_ACT, interval=1.5):
                continue
            # 活动大厅立绘：点左侧「祸主降临」活动名进入（点击位置取模板命中区域）
            if self.appear_then_click(self.I_MD_LOBBY_ENTER, interval=1.5):
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
        if not self.appear_then_click(self.I_MD_GIFT_ICON):
            logger.warning('未找到礼包入口，跳过购买')
            return
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
        self.screenshot()
        if self.md_shop_appear():
            self.click(self.C_MD_CLOSE)
            sleep(1)

    def md_craft_star1(self):
        logger.hr('超鬼王 一星裂变之眼合成', 2)
        self.md_wait_main()
        if not self.appear_then_click(self.I_MD_CRAFT_ICON):
            logger.warning('未找到合成入口，跳过合成')
            return
        if not self.wait_until_appear(self.I_MD_CRAFT_TITLE, wait_time=6):
            logger.warning('未进入合成界面，跳过合成')
            return
        self.screenshot()
        ticket = self.md_craft_ticket()
        if ticket == 0:
            # 券为 0 时点开始合成会让游戏直接跳到宠梦礼包，随后所有主界面识别都会超时
            logger.info('合成券为 0，跳过合成')
            self.md_close_craft()
            return
        # 列表会记住上次滚动位置，先拉回顶部，保证第一行是一星
        for _ in range(2):
            self.device.swipe(p1=(300, 180), p2=(300, 420), duration=(0.3, 0.4))
            sleep(0.5)
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
            self.screenshot()
            if not self.appear(self.I_MD_CRAFT_TITLE):
                # 券不足时游戏直接跳到宠梦礼包，合成界面已经不在了
                logger.warning('点开始合成后离开了合成界面（合成券不足），关闭礼包页')
                self.click(self.C_MD_CLOSE)
                sleep(1)
                break
            self.click(self.C_MD_CRAFT_RESULT)  # 关闭合成结果弹窗
            sleep(1)
        self.md_close_craft()

    def md_close_craft(self):
        self.screenshot()
        if not self.appear(self.I_MD_CRAFT_TITLE):
            return
        self.click(self.C_MD_CLOSE_CRAFT)
        # 右侧图标会透过半透明合成面板显示，必须等标题消失才算真正关闭
        timer = Timer(5).start()
        while 1:
            self.screenshot()
            if not self.appear(self.I_MD_CRAFT_TITLE):
                break
            if timer.reached():
                break
            sleep(0.5)
        sleep(0.5)

    def md_setup_team(self):
        logger.hr('超鬼王 队伍预设', 2)
        self.md_wait_main()
        # 合成界面关闭有动画，预设行可能晚一点才出现，轮询等待
        if not self.wait_until_appear(self.I_MD_PRESET_ROW, wait_time=10):
            logger.warning('未找到预设入口，跳过队伍设置')
            return
        self.click(self.I_MD_PRESET_ROW)
        if not self.wait_until_appear(self.I_MD_TEAM_TAB_ACTIVITY, wait_time=6):
            logger.warning('队伍面板未打开，跳过队伍设置')
            return
        # 分类标签用 OCR 定位「活动」：模板会误匹配御魂/英杰/契灵等外形相同的标签
        self.screenshot()
        area = self.O_MD_TEAM_TAB_ACT.ocr(self.device.image)
        if not area or area[2] <= 0:
            logger.warning('未识别到「活动」分类标签，跳过队伍设置')
            return
        x, y, w, h = area
        self.device.click(x + w // 2, y + h // 2, control_name='md_team_tab_activity')
        sleep(1)
        switched = False
        for _ in range(2):
            # 第一队行内文字会随日期变化（【Day1】/【Day2】群体阵容），用固定点点击
            self.click(self.C_MD_TEAM_FIRST)
            # 点完必须重新截图轮询，appear 用的是缓存图，会漏掉后弹出来的确认框
            if self.wait_until_appear(self.I_UI_CONFIRM, wait_time=3):
                self.appear_then_click(self.I_UI_CONFIRM)
                switched = True
                sleep(1)
                break
        logger.info(f'御魂切换：{"弹窗已确认" if switched else "两次点击未见弹窗"}')
        # 队伍面板是主界面上的常驻侧栏，不需要关闭；后续"全部队列"可直接点在右侧栏上

    def md_battle_loop(self):
        logger.hr('超鬼王 召唤与战斗循环', 2)
        while 1:
            if not self.md_return_main():
                logger.warning('战斗后未回到活动界面')
                self.set_next_run(task="MetaDemon", success=False)
                raise TaskEnd

            exhaustion = self.md_exhaustion()
            if exhaustion is not None and exhaustion >= 100:
                logger.info(f'疲劳度 {exhaustion} >= 100，1 小时后再运行')
                self.set_next_run(task="MetaDemon", success=True,
                                  target=datetime.now() + timedelta(hours=1), server=False)
                raise TaskEnd

            # 场上已有自己发现的鬼王时，右侧栏的「全部队列」会被「挑战」取代，直接打它
            self.screenshot()
            if not self.appear(self.I_MD_CHALLENGE):
                if not self.md_open_summon():
                    logger.warning('未能打开召唤队列弹窗')
                    self.set_next_run(task="MetaDemon", success=False)
                    raise TaskEnd

                star = self.md_pick_star()
                if star is None:
                    logger.info('召唤队列中已无 1~4 星裂变之眼，明天 10 点再打')
                    target = (datetime.now() + timedelta(days=1)).replace(
                        hour=10, minute=0, second=0, microsecond=0)
                    self.set_next_run(task="MetaDemon", success=True, target=target, server=False)
                    raise TaskEnd

                logger.info(f'召唤 {star} 星裂变之眼')
                if not self.appear_then_click(self.I_MD_SUMMON_NOW):
                    logger.warning('召唤队列里没找到「立即召唤」按钮')
                    self.set_next_run(task="MetaDemon", success=False)
                    raise TaskEnd
                sleep(2)
                if not self.wait_until_appear(self.I_MD_CHALLENGE, wait_time=10):
                    logger.warning('召唤后未出现挑战按钮')
                    self.set_next_run(task="MetaDemon", success=False)
                    raise TaskEnd
            else:
                logger.info('场上已有自己发现的鬼王，直接挑战')
            for _ in range(3):
                self.screenshot()
                if not self.appear(self.I_MD_BOOST_ON):
                    break
                logger.info('战斗前取消 2.5 倍伤害')
                self.click(self.I_MD_BOOST_ON)
                sleep(1)
            self.screenshot()
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

    def md_return_main(self, timeout: int = 25) -> bool:
        """战斗后回到活动主界面。
        通用战斗结算可能停在奖励/补给/礼包等残留面板上，先逐个关掉再等标题出现"""
        timer = Timer(timeout).start()
        while 1:
            self.screenshot()
            if self.appear(self.I_MD_MAIN_TITLE):
                return True
            if timer.reached():
                return False
            if self.appear(self.I_UI_REWARD, threshold=0.6):
                self.ui_reward_appear_click()
                sleep(1)
                continue
            if self.appear(self.I_MD_SUPPLY_TITLE):
                self.click(self.C_MD_SUPPLY_CLOSE)
                sleep(1)
                continue
            if self.md_shop_appear():
                logger.info('战斗后停在礼包页，关闭')
                self.click(self.C_MD_CLOSE)
                sleep(1)
                continue
            # 不认识的残留结算页：点底部「点击屏幕继续」区域推进
            self.click(self.C_CONTINUE_PROMPT, interval=1.5)
            sleep(0.5)

    def md_shop_appear(self) -> bool:
        """礼包页识别：能读到「限购 x/y 次」即视为礼包页"""
        text = str(self.O_MD_SHOP_LIMIT.ocr(self.device.image))
        return bool(re.search(r'\d+\s*/\s*\d+', text))

    def _battle_finish_check(self) -> bool:
        # 超鬼王打完会回到活动主界面，标题可见即可结束通用结算的盲点等待
        return self.appear(self.I_MD_MAIN_TITLE)

    def md_open_summon(self) -> bool:
        self.screenshot()
        if self.appear(self.I_MD_SUMMON_TITLE):
            return True
        for _ in range(3):
            # 战斗结束回主界面后侧栏图标是淡入的，先轮询等图标出现再点（每轮都会重新截图）
            if not self.wait_until_appear_then_click(self.I_MD_QUEUE_ICON, wait_time=8):
                logger.info(f'没等到召唤队列图标（得分 {self.I_MD_QUEUE_ICON.last_score:.3f}）')
                return False
            if self.wait_until_appear(self.I_MD_SUMMON_TITLE, wait_time=4):
                return True
        return False

    def md_pick_star(self):
        """点队列最左侧的低/中星卡片（1~4星）；最左只剩 5/6 星时返回 None"""
        self.screenshot()
        image = self.device.image
        cards = []
        for rule, label in ((self.I_MD_CARD_LOW, '1~2星'),
                            (self.I_MD_CARD_MID, '3~4星'),
                            (self.I_MD_CARD_HIGH, '5~6星')):
            for x, y, w, h, score in self._match_all(rule, image):
                cards.append((x, y, w, h, score, label))
        if not cards:
            return None
        # 同一张卡可能被多档命中，按 x 聚成一张卡，取分数最高的那档作为它的星级
        cards.sort(key=lambda c: c[0])
        groups = []
        for card in cards:
            if groups and card[0] - groups[-1][0][0] <= 45:
                groups[-1].append(card)
            else:
                groups.append([card])
        x, y, w, h, score, label = max(groups[0], key=lambda c: c[4])
        # 最左侧是 5/6 星，说明 1~4 星已耗尽
        if label == '5~6星':
            logger.info('队列最左侧是 5~6 星卡片，停止召唤')
            return None
        self.device.click(x + w // 2, y + h // 2, control_name='md_pick_star')
        sleep(0.6)
        return label

    @staticmethod
    def _match_all(rule, image, threshold: float = None):
        """返回模板在 roi_back 内的全部命中 (x, y, w, h, score)，按 x 升序。
        rule.match 每次只给一个最优命中，选「最左」时会把倒数第二张卡当成最左"""
        th = rule.threshold if threshold is None else threshold
        x1, y1, w1, h1 = rule.roi_back
        crop = image[y1:y1 + h1, x1:x1 + w1]
        template = rule.image
        th_tpl, tw_tpl = template.shape[:2]
        if crop.shape[0] < th_tpl or crop.shape[1] < tw_tpl:
            return []
        res = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= th)
        hits = [(int(x1 + x), int(y1 + y), tw_tpl, th_tpl, float(res[y, x]))
                for y, x in zip(ys, xs)]
        # 去重：同一张卡附近只保留最高分
        hits.sort(key=lambda h: -h[4])
        kept = []
        for hit in hits:
            if all(abs(hit[0] - k[0]) > hit[2] // 2 or abs(hit[1] - k[1]) > hit[3] // 2 for k in kept):
                kept.append(hit)
        kept.sort(key=lambda h: h[0])
        return kept

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

    def md_craft_ticket(self):
        """合成券数量，读不到返回 None"""
        text = str(self.O_MD_CRAFT_TICKET.ocr(self.device.image))
        matched = re.search(r'[：:]\s*(\d+)', text)
        if matched:
            return int(matched.group(1))
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
