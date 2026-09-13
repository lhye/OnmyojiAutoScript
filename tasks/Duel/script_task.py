# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from time import sleep

import random
from datetime import time, datetime, timedelta

from module.logger import logger
from module.exception import TaskEnd
from module.base.timer import Timer

from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.SwitchOnmyoji.switch_onmyoji import SwitchOnmyoji
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_duel, page_onmyodo, random_click
from tasks.Duel.config import Duel
from tasks.Duel.assets import DuelAssets
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.page import page_main, page_shikigami_records

""" 斗技 """


class ScriptTask(GameUi, GeneralBattle, SwitchSoul, DuelAssets, SwitchOnmyoji):
    battle_win_count = 0
    battle_lose_count = 0
    current_score = 0
    pre_battle_win_cnt = battle_win_count
    pre_battle_lose_cnt = battle_lose_count
    is_celeb: bool = False  # 是否是名仕
    conf: Duel = None
    _result_ocr_timer = None  # 结算banner胜负OCR的节流计时器(universal_judge_result用)

    def run(self):
        current_time = datetime.now().time()
        if not (time(12, 00) <= current_time < time(23, 00)):
            self.set_next_run(task='Duel', success=True, finish=False)
            raise TaskEnd('Duel')
        self.conf = self.config.duel
        limit_time = self.conf.duel_config.limit_time
        self.limit_time: timedelta = timedelta(hours=limit_time.hour, minutes=limit_time.minute,
                                               seconds=limit_time.second)
        self.prepare_duel()
        while True:
            self.screenshot()
            self.check_and_get_reward()
            if not self.duel_main():
                self.ui_goto_page(page_duel)
                continue
            if not self.can_start_duel():
                break
            self.start_duel()
        logger.info('Duel battle end')
        self.set_next_run(task='Duel', success=True, finish=True)
        self.ui_goto_page(page_main)
        # 调起花合战
        self.set_next_run(task='TalismanPass', target=datetime.now())
        raise TaskEnd('Duel')

    def prepare_duel(self):
        """斗技准备工作(切换御魂or阴阳师...), 最后回到斗技主界面"""
        self.ui_goto_page(page_main)
        self.switch_soul()
        if self.conf.duel_config.switch_enabled:
            self.ui_goto_page(page_onmyodo)
            self.switch_onmyoji(self.conf.duel_config.switch_onmyoji)
        self.ui_goto_page(page_duel)
        self.switch_all_soul()
        self.current_score = self.conf.duel_celeb_config.initial_score

    def can_start_duel(self) -> bool:
        """是否可以运行斗技"""
        # 任务执行时间超过限制时间，退出
        if datetime.now() - self.start_time >= self.limit_time:
            logger.info('Duel task is over time')
            return False
        # 当前分数跟目标分数比较, 判断分数是否已经满足条件
        if self.get_and_update_cur_score() >= self.conf.duel_config.target_score:
            logger.info('Duel task is over score')
            return False
        # 若不开启名仕战斗, 则到达名士直接退出
        if not self.conf.duel_celeb_config.celeb_battle and self.is_celeb:
            logger.info('You are already a celeb（名仕）')
            return False
        # 练习
        if self.appear(self.I_BATTLE_WITH_TRAIN) or self.appear(self.I_BATTLE_WITH_TRAIN2):
            return False
        # 荣誉满了，退出
        if self.conf.duel_config.honor_full_exit and self.check_honor():
            logger.info('Duel task is over honor')
            return False
        return True

    def start_duel(self):
        """进行一次斗技"""
        logger.hr('Duel battle', 2)
        self.current_count += 1
        self.enter_battle()
        self.battle_prepare()
        battle_ret = self.wait_battle()
        if battle_ret:
            self.pre_battle_win_cnt = self.battle_win_count
            self.battle_win_count += 1
        else:
            self.pre_battle_lose_cnt = self.battle_lose_count
            self.battle_lose_count += 1
        task_run_time_seconds = timedelta(seconds=int((datetime.now() - self.start_time).total_seconds()))
        logger.info(f'battle result: {battle_ret}')
        logger.info(f'battle count:{self.current_count} | win:{self.battle_win_count} failure:{self.battle_lose_count}')
        logger.info(f'battle time: {task_run_time_seconds} / {self.limit_time}')
        self.ui_goto_page(page_duel)

    def enter_battle(self):
        """点击开始战斗(一直到出现战斗准备界面)"""
        logger.hr('duel battle matching')
        while not self.is_in_battle_prepare():
            self.screenshot()
            # 战斗按钮
            self.ui_click_until_disappear(self.I_D_BATTLE, interval=1.2)
            self.ui_click_until_disappear(self.I_D_BATTLE2, interval=1.2)
            # 战斗带保护的按钮
            self.ui_click_until_disappear(self.I_D_BATTLE_PROTECT, interval=1.2)

    def battle_prepare(self):
        """选式神准备斗技阶段"""
        logger.hr('duel battle preparing')
        not_in_prepare_cnt, max_retry = 0, 3
        while True:
            if not_in_prepare_cnt >= max_retry:  # max_retry次识别不到任何阶段元素(准备,战斗,结算), 退出
                break
            self.screenshot()
            if self.is_battle_end() or self.is_in_real_battle():  # 战斗已经结束或已经开始战斗
                break
            if not self.is_in_battle_prepare():  # 一般不会出现这种情况(不在准备,战斗,结束界面), 但是处理一下
                not_in_prepare_cnt += 1
                sleep(random.uniform(1.2, 2.4))
                continue
            not_in_prepare_cnt = 0
            # 再次检查是否是名仕(若斗技主界面识别名仕失效的话)
            if self.appear_then_click(self.I_BAN, interval=1.2):
                self.is_celeb = True
                continue
            # 名仕不开启自动上阵, 根据最后一个式神的名字是否改变来检查自己式神是否被ban
            if not self.appear(self.I_D_CHECK_BAN, interval=0.8) and self.is_celeb:
                ocr_name = self.O_D_BAN_NAME.ocr(self.device.image)
                shikigami_banned = ocr_name != '' and not any(
                    char in ocr_name for char in self.conf.duel_celeb_config.ban_name)
                logger.info(f'Check self shikigami is banned:{shikigami_banned}')
                if shikigami_banned:
                    self.duel_exit_battle()
                    continue
                self.click(self.C_DUEL_CLICK_5, interval=random.uniform(0.7, 1.4))
                sleep(random.uniform(1.5, 3))  # 降低点击频率和ocr识别频率
                continue
            # 点击自动上阵或准备
            if self.appear_then_click(self.I_D_AUTO_ENTRY, interval=1.2) or \
                    self.appear_then_click(self.I_D_PREPARE, interval=1.2):
                self.reset_device('PREPARE_BEFORE_BATTLE')

    def wait_battle(self) -> bool:
        """等待战斗结束, 返回战斗结果, 最后会退出到斗技主界面"""
        logger.hr('duel battle waiting')
        battle_operated = False
        battle_timeout_timer = Timer(270).start()
        ret_timer = Timer(5)
        battle_timeout_cnt, max_timeout_cnt = 0, 3
        ret = None
        while True:
            self.screenshot()
            self.check_and_get_reward()
            if self.appear(self.I_CHECK_DUEL, interval=0.6) and self.appear(self.I_D_HELP, interval=0.6):  # 斗技主界面
                break
            if self.appear_then_click(self.I_UI_BACK_RED, interval=1.2):  # 关闭段位上升页面
                ret_timer.reset()
                continue
            if ret_timer.started() and ret_timer.reached():  # 兜底逻辑, 已经结算了但是还没有到斗技主界面
                self.ui_goto_page(page_duel)
                break
            if self._universal_battle and ret is None and not self._universal_battle_running():
                # 通用主题: 鬼火消失=战斗结束。结算banner需点击才消失, 点击后可能经过领奖画面(胜利也可能没有), 最终回斗技主界面
                result = self.universal_judge_result()
                if result is not None:
                    ret = result
                    ret_timer.start()
                    logger.info(f'Duel battle result: {"win" if ret else "lose"} (universal)')
                else:
                    # 胜负未识别(如特殊banner样式): 盲点banner推进, 点出领奖画面时下轮判胜
                    self._universal_click_banner(count=1, delay=0.5)
            if self._universal_battle and ret is not None:
                # 已判定胜负: 盲点推进结算画面(按name全局节流1.5s, 低频), 回到斗技主界面后由上方条件break
                self.click(random_click(ltrb=(True, True, False, True)), interval=1.5)
                continue
            if ret is None and self.is_battle_win():
                ret = True
                ret_timer.start()
                self.click(random_click(ltrb=(True, True, False, True)), interval=1.2)
                continue
            if ret is None and self.is_battle_lose():
                ret = False
                ret_timer.start()
                self.click(random_click(ltrb=(True, True, False, True)), interval=1.2)
                continue
            if battle_timeout_cnt >= max_timeout_cnt:
                logger.warning('Duel battle timeout[>15 minutes], exit')
                self.duel_exit_battle()
                continue
            if ret is None and not battle_operated:  # 进行战斗前的操作
                self.ui_click(self.O_D_HAND, self.O_D_AUTO, interval=0.8)
                self.green_mark(self.conf.duel_config.green_enable, self.conf.duel_config.green_mark)
                battle_operated = True
                self.reset_device('BATTLE_STATUS_S')
                continue
            if battle_timeout_timer.reached_and_reset():
                battle_timeout_cnt += 1
                self.reset_device('BATTLE_STATUS_S')
                logger.warning("battle' time is too long, increase wait time")
        return ret

    def duel_exit_battle(self):
        was_in_battle = False
        banner_clicks = 0
        while 1:
            self.screenshot()
            if self._universal_battle:
                # 通用战斗主题: 撤退确认弹窗(公共资产)+按位置点退出; 战斗结束后失败横幅需点击才消失
                if self.appear_then_click(self.I_EXIT_ENSURE, interval=1.2):
                    was_in_battle = True
                    continue
                if self._click_exit():
                    was_in_battle = True
                    continue
                if was_in_battle:
                    # 鬼火消失=战斗已结束, 盲点失败横幅后返回
                    if not self._universal_battle_running() and banner_clicks < 3:
                        banner_clicks += 1
                        self._universal_click_banner(count=1, delay=1)
                    return
                # 未进入战斗(名士ban选等): 斗技专属退出按钮
                if self.appear_then_click(self.I_DUEL_EXIT, interval=1):
                    continue
                if self.appear(self.I_D_CHECK_BAN):
                    continue
                # 点击退出后确认框弹出有延迟, 此时三个元素均不可见; 提前return会让确认框残留,
                # 上层battle_prepare在遮挡下盲点导致GameTooManyClickError, 故短轮询确认框点掉后再返回
                ensure_timer = Timer(3).start()
                while not ensure_timer.reached():
                    self.screenshot()
                    if self.appear_then_click(self.I_EXIT_ENSURE, interval=1.2):
                        break
                return
            if self.appear(self.I_D_FAIL) or self.appear(self.I_FALSE):
                return
            if self.appear_then_click(self.I_EXIT_ENSURE):
                continue
            # 选式神界面退出或战斗内退出
            if self.appear_then_click(self.I_DUEL_EXIT, interval=1) or self.appear_then_click(self.I_EXIT, interval=1):
                continue

    def check_honor(self) -> bool:
        """检查荣誉是否满了"""
        if not self.appear(self.I_DUEL_HONOR):
            return False
        roi_x = self.I_DUEL_HONOR.roi_front[0] + self.I_DUEL_HONOR.roi_front[2]
        roi_y = self.I_DUEL_HONOR.roi_front[1]
        roi_w = 110
        roi_h = self.I_DUEL_HONOR.roi_front[3]
        self.O_D_HONOR.roi = [roi_x, roi_y, roi_w, roi_h]
        current, remain, total = self.O_D_HONOR.ocr(self.device.image)
        return current == total and remain == 0

    def get_and_update_cur_score(self, skip_screenshot: bool = True) -> int:
        """
        获取并更新当前斗技分数, 要求处于斗技主界面, 同时更新名仕状态
        :param skip_screenshot: 是否跳过截图
        :return: 当前斗技分数
        """
        self.maybe_screenshot(skip_screenshot)
        score = self.current_score
        self.is_celeb = False
        # 名士界面无积分数字显示, 非名士界面无名士标识: 二者必居其一
        # 两者皆空说明页面转场淡入未完成(page arrived后0.6s截图星星未渲染, 曾导致误判非名士而开打)
        # 因此轮询等待二者其一命中(上限10s), 而非固定sleep(模拟器速度不可控)
        wait_timer = Timer(10).start()
        while not wait_timer.reached():
            if self.appear(self.I_D_CELEB_STAR) or self.appear(self.I_D_CELEB_HONOR):
                self.is_celeb = True
                break
            score, remain, total = self.O_D_SCORE.ocr(self.device.image)
            if score != 0:
                break
            sleep(0.5)
            self.screenshot()
        if self.is_celeb:
            if self.battle_win_count - self.pre_battle_win_cnt == 1:
                self.pre_battle_win_cnt = self.battle_win_count
                score += 100
            elif self.battle_lose_count - self.pre_battle_lose_cnt == 1:
                self.pre_battle_lose_cnt = self.battle_lose_count
                score -= 100
        else:
            if score > 10000:
                # 识别错误分数超过一万, 去掉最高位
                logger.warning('Recognition error, score is too high')
                score = int(str(score)[1:])
        logger.info(f'battle score: {score}')
        self.current_score = score
        return self.current_score

    def switch_soul(self):
        """从式神录界面切换御魂"""
        if self.conf.switch_soul.enable:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul(self.conf.switch_soul.switch_group_team)
        if self.conf.switch_soul.enable_switch_by_name:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul_by_name(self.conf.switch_soul.group_name, self.conf.switch_soul.team_name)

    def duel_main(self, screenshot=False) -> bool:
        """判断是否在斗技主界面"""
        if screenshot:
            self.screenshot()
        return self.appear(self.I_D_HELP) or self.appear(self.I_CHECK_DUEL) or \
            self.appear(self.I_D_CELEB_STAR) or self.appear(self.I_D_CELEB_HONOR)

    def switch_all_soul(self):
        """在斗技式神备选界面一键切换所有御魂"""
        if not self.conf.duel_config.switch_all_soul:
            return
        click_count = 0  # 计数
        while 1:
            self.screenshot()
            if click_count >= 3:
                break
            if self.appear_then_click(self.I_D_TEAM, interval=1):
                continue
            if self.appear_then_click(self.I_UI_CONFIRM, interval=0.6):
                continue
            if self.appear_then_click(self.I_D_TEAM_SWTICH, interval=1):
                click_count += 1
                continue
        logger.info('Souls Switch is complete')
        self.ui_click(self.I_UI_BACK_YELLOW, self.I_D_TEAM)

    def check_and_get_reward(self):
        """检查并收获奖励"""
        if self.appear(self.I_REWARD, interval=0.6) or self.appear(self.I_UI_REWARD, interval=0.6):
            self.click(random_click(ltrb=(True, True, False, True)))
            logger.info('get reward')

    def is_in_battle_prepare(self, skip_screenshot=True) -> bool:
        """是否在战斗准备界面"""
        self.maybe_screenshot(skip_screenshot)
        return self.appear(self.I_D_PREPARE) or \
            self.appear(self.I_D_AUTO_ENTRY) or \
            self.appear(self.I_BAN) or \
            self.appear(self.I_D_WORD_BATTLE) or \
            self.appear(self.I_D_CHECK_BAN)

    def is_battle_win(self) -> bool:
        if self._universal_battle:
            # 通用战斗主题: 领奖画面(公共资产)出现必为胜利; 注意胜利也可能没有领奖画面(由universal_judge_result兜底)
            return self.appear(self.I_REWARD, threshold=0.6) or self.appear(self.I_REWARD_GOLD, threshold=0.8)
        return self.appear(self.I_WIN) or self.appear(self.I_D_VICTORY)

    def is_battle_lose(self) -> bool:
        if self._universal_battle:
            # 通用战斗主题: 下一局的准备房间里鬼火必然不可见, "鬼火消失+准备界面"不能作为失败依据
            # (会让battle_prepare误判战斗已结束而不点准备); 失败由结算banner的OCR在wait_battle内判定
            return False
        return self.appear(self.I_FALSE) or self.appear(self.I_D_FAIL)

    def universal_judge_result(self):
        """通用战斗主题的斗技结算判定(鬼火消失后调用):
        结算流程: 鬼火消失 -> 胜/败banner(需点击才消失) -> 可能经过领奖画面(胜利也可能没有) -> 回到斗技主界面
        - 领奖画面出现 -> 胜利
        - 领奖未出现时OCR识别banner上的"胜利/失败"文字(1秒节流, 仅结算阶段识别, 非逐帧)
        :return: True=胜, False=败, None=未识别
        """
        if self.appear(self.I_REWARD, threshold=0.6) or self.appear(self.I_REWARD_GOLD, threshold=0.8):
            return True
        if self._result_ocr_timer is None:
            self._result_ocr_timer = Timer(1).start()
        elif not self._result_ocr_timer.reached():
            return None
        else:
            self._result_ocr_timer = Timer(1).start()
        if self.ocr_appear(self.O_D_RESULT_WIN):
            return True
        if self.ocr_appear(self.O_D_RESULT_LOSE):
            return False
        return None

    def is_battle_end(self) -> bool:
        return self.is_battle_win() or self.is_battle_lose() or \
            self.appear(self.I_REWARD) or self.appear(self.I_UI_REWARD)

    def reset_device(self, status: str):
        self.device.click_record_clear()
        self.device.stuck_record_clear()
        self.device.stuck_record_add(status)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas3')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run()
