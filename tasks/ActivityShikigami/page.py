from tasks.ActivityShikigami.assets import ActivityShikigamiAssets as asa
from tasks.GameUi.page import Page, page_main
from tasks.GlobalGame.assets import GlobalGameAssets as gga
from tasks.GameUi.assets import GameUiAssets as G
from tasks.Component.RightActivity.assets import RightActivityAssets as RAA

# ************************************* 活动部分 *****************************************#

# 活动总览页 act_list
page_act_list = Page(asa.I_CHECK_ACT_LIST)
page_act_list.additional = [gga.I_UI_REWARD]
page_act_list.link(button=G.I_BACK_Y, destination=page_main)
page_main.link(button=[asa.I_SHI, RAA.I_TOGGLE_BUTTON], destination=page_act_list)

# 拾光永恒活动主界面 act_main
page_act_main = Page(asa.I_CHECK_MAIN)
# 神木补给: 每日首次进入弹出发放门票, 需先关掉再进地图
page_act_main.additional = [gga.I_UI_REWARD, asa.I_SUPPLY_CLOSE]
page_act_main.link(button=G.I_BACK_Y, destination=page_main)
page_act_list.link(button=asa.I_GOTO_ACT, destination=page_act_main)

# 亗地回响地图
page_map = Page(asa.I_CHECK_MAP)
page_map.additional = [gga.I_UI_REWARD, gga.I_UI_CONFIRM, gga.I_UI_CONFIRM_SAMLL]
page_map.link(button=G.I_BACK_Y, destination=page_act_main)
page_act_main.link(button=asa.I_GOTO_MAP, destination=page_map)

# 虚无精锐 boss 准备页（爬塔战斗页）
page_climb_act = Page(asa.I_CHECK_BATTLE_MAIN)
page_climb_act.additional = [gga.I_UI_REWARD, asa.I_SKIP_BUTTON, asa.I_CONFIRM_SKIP, asa.I_RED_EXIT]
page_climb_act.link(button=G.I_BACK_Y, destination=page_map)
page_map.link(button=asa.I_BOSS_LABEL, destination=page_climb_act)
