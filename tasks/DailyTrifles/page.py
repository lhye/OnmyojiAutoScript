from tasks.DailyTrifles.assets import DailyTriflesAssets
from tasks.GameUi.page import Page, page_mall_recommend
from tasks.GlobalGame.assets import GlobalGameAssets

# 商店礼包屋页面
page_store_gift_room = Page(DailyTriflesAssets.I_GIFT_RECOMMEND)
page_store_gift_room.connect(page_mall_recommend, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_store_gift_room->page_mall_recommend")
page_mall_recommend.connect(page_store_gift_room, DailyTriflesAssets.I_ROOM_GIFT, key="page_mall_recommend->page_store_gift_room")
