# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from enum import Enum, auto
from time import sleep
from datetime import datetime, timedelta
import cv2
import numpy as np
import random
from typing import Any
from cached_property import cached_property

from module.atom.image import RuleImage
from module.atom.click import RuleClick
from module.atom.ocr import RuleOcr
from module.base.protect import random_sleep
from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger

from tasks.base_task import BaseTask
from tasks.Component.GeneralBattle.battle_wait import battle_wait_strategy
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.ActivityShikigami.assets import ActivityShikigamiAssets
from tasks.ActivityShikigami.config import SwitchSoulConfig, GeneralBattleConfig, ActivityShikigami
from tasks.Component.BaseActivity.base_activity import BaseActivity
from tasks.Component.BaseActivity.config_activity import GeneralClimb
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.game_ui import GameUi
import tasks.Component.GeneralBattle.config_general_battle
import tasks.ActivityShikigami.page as game


def _prepare_image_for_ocr(image: np.ndarray, asset: RuleOcr) -> np.ndarray:
    image_copy = image.copy()
    x, y, w, h = asset.roi
    roi_to_process = image_copy[y:y + h, x:x + w]
    if len(roi_to_process.shape) == 3:
        gray_image = cv2.cvtColor(roi_to_process, cv2.COLOR_BGR2GRAY)
    else:
        gray_image = roi_to_process
    # 自适应二值化
    _, binary_norm = cv2.threshold(gray_image, 127, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    _, binary_inv = cv2.threshold(gray_image, 127, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    if cv2.countNonZero(binary_norm) < cv2.countNonZero(binary_inv):
        binary_correct = binary_norm
    else:
        binary_correct = binary_inv
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 1))
    dilated_image = cv2.dilate(binary_correct, kernel, iterations=1)
    # 找轮廓
    contours, _ = cv2.findContours(dilated_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    processed_roi_content = None
    if contours:
        all_points = np.concatenate(contours, axis=0)
        bx, by, bw, bh = cv2.boundingRect(all_points)
        processed_roi_content = binary_correct[by:by + bh, bx:bx + bw]
    centered_roi = np.full((h, w), 255, dtype=np.uint8)  # 255代表白色
    if processed_roi_content is not None:
        content_h, content_w = processed_roi_content.shape
        if content_h <= h and content_w <= w:
            # 计算居中粘贴的位置，放到中间
            start_y = (h - content_h) // 2
            start_x = (w - content_w) // 2
            paste_area = centered_roi[start_y:start_y + content_h, start_x:start_x + content_w]
            paste_area[processed_roi_content == 255] = 0
        else:
            logger.warning(f"Content for asset '{asset.name}' is larger than ROI. Skipping centering.")
            # 内容过大，直接使用原始二值图的反转作为结果
            centered_roi = cv2.bitwise_not(binary_correct)
    else:
        logger.warning(f"No content found in ROI for asset: {asset.name}. ROI will be blank.")
    processed_roi_bgr = cv2.cvtColor(centered_roi, cv2.COLOR_GRAY2BGR)
    image_copy[y:y + h, x:x + w] = processed_roi_bgr
    return image_copy


class LimitTimeOut(Exception):
    pass


class LimitCountOut(Exception):
    pass


class StateMachine(BaseTask):
    run_idx: int = 0  # 当前爬塔类型

    @cached_property
    def conf(self) -> GeneralClimb:
        return self.config.model.activity_shikigami

    @property
    def climb_type(self) -> str:
        if self.run_idx >= len(self.conf.general_climb.run_sequence_v):
            return self.conf.general_climb.run_sequence_v[-1]
        return self.conf.general_climb.run_sequence_v[self.run_idx]

    # ----------------------------------------------------
    def put_status(self):
        """
        更新全局状态
        """

        def get_count(self) -> int:
            # current_count由run_general_battle每次战斗自增, switch_next切换类型时归零
            # (原count_map从未自增导致次数限制永不生效)
            return self.current_count

        def get_limit(self) -> int:
            limit = getattr(self.conf.general_climb, f'{self.climb_type}_limit', 0)
            return 0 if not limit else limit

        # 超过运行时间
        if self.limit_time is not None and datetime.now() - self.start_time >= self.limit_time:
            logger.info(f"Climb type {self.climb_type} time out")
            raise LimitTimeOut
        # 次数达到限制
        if get_count(self) >= get_limit(self):
            logger.info(f"Climb type {self.climb_type} count limit reached")
            raise LimitCountOut

    def switch_next(self):
        """
        切换下一种爬塔类型
        :return: True 切换成功 or False
        """
        self.run_idx += 1
        if self.run_idx >= len(self.conf.general_climb.run_sequence_v):
            logger.info('All climbing activities have been completed')
            return False
        # 切换爬塔类型了, 恢复所有状态
        self.current_count = 0
        logger.hr(f'Climb switch to {self.climb_type}', 2)
        return True


class ScriptTask(StateMachine, GameUi, BaseActivity, SwitchSoul, ActivityShikigamiAssets):
    """
    更新前请先看 ./README.md
    """

    def run(self) -> None:
        self.limit_time: timedelta = self.conf.general_climb.limit_time_v
        #
        for climb_type in self.conf.general_climb.run_sequence_v:
            self.ui_get_current_page()
            try:
                if climb_type == 'boss':
                    # 炼石成金首领: 入口在活动主界面左下
                    self.ui_goto(game.page_act_main)
                    self._run_boss()
                else:
                    # 进入到亗地回响地图
                    self.ui_goto(game.page_map)
                    # 合战派遣(有空位才派, 每日一次, 已满直接跳过)
                    self.hezhan_dispatch()
                    # 清结算提示并进入虚无精锐准备页
                    self._enter_battle_page()
                    method_func = getattr(self, f'_run_{climb_type}')
                    method_func()
            except LimitCountOut as e:
                # 不在此处盲点返回: 结算动画未结束时点击无效, 曾卡死导致boss轮永不执行(2026-09-19实锤)
                # 下一轮循环的ui_goto(page_map)/_run_boss自带导航, 会从当前页面可靠抵达
                pass
            except LimitTimeOut as e:
                break
            finally:
                # 切换下一个爬塔类型
                self.switch_next()

        # 返回庭院
        logger.hr("Exit Shikigami", 2)
        self.ui_get_current_page(False)
        self.ui_goto(game.page_main)
        if self.conf.general_climb.active_souls_clean:
            self.set_next_run(task='SoulsTidy', success=False, finish=False, target=datetime.now())
        self.set_next_run(task="ActivityShikigami", success=True)
        raise TaskEnd

    def _run_pass(self):
        """
            更新前请先看 ./README.md
        """
        logger.hr(f'Start run climb type PASS', 1)
        self.switch_soul(self.I_BATTLE_MAIN_TO_RECORDS, self.I_CHECK_BATTLE_MAIN)
        self.switch_climb_mode_in_game('pass')

        ocr_limit_timer = Timer(1).start()
        click_limit_timer = Timer(4).start()
        while 1:
            self.screenshot()
            self.put_status()
            # --------------------------------------------------------------
            if self.appear_then_click(self.I_GIFT_CLOSE, interval=1.5):
                logger.info('Gift package popup closed')
                continue
            if (self.appear_then_click(self.I_UI_CONFIRM, interval=0.5)
                    or self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=0.5)):
                continue
            if self.ui_reward_appear_click():
                continue
            if not ocr_limit_timer.reached():
                continue
            ocr_limit_timer.reset()
            if not self.appear(self.I_FIRE):
                continue
            #  --------------------------------------------------------------
            self.lock_team(self.conf.general_battle)
            if not self.check_tickets_enough():
                logger.warning(f'No tickets left, wait for next time')
                break
            if self.conf.general_climb.random_sleep:
                random_sleep(probability=0.2)
            if self.start_battle():
                continue

        self.ui_click(self.I_UI_BACK_YELLOW, stop=self.I_CHECK_MAP, interval=4.5)

    def _run_ap(self):
        """
            更新前请先看 ./README.md
        """
        logger.hr(f'Start run climb type AP')
        self.switch_soul(self.I_BATTLE_MAIN_TO_RECORDS, self.I_CHECK_BATTLE_MAIN)
        self.switch_climb_mode_in_game('ap')

        ocr_limit_timer = Timer(1).start()
        while 1:
            self.screenshot()
            self.put_status()
            # --------------------------------------------------------------
            # 礼包弹窗优先关闭: 盖住挑战按钮导致O_FIRE永远识别不到, 且此时点其他位置可能误购
            if self.appear_then_click(self.I_GIFT_CLOSE, interval=1.5):
                logger.info('Gift package popup closed')
                continue
            if not ocr_limit_timer.reached():
                continue
            ocr_limit_timer.reset()
            if not self.appear(self.I_FIRE):
                self.appear_then_click(self.I_CHECK_BATTLE_MAIN, interval=4)
                continue
            #  --------------------------------------------------------------
            self.lock_team(self.conf.general_battle)
            if not self.check_tickets_enough():
                logger.warning(f'No tickets left, wait for next time')
                break
            if self.conf.general_climb.random_sleep:
                random_sleep(probability=0.2)
            if self.start_battle():
                continue

        self.ui_click(self.I_UI_BACK_YELLOW, stop=self.I_CHECK_MAP, interval=4.5)

    def _run_boss(self):
        """炼石成金首领: 活动主界面左下入口, 点挑战直接开打(x12票), 支持切换御魂+次数限制"""
        logger.hr(f'Start run climb type BOSS')
        # 上一轮(ap/pass)结束画面可能在虚无精锐准备页/结算画面, 先导航回活动主界面再点入口
        self.ui_goto(game.page_act_main)
        self.ui_click(self.I_GOTO_GOLD_BOSS, stop=self.I_CHECK_GOLD_BOSS, interval=2)
        self.switch_soul(self.I_BATTLE_MAIN_TO_RECORDS, self.I_CHECK_GOLD_BOSS)

        ocr_limit_timer = Timer(1).start()
        ocr_fail = 0  # boss页OCR连续失败计数(镜像帧判定)
        while 1:
            self.screenshot()
            self.put_status()
            # --------------------------------------------------------------
            if self.appear_then_click(self.I_GIFT_CLOSE, interval=1.5):
                logger.info('Gift package popup closed')
                continue
            if (self.appear_then_click(self.I_UI_CONFIRM, interval=0.5)
                    or self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=0.5)):
                continue
            if self.ui_reward_appear_click():
                continue
            if not ocr_limit_timer.reached():
                continue
            ocr_limit_timer.reset()
            if not self.appear(self.I_BOSS_FIRE):
                # nemu_ipc在boss界面的游戏surface带额外变换, 原始帧180度倒, OAS仅flip上下后
                # 剩左右镜像, OCR读倒字(实锤: "挑战"被读成"机战", 2026-09-19)。
                # 帧镜像不影响ADB点击坐标(屏幕实际显示是正的), 连续失败后改固定坐标点击
                ocr_fail += 1
                if ocr_fail == 3:
                    logger.warning('Boss fire OCR keep failing, probably mirrored nemu frame, fallback to fixed click')
                if ocr_fail >= 3:
                    self.click(self.C_BOSS_FIRE, interval=2)
                continue
            ocr_fail = 0
            #  --------------------------------------------------------------
            if not self.check_tickets_enough():
                logger.warning(f'No boss tickets left, wait for next time')
                break
            if self.conf.general_climb.random_sleep:
                random_sleep(probability=0.2)
            if self.start_battle(check_image=self.I_CHECK_GOLD_BOSS, fire=self.I_BOSS_FIRE, wait_strategy='default'):
                continue

        self.ui_click(self.I_UI_BACK_YELLOW, stop=self.I_CHECK_MAIN, interval=4.5)

    def _run_ap100(self):
        """
        拾光永恒活动无100体爬塔, 旧配置序列兼容用
        """
        logger.hr(f'Start run climb type AP100')
        logger.warning(f'climb type [ap100] is not supported in this activity, skip')

    def hezhan_dispatch(self):
        """合战派遣: 地图上存在空余上阵位时, 依次派遣阴阳师(每日一次, 无空位直接跳过)
        上阵按钮金/灰同结构仅亮度不同: 金色(正式派遣)才点, 灰色(1/12时低档)点加号提档, 提满仍灰则放弃"""
        if not self.conf.general_climb.hezhan_dispatch:
            return
        if not self.appear(self.I_DEPLOY_PLUS):
            logger.info('Hezhan dispatch: no empty slot, skip')
            return
        logger.hr('Hezhan dispatch', 2)
        timeout_timer = Timer(150).start()
        select_timer = Timer(0).start()  # 点+号后: 窗口内点卡位等选人面板出现
        deploy_timer = Timer(0).start()  # 上阵后: 合战动画期, 界面整体关闭回地图
        done_timer = None  # 全部完成复查计时(防弹窗关闭动画竞态误判)
        plus_count = 0  # 灰色提档加号点击次数
        while 1:
            self.screenshot()
            if timeout_timer.reached():
                logger.warning('Hezhan dispatch timeout')
                break
            # 通用弹窗(含合战派遣奖励的白石晶宝箱弹窗)
            if self.appear_then_click(self.I_UI_CONFIRM, interval=1) or \
                    self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=1):
                continue
            if self.ui_reward_appear_click():
                continue
            if self.appear_then_click(self.I_CHEST_CLOSE, interval=1.5):
                logger.info('Hezhan reward chest popup closed')
                continue
            if self.appear_then_click(self.I_SUPPLY_CLOSE, interval=1.5):
                logger.info('Hezhan daily supply popup closed')
                continue
            if self.appear_then_click(self.I_GIFT_CLOSE, interval=1.5):
                logger.info('Hezhan gift package popup closed')
                continue
            # 派遣面板已开: 按钮亮度区分金/灰, 只点金色正式派遣
            if self.appear(self.I_DEPLOY):
                if self.I_DEPLOY.match_brightness(self.device.image, threshold=0.7, roi=self.I_DEPLOY.roi_front):
                    # click返回False表示处于interval冷却期未实际点击
                    if self.click(self.I_DEPLOY, interval=2):
                        logger.info('Hezhan onmyoji deployed, wait interface close')
                        deploy_timer = Timer(5).start()  # 每派一个界面整体关闭回地图, 动画约3s
                        plus_count = 0
                else:
                    # 灰色低档: 点加号提档直到变金, 11次(满12档)后仍灰则放弃
                    if plus_count >= 11:
                        logger.warning('Hezhan deploy still gray after max plus, give up dispatch')
                        self.click(self.C_MAP_CLOSE)
                        break
                    self.click(self.C_HEZHAN_PLUS, interval=1)
                    plus_count += 1
                continue
            # 上阵后合战动画期: 界面整体关闭, 弹窗由上方分支处理, 此处只等待
            if not deploy_timer.reached():
                continue
            # 选择栏/面板操作窗口期: 点第一个阴阳师卡位直到面板出现
            if not select_timer.reached():
                self.click(self.C_HEZHAN_FIRST, interval=1.5)
                continue
            # 地图无空余上阵位: 派遣全部完成
            # 复查3秒防竞态: 宝箱弹窗关闭动画中+号短暂被遮, 立即判完成会漏派
            if self.appear(self.I_DEPLOY_PLUS):
                done_timer = None
            elif done_timer is None:
                done_timer = Timer(3).start()
            elif done_timer.reached():
                logger.info('Hezhan dispatch all done')
                break
            # 地图有空位: 点+号重新进入派遣选人画面
            if self.appear_then_click(self.I_DEPLOY_PLUS, interval=2.5):
                select_timer = Timer(5).start()
                plus_count = 0
                continue

    def _enter_battle_page(self):
        """从亗地回响地图进入虚无精锐准备页:
        结算提示遮挡时盲点空白区域, 直到虚无精锐标签出现再点击进入"""
        logger.hr('Enter boss battle page', 2)
        timeout_timer = Timer(60).start()
        blank_timer = Timer(3).start()
        while 1:
            self.screenshot()
            if timeout_timer.reached():
                logger.warning('Enter boss battle page timeout')
                break
            # 到达boss准备页
            if self.appear(self.I_CHECK_BATTLE_MAIN):
                logger.info('Arrive boss battle page')
                break
            # 通用弹窗优先(含合战派遣奖励的白石晶宝箱弹窗)
            if self.appear_then_click(self.I_UI_CONFIRM, interval=1) or \
                    self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=1):
                continue
            if self.ui_reward_appear_click():
                continue
            if self.appear_then_click(self.I_CHEST_CLOSE, interval=1.5):
                logger.info('Reward chest popup closed')
                blank_timer.reset()
                continue
            if self.appear_then_click(self.I_SUPPLY_CLOSE, interval=1.5):
                logger.info('Daily supply popup closed')
                blank_timer.reset()
                continue
            if self.appear_then_click(self.I_GIFT_CLOSE, interval=1.5):
                logger.info('Gift package popup closed')
                blank_timer.reset()
                continue
            # 虚无精锐标签出现: 点击进入
            if self.appear_then_click(self.I_BOSS_LABEL, interval=3):
                continue
            # 结算提示遮挡: 盲点空白区域直到标签出现
            if blank_timer.reached():
                self.click(self.C_MAP_BLANK, interval=1.5)
                blank_timer.reset()

    def start_battle(self, check_image: RuleImage = None, fire: RuleImage = None, wait_strategy: str = 'activity'):
        check_image = check_image if check_image is not None else self.I_CHECK_BATTLE_MAIN
        fire = fire if fire is not None else self.I_FIRE
        click_times, max_times = 0, random.randint(4, 8)
        while 1:
            self.screenshot()
            # 战斗内或战斗准备界面(虚无精锐大鼓"准备"页): 交给run_general_battle处理
            # 该准备界面I_CHECK_BATTLE_MAIN不命中, 不跳出会在此空转直到GameStuck(2026-09-16实测)
            if self.is_in_battle(False) or self.is_in_prepare(False):
                break
            if click_times >= max_times:
                logger.warning(f'Climb {self.climb_type} cannot enter, maybe already end, try next')
                return
            if self.appear_then_click(self.I_GIFT_CLOSE, interval=1.5):
                logger.info('Gift package popup closed')
                continue
            if (self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=1) or
                    self.appear_then_click(self.I_UI_CONFIRM, interval=1) ):
                continue
            if (self.appear(check_image, interval=1)) \
                    and self.appear_then_click(fire, interval=2):
                click_times += 1
                logger.info(f'Try click fire, remain times[{max_times - click_times}]')
                continue
        # 运行战斗
        if wait_strategy == 'default':
            # boss(炼石成金)结算是金色鱼专属画面, 无"获得奖励"横幅(I_UI_REWARD),
            # activity策略的success/failure钩子全不命中且无盲点/超时兜底, 会永久空转在奖励界面(2026-09-19实锤)
            # default策略: 鬼火消失->盲点推进->I_REWARD/I_REWARD_GOLD领奖判定, 静态实测boss奖励画面命中0.987/0.992
            with battle_wait_strategy(success='default'):
                self.run_general_battle(config=self.get_general_battle_conf())
        else:
            self.run_general_battle(config=self.get_general_battle_conf())

    @battle_wait_strategy(success='activity')
    def battle_wait(self, *args, **kwargs):
        return self.battle_wait_with_strategy(*args, **kwargs)

    def switch_soul(self, enter_button: RuleImage, cur_img: RuleImage):
        conf = self.conf.switch_soul_config
        enable_switch = getattr(conf, f"enable_switch_{self.climb_type}", False)
        enable_by_name = getattr(conf, f"enable_switch_{self.climb_type}_by_name", False)
        if not enable_switch and not enable_by_name:
            return
        logger.hr('Start switch soul', 2)
        conf.validate_switch_soul()
        self.ui_click(enter_button, stop=self.I_CHECK_RECORDS, interval=1)
        if enable_by_name:
            group, team = getattr(conf, f"{self.climb_type}_group_team_name").split(",")
            self.run_switch_soul_by_name(group, team)
        elif enable_switch:
            group_team = getattr(conf, f"{self.climb_type}_group_team")
            self.run_switch_soul(group_team)
        self.ui_click(self.I_UI_BACK_YELLOW, stop=cur_img, interval=1)

    def switch_climb_mode_in_game(self, mode: str = 'ap'):
        map_check = {
            'ap': self.I_CLIMB_MODE_AP,
            'pass': self.I_CLIMB_MODE_PASS,
        }
        logger.info(f'Switch climb mode to {mode}')
        self.ui_click(self.I_CLIMB_MODE_SWITCH, stop=map_check[mode], interval=1.9)

    def lock_team(self, battle_conf: GeneralBattleConfig):
        """
        根据配置判断当前爬塔类型是否锁定阵容, 并执行锁定或解锁
        """
        enable_preset = getattr(battle_conf, f"enable_{self.climb_type}_preset", False)
        if not enable_preset:
            logger.info(f'Lock {self.climb_type} team')
            self.ui_click(self.I_UNLOCK, stop=self.I_LOCK, interval=1.5)
            return
        logger.info(f'Unlock {self.climb_type} team')
        self.ui_click(self.I_LOCK, stop=self.I_UNLOCK, interval=1.5)

    def check_tickets_enough(self) -> bool:
        """
        判断当前爬塔门票是否足够
        :return: True 可以运行 or False
        """
        logger.hr(f'Check {self.climb_type} tickets')
        fire = self.I_BOSS_FIRE if self.climb_type == 'boss' else self.I_FIRE
        if not self.wait_until_appear(fire, wait_time=3):
            logger.warning(f'Detect fire fail, try reidentify')
            return False
        self.screenshot()
        remain_times = 0
        if self.climb_type == 'pass':
            remain_times = self.O_REMAIN_PASS.ocr_digit(self.device.image)
        if self.climb_type == 'ap':
            remain_times = self.O_REMAIN_AP.ocr_digit(self.device.image)
        if self.climb_type == 'boss':
            remain_times = self.O_BOSS_REMAIN.ocr_digit(self.device.image)
        return remain_times > 0

    def get_general_battle_conf(self) -> tasks.Component.GeneralBattle.config_general_battle.GeneralBattleConfig:
        from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig as gbc
        self.conf.validate_switch_preset()
        enable_preset = getattr(self.conf.general_battle, f'enable_{self.climb_type}_preset', False)
        group, team = getattr(self.conf.switch_soul_config, f'{self.climb_type}_group_team').split(',')
        return gbc(lock_team_enable=not enable_preset,
                   preset_enable=enable_preset,
                   preset_group=group if enable_preset else 1,
                   preset_team=team if enable_preset else 1,
                   green_enable=getattr(self.conf.general_battle, f'enable_{self.climb_type}_green', False),
                   green_mark=getattr(self.conf.general_battle, f'{self.climb_type}_green_mark'),
                   random_click_swipt_enable=getattr(self.conf.general_battle, f'enable_{self.climb_type}_anti_detect',
                                                     False), )

    def random_reward_click(self, exclude_click: list = None, click_now: bool = True) -> RuleClick:
        """
        随机点击
        :param exclude_click: 排除的点击位置
        :param click_now: 是否立即点击
        :return: 随机的点击位置
        """
        options = [self.C_RANDOM_LEFT, self.C_RANDOM_RIGHT, self.C_RANDOM_TOP, self.C_RANDOM_BOTTOM]
        if exclude_click:
            options = [option for option in options if option not in exclude_click]
        target = random.choice(options)
        if click_now:
            self.click(target, interval=1.8)
        return target


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run()


