# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey

from pydantic import ConfigDict, Field

from tasks.Component.config_base import ConfigBase
from tasks.Component.config_scheduler import Scheduler


class MetaDemon(ConfigBase):
    # 旧版的礼包/合成/阵容/御魂切换配置已随任务重写失效，这里忽略旧配置里的多余字段
    model_config = ConfigDict(extra='ignore')

    scheduler: Scheduler = Field(default_factory=Scheduler)
