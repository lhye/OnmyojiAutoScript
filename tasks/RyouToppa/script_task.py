# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
from datetime import datetime, timedelta, time as dt_time
import random

from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.RyouToppa.assets import RyouToppaAssets
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.config_base import ConfigBase, Time
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_realm_raid, page_main, page_kekkai_toppa, page_shikigami_records
from tasks.RealmRaid.assets import RealmRaidAssets
from tasks.Component.GeneralBattle.battle_wait import battle_wait_strategy

from module.logger import logger
from module.exception import TaskEnd
from module.atom.image_grid import ImageGrid
from module.base.utils import point2str
from module.base.timer import Timer
from module.exception import GamePageUnknownError



area_map = (
    {
        "fail_sign": (RyouToppaAssets.I_AREA_1_IS_FAILURE_NEW, RyouToppaAssets.I_AREA_1_IS_FAILURE),
        "rule_click": RyouToppaAssets.C_AREA_1,
        "finished_sign": (RyouToppaAssets.I_AREA_1_FINISHED, RyouToppaAssets.I_AREA_1_FINISHED_NEW, RyouToppaAssets.I_AREA_1_FINISHED_V3)
    },
    {
        "fail_sign": (RyouToppaAssets.I_AREA_2_IS_FAILURE_NEW, RyouToppaAssets.I_AREA_2_IS_FAILURE),
        "rule_click": RyouToppaAssets.C_AREA_2,
        "finished_sign": (RyouToppaAssets.I_AREA_2_FINISHED, RyouToppaAssets.I_AREA_2_FINISHED_NEW, RyouToppaAssets.I_AREA_2_FINISHED_V3)
    },
    {
        "fail_sign": (RyouToppaAssets.I_AREA_3_IS_FAILURE_NEW, RyouToppaAssets.I_AREA_3_IS_FAILURE),
        "rule_click": RyouToppaAssets.C_AREA_3,
        "finished_sign": (RyouToppaAssets.I_AREA_3_FINISHED, RyouToppaAssets.I_AREA_3_FINISHED_NEW, RyouToppaAssets.I_AREA_3_FINISHED_V3)
    },
    {
        "fail_sign": (RyouToppaAssets.I_AREA_4_IS_FAILURE_NEW, RyouToppaAssets.I_AREA_4_IS_FAILURE),
        "rule_click": RyouToppaAssets.C_AREA_4,
        "finished_sign": (RyouToppaAssets.I_AREA_4_FINISHED, RyouToppaAssets.I_AREA_4_FINISHED_NEW, RyouToppaAssets.I_AREA_4_FINISHED_V3)
    },
    {
        "fail_sign": (RyouToppaAssets.I_AREA_5_IS_FAILURE_NEW, RyouToppaAssets.I_AREA_5_IS_FAILURE),
        "rule_click": RyouToppaAssets.C_AREA_5,
        "finished_sign": (RyouToppaAssets.I_AREA_5_FINISHED, RyouToppaAssets.I_AREA_5_FINISHED_NEW, RyouToppaAssets.I_AREA_5_FINISHED_V3)
    },
    {
        "fail_sign": (RyouToppaAssets.I_AREA_6_IS_FAILURE_NEW, RyouToppaAssets.I_AREA_6_IS_FAILURE),
        "rule_click": RyouToppaAssets.C_AREA_6,
        "finished_sign": (RyouToppaAssets.I_AREA_6_FINISHED, RyouToppaAssets.I_AREA_6_FINISHED_NEW, RyouToppaAssets.I_AREA_6_FINISHED_V3)
    },
    {
        "fail_sign": (RyouToppaAssets.I_AREA_7_IS_FAILURE_NEW, RyouToppaAssets.I_AREA_7_IS_FAILURE),
        "rule_click": RyouToppaAssets.C_AREA_7,
        "finished_sign": (RyouToppaAssets.I_AREA_7_FINISHED, RyouToppaAssets.I_AREA_7_FINISHED_NEW, RyouToppaAssets.I_AREA_7_FINISHED_V3)
    },
    {
        "fail_sign": (RyouToppaAssets.I_AREA_8_IS_FAILURE_NEW, RyouToppaAssets.I_AREA_8_IS_FAILURE),
        "rule_click": RyouToppaAssets.C_AREA_8,
        "finished_sign": (RyouToppaAssets.I_AREA_8_FINISHED, RyouToppaAssets.I_AREA_8_FINISHED_NEW, RyouToppaAssets.I_AREA_8_FINISHED_V3)
    }
)


def random_delay(min_value: float = 1.0, max_value: float = 2.0, decimal: int = 1):
    """
    生成一个指定范围内的随机小数
    """
    random_float_in_range = random.uniform(min_value, max_value)
    return (round(random_float_in_range, decimal))

class ScriptTask(GeneralBattle, GameUi, SwitchSoul, RyouToppaAssets):
    medal_grid: ImageGrid = None
    # 区域列表单行高度(px): area1~8点击y间距约131, 滑动按整行移动以保持8个ROI与卡片对位
    AREA_ROW_HEIGHT: int = 131
    # 向上滑动的最大次数, 防止没有更多目标时无限滑
    AREA_LIST_MAX_PAGES: int = 10

    def run(self):
        """
        执行
        :return:
        """
        ryou_config = self.config.ryou_toppa
        time_limit: Time = ryou_config.raid_config.limit_time
        time_delta = timedelta(hours=time_limit.hour, minutes=time_limit.minute, seconds=time_limit.second)
        self.medal_grid = ImageGrid([RealmRaidAssets.I_MEDAL_5, RealmRaidAssets.I_MEDAL_4, RealmRaidAssets.I_MEDAL_3,
                                     RealmRaidAssets.I_MEDAL_2, RealmRaidAssets.I_MEDAL_1, RealmRaidAssets.I_MEDAL_0])

        if ryou_config.switch_soul_config.enable:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul(ryou_config.switch_soul_config.switch_group_team)

        if ryou_config.switch_soul_config.enable_switch_by_name:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul_by_name(ryou_config.switch_soul_config.group_name, ryou_config.switch_soul_config.team_name)

        self.ui_get_current_page()
        self.ui_goto(page_kekkai_toppa)
        ryou_toppa_start_flag = True
        ryou_toppa_success_penetration = False
        ryou_toppa_admin_flag = False
        # 点击突破
        while 1:
            self.screenshot()
            if self.appear_then_click(RealmRaidAssets.I_REALM_RAID, interval=1):
                continue
            if self.appear(self.I_REAL_RAID_REFRESH, threshold=0.8):
                if self.appear_then_click(self.I_RYOU_TOPPA, interval=1):
                    continue
            # 攻破阴阳寮，说明寮突已开，则退出
            elif self.appear(self.I_SUCCESS_PENETRATION, threshold=0.8):
                ryou_toppa_start_flag = True
                ryou_toppa_success_penetration = True
                break
            # 出现选择寮突说明寮突未开
            elif self.appear(self.I_SELECT_RYOU_BUTTON, threshold=0.8):
                ryou_toppa_start_flag = False
                ryou_toppa_admin_flag = True
                break
            # 出现晴明说明寮突未开
            elif self.appear(self.I_NO_SELECT_RYOU, threshold=0.8):
                ryou_toppa_start_flag = False
                break
            # 出现寮奖励， 说明寮突已开
            elif self.appear(self.I_RYOU_REWARD, threshold=0.8) or self.appear(self.I_RYOU_REWARD_90, threshold=0.8):
                ryou_toppa_start_flag = True
                break

        logger.attr('ryou_toppa_start_flag', ryou_toppa_start_flag)
        logger.attr('ryou_toppa_success_penetration', ryou_toppa_success_penetration)
        # 寮突未开 并且有权限， 开开寮突，没有权限则标记失败
        if not ryou_toppa_start_flag:
            if ryou_config.raid_config.ryou_access and ryou_toppa_admin_flag:
                # 作为寮管理，开启今天的寮突
                logger.info("As the manager of the ryou, try to start ryou toppa.")
                self.start_ryou_toppa()
            else:
                logger.info("The ryou toppa is not open and you are a ryou member.")
                self.set_next_run(task='RyouToppa', finish=True, server=True, success=False)
                raise TaskEnd

        # 100% 攻破, 第二天再执行
        if ryou_toppa_success_penetration:
            logger.info('RyouToppa is 100%')
            self.plan_tomorrow_ryoutoppa()
            raise TaskEnd
        if self.config.ryou_toppa.general_battle_config.lock_team_enable:
            logger.info("Lock team.")
            self.ui_click(self.I_TOPPA_UNLOCK_TEAM, self.I_TOPPA_LOCK_TEAM)
        else:
            logger.info("Unlock team.")
            self.ui_click(self.I_TOPPA_LOCK_TEAM, self.I_TOPPA_UNLOCK_TEAM)
        # --------------------------------------------------------------------------------------------------------------
        # 开始突破: 完成1次战斗后回到选择界面重新扫描重算index;
        # 选中的区域进不了战斗(目标被寮友打掉等)时游标+1选下一个;
        # 当前页8个都点完仍进不去战斗, 就点住列表往上滑, 继续点后面的目标;
        # 滑到底仍没有任何能进战斗的目标才视为任务结束, 不再刷新对手
        # --------------------------------------------------------------------------------------------------------------
        success = True
        need_scan = True   # 首次进入/每次战斗结束后重新扫描
        cursor = 0
        tried = set()      # 当前页已尝试过但进不了战斗的区域
        page = 0           # 已向上滑动的页数(0=列表顶部)
        futile_round = 0   # 整个列表都进不了战斗的轮数(异常态, 与"已无目标"区分)
        while 1:
            self.screenshot()
            # 阈值0.8: 个人突破页对 breakthrough记录徽章有~0.7假分, 0.6会误放行
            if not self.appear(self.I_TOPPA_RECORD, threshold=0.8):
                # 战斗结束后可能回落到个人突破页(点"个人"页签所在界面), 点"阴阳寮"页签回寮突破页
                self.appear_then_click(self.I_RYOU_TOPPA, interval=3)
                continue
            # 设置长任务标志,用来寻找寮突可进攻的目标
            self.device.stuck_record_add('PREPARE_BEFORE_BATTLE')
            if not self.has_ticket():
                logger.info("We have no chance to attack. Try again after 1 hour.")
                success = False
                break
            if self.current_count >= ryou_config.raid_config.limit_count:
                logger.warning("We have attacked the limit count.")
                break
            if datetime.now() >= self.start_time + time_delta:
                logger.warning("We have attacked the limit time.")
                break
            if need_scan:
                # 重新识别当前页8个区域状态(跳过已击破/攻略失败/本页已试过), 计算可攻打的区域
                index = self.scan_area(exclude=tried)
                if index == -1:
                    # 当前页没有可打目标: 点住列表往上滑, 继续找后面的目标
                    if page < self.AREA_LIST_MAX_PAGES and self.swipe_area_list():
                        logger.info(f'No attackable area in page {page + 1}, swipe up to next page')
                        page += 1
                        tried.clear()
                        cursor = 0
                        continue
                    # 已滑到底(或列表不能滑动): 回到顶部再确认一轮, 仍无可打目标才结束
                    futile_round += 1
                    if page == 0 or futile_round >= 2:
                        logger.info('All areas are finished or futile, task complete')
                        break
                    logger.info(f'No attackable area in whole list, wait 10s and rescan ({futile_round}/2)')
                    time.sleep(10)
                    self.rewind_area_list(page)
                    page = 0
                    tried.clear()
                    cursor = 0
                    continue
                cursor = index
                need_scan = False
            # 进攻
            res = self.attack_area(cursor)
            if res is None:
                # attack_area每次会点1-2次"进攻", 多个区域累计会超过device的"同一按钮10次"守卫,
                # 这里是按区域有界推进的探测, 不是死循环, 清空点击记录避免误报GameTooManyClickError
                self.device.click_record_clear()
                tried.add(cursor)
                # 无法进战斗: 游标+1直接试下一个区域
                cursor += 1
                if cursor >= len(area_map):
                    # 本页8个都进不去战斗, 下一轮扫描(没有可打的会自动往上滑动)
                    need_scan = True
                    continue
            else:
                futile_round = 0
                # 完成1次战斗(胜/败), 回到选择界面重新扫描重算index
                tried.clear()
                need_scan = True
            # 等待画面稳定(失败/击破图标动画)后再进行下一步
            time.sleep(random.uniform(1, 2))


        # 回 page_main
        self.ui_get_current_page()
        self.ui_goto(page_main)
        if success:
            self.set_next_run(task='RyouToppa', finish=True, server=True, success=True)
        else:
            self.set_next_run(task='RyouToppa', finish=True, server=True, success=False)
        raise TaskEnd

    def plan_tomorrow_ryoutoppa(self):
        # 安排下次寮突破，便于复用
        now = datetime.now()
        # 如果时间在00:00-5:00之间则设定时间为当天的自定义时间
        if now.time() < dt_time(5, 0):  # 不确定 time 的使用范围，重命名 datetime 中的 time
            self.custom_next_run(task='RyouToppa', custom_time=self.config.ryou_toppa.raid_config.next_ryoutoppa_time, time_delta=0)
        # 如果时间在05:00-23:59之间则设定时间为明天的自定义时间
        else:
            self.custom_next_run(task='RyouToppa', custom_time=self.config.ryou_toppa.raid_config.next_ryoutoppa_time, time_delta=1)

    def start_ryou_toppa(self):
        """
        开启寮突破
        :return:
        """
        # 点击寮突
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_SELECT_RYOU_BUTTON, interval=1):
                break
        logger.info(f'Click {self.I_SELECT_RYOU_BUTTON.name}')

        # 选择第一个寮
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_GUILD_ORDERS_REWARDS, action=self.C_SELECT_FIRST_RYOU, interval=1):
                break
        logger.info(f'Click {self.C_SELECT_FIRST_RYOU.name}')

        # 点击开始突入
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_START_TOPPA_BUTTON, interval=1):
                continue
            # 出现寮奖励， 说明寮突已开
            if self.appear(self.I_RYOU_REWARD, threshold=0.8):
                break
        logger.info(f'Click {self.I_START_TOPPA_BUTTON.name}')

    def has_ticket(self) -> bool:
        """
        如果没有票了，那么就返回False
        :return:
        """
        # 21点后、次日5点前无限进攻机会
        if datetime.now().hour >= 21 or datetime.now().hour <= 5:
            return True
        self.wait_until_appear(self.I_TOPPA_RECORD)
        self.screenshot()
        cu, res, total = self.O_NUMBER.ocr(self.device.image)
        if cu == 0 and cu + res == total:
            logger.warning(f'Execute round failed, no ticket')
            return False
        return True

    def check_area(self, index: int) -> bool:
        """
        检查该区域是否可攻打(已击破/攻略失败均视为不可攻打, 跳过)
        :return:
        """
        fail_signs = area_map[index].get("fail_sign")
        finished_signs = area_map[index].get("finished_sign")
        self.screenshot()
        # 该区域已击破: 不可攻打(100%攻破的收尾由scan_area的全体击破判定负责)
        if any(self.appear(f, threshold=0.8) for f in finished_signs):
            logger.info('Area [%s] is finished, skip.' % str(index + 1))
            return False
        # 如果该区域攻略失败返回 False
        if any(self.appear(f, threshold=0.8) for f in fail_signs):
            logger.info('Area [%s] is futile attack, skip.' % str(index + 1))
            return False
        return True

    def scan_area(self, exclude: set = None) -> int:
        """
        扫描当前页的8个区域(各区域标志ROI在同一屏内), 返回第一个可攻打区域
        :param exclude: 本页已尝试过、进不了战斗的区域index, 跳过不再重复点
        :return: 可攻打区域index; 当前页没有可打目标返回 -1
        """
        self.screenshot()
        image = self.device.image
        for i in range(len(area_map)):
            if exclude and i in exclude:
                continue
            fail_signs = area_map[i].get("fail_sign")
            finished_signs = area_map[i].get("finished_sign")
            # 该区域已击破: 跳过
            if any(f.match(image, threshold=0.8) for f in finished_signs):
                logger.info('Area [%s] is finished, skip.' % str(i + 1))
                continue
            # 该区域攻略失败: 跳过
            if any(f.match(image, threshold=0.8) for f in fail_signs):
                logger.info('Area [%s] is futile attack, skip.' % str(i + 1))
                continue
            return i
        return -1

    def swipe_area_list(self) -> bool:
        """
        在区域列表上点住往上滑(2行), 露出后面的目标
        :return: 滑动后画面是否变化; False 表示已滑到底, 没有更多目标
        """
        # 先点左侧安全区域收起可能残留的结界师弹窗, 避免滑动被弹窗吃掉
        self.click(self.C_SAFE_AREA, interval=1)
        self.screenshot()
        before = self.device.image.copy()
        # 在右侧列拖动(弹窗不会覆盖到这里), 慢速拖动以减少惯性导致的行错位
        self.device.swipe_adb((1050, 560), (1050, 560 - self.AREA_ROW_HEIGHT * 2), duration=0.6)
        time.sleep(1.5)
        self.screenshot()
        diff = cv2.absdiff(before[120:660, 400:1100], self.device.image[120:660, 400:1100]).mean()
        logger.info(f'Area list swipe up, diff={diff:.2f}')
        return diff > 5

    def rewind_area_list(self, pages: int):
        """
        从列表当前位置滑回顶部
        :param pages: 已向下滑动的页数
        """
        for _ in range(pages + 1):
            self.device.swipe_adb((1050, 560 - self.AREA_ROW_HEIGHT * 2), (1050, 560), duration=0.6)
            time.sleep(1)
        logger.info('Area list rewound to top')

    def flush_area_cache(self):
        time.sleep(2)
        duration = 0.352
        count = random.randint(1, 3)
        for i in range(count):
            # 测试过很多次 win32api, win32gui 的 MOUSEEVENTF_WHEEL, WM_MOUSEWHEEL
            # 都出现过很多次离奇的事件，索性放弃了使用以下方法，参数是精心调试的
            # 每次执行刚好刷新一组（2个）设定随机刷新 1 - 3 次
            safe_pos_x = random.randint(540, 1000)
            safe_pos_y = random.randint(320, 540)
            p1 = (safe_pos_x, safe_pos_y)
            p2 = (safe_pos_x, safe_pos_y - 101)
            logger.info('Swipe %s -> %s, %s ' % (point2str(*p1), point2str(*p2), duration))
            self.device.swipe_adb(p1, p2, duration=duration)
            time.sleep(2)

    def attack_area(self, index: int):
        """
        :return: 战斗胜利(True) / 战斗失败(False); 无法进战斗返回 None(调用方游标+1选下一个)
        """
        # 每次进攻前检查区域可用性
        if not self.check_area(index):
            return None

        # 正式进攻会设定 2s - 10s 的随机延迟，避免攻击间隔及其相近被检测为脚本。
        if self.config.ryou_toppa.raid_config.random_delay:
            delay = random_delay()
            time.sleep(delay)


        rcl = area_map[index].get("rule_click")
        # # 点击攻击区域，等待攻击按钮出现。
        # self.ui_click(rcl, stop=RealmRaidAssets.I_FIRE, interval=2)
        # 塔塔开！
        click_failure_count = 0
        while True:
            self.screenshot()
            # 先判是否已进战斗(点进攻后转场需要时间), 再判重试上限:
            # 若上限判断在前, 转场期间计数到顶会直接放弃, 导致已出现的准备界面无人点"准备"(2026-10-10实锤)
            if not self.appear(self.I_TOPPA_RECORD, threshold=0.85):
                time.sleep(1)
                self.screenshot()
                if self.appear(self.I_TOPPA_RECORD, threshold=0.85):
                    continue
                logger.info("Start attach area [%s]" % str(index + 1))
                return self.run_general_battle(config=self.config.ryou_toppa.general_battle_config)
            # 上限3: 点区域1次+点进攻1次为正常流程, 剩1次重试; 仅在选择界面停留时计数
            if click_failure_count >= 3:
                # 转场淡出期徽章仍>=0.85可见, 放弃前等1s复查: 进攻点击已生效却在上限帧被判失败,
                # 会把孤儿准备界面留给主循环空转卡死(2026-10-12 22:12 oas4实锤)
                time.sleep(1)
                self.screenshot()
                if not self.appear(self.I_TOPPA_RECORD, threshold=0.85):
                    continue
                logger.warning("Click failure, check your click position")
                return None
            if self.appear_then_click(RealmRaidAssets.I_FIRE, interval=2, threshold=0.8):
                click_failure_count += 1
                continue
            if self.click(rcl, interval=5):
                # https://github.com/runhey/OnmyojiAutoScript/issues/1748
                time.sleep(random.uniform(0, 0.3))
                click_failure_count += 1
                continue

    @battle_wait_strategy()
    def battle_wait(self, *args, **kwargs):
        return self.battle_wait_with_strategy(*args, **kwargs)


if __name__ == "__main__":
    from module.config.config import Config
    from module.device.device import Device

    config = Config('oas1')
    device = Device(config)
    t = ScriptTask(config, device)
    t.run()
