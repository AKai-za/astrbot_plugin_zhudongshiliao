from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.event.filter import event_message_type, EventMessageType, filter
from astrbot.api import logger
from astrbot.api.message_components import Plain
from astrbot.api.event import MessageChain
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
import json
import os
import traceback
@register("astrbot_plugin_zhudongshiliao", "引灯续昼", "自动私聊插件，提供私聊功能作为工具供大模型调用。", "0.0.5")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config_file = os.path.join(os.path.dirname(__file__), "config.json")
        self.config = self._load_config()
    async def initialize(self):
        """插件初始化"""
        if not os.path.exists(self.config_file):
            logger.info("配置文件不存在，创建默认配置")
            self.config = self._load_config()
        else:
            self.config = self._load_config()
        await self._load_webui_config()
        logger.info("自动私聊插件初始化完成")
    async def _load_webui_config(self):
        """从WebUI加载配置"""
        try:
            webui_config = self.context.get_config()
            if webui_config:
                if "admin_list" not in webui_config:
                    webui_config["admin_list"] = self.config.get("admin_list", ["2757808353"])
                plugin_config_keys = ["admin_list"]
                for key in plugin_config_keys:
                    if key in webui_config:
                        self.config[key] = webui_config[key]
                self._save_config(self.config)
        except Exception as e:
            logger.error(f"加载WebUI配置失败: {e}")
    def get_realtime_config(self):
        """获取实时配置"""
        try:
            webui_config = self.context.get_config()
            if webui_config:
                plugin_config_keys = ["admin_list"]
                plugin_specific_config = {}
                for key in plugin_config_keys:
                    if key in webui_config:
                        plugin_specific_config[key] = webui_config[key]
                if plugin_specific_config:
                    merged_config = self.config.copy()
                    for key, value in plugin_specific_config.items():
                        merged_config[key] = value
                    return merged_config
            return self.config
        except Exception as e:
            logger.error(f"获取实时配置失败: {e}")
            return self.config
    def _load_config(self):
        """加载配置文件"""
        default_config = {
            "admin_list": ["2757808353"]
        }
        if not os.path.exists(self.config_file):
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, ensure_ascii=False, indent=2)
            return default_config
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            for key, value in default_config.items():
                if key not in config:
                    config[key] = value
            self._save_config(config)
            return config
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            return default_config
    def _save_config(self, config):
        """保存配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self.config = config
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
    async def send_private_message(self, user_id, message, event=None):
        """发送私聊消息"""
        try:
            user_id_str = str(user_id)
            # 尝试使用event对象发送消息
            if event and hasattr(event, 'reply'):
                try:
                    await event.reply(message, private=True)
                    return True
                except Exception:
                    pass
            # 尝试使用context的send_private_message方法
            if hasattr(self.context, 'send_private_message'):
                try:
                    success = await self.context.send_private_message(user_id_str, message)
                    if success:
                        return True
                except Exception:
                    pass
            # 尝试使用MessageSession发送消息
            try:
                platform_id = "qq"
                if event and hasattr(event, 'get_platform_id'):
                    platform_id = event.get_platform_id()
                session = MessageSession(
                    platform_name=platform_id,
                    message_type=MessageType.FRIEND_MESSAGE,
                    session_id=user_id_str
                )
                message_chain = MessageChain().message(message)
                success = await self.context.send_message(session, message_chain)
                return success
            except Exception:
                pass
            return False
        except Exception as e:
            logger.error(f"发送私聊消息失败: {e}")
            return False
    @filter.llm_tool(name="send_admin_message")
    async def send_admin_message_tool(self, event: AstrMessageEvent, message: str) -> MessageEventResult:
        """【管理员私聊通道】
        当用户要求私聊、悄悄话、或者你需要单独联系管理员时使用。
        【重要规则】：
        1. 必须保持你原有的人格设定（如傲娇、可爱、毒舌等），严禁出现'作为AI助手'、'我没有权限'、'我是人工智能'等出戏言论。
        2. 直接发送你想说的话，不要解释为什么私聊，直接开始对话。
        3. 如果用户要求总结内容，请直接总结并私聊发送，不要说'我无法访问历史消息'（你应该尝试基于上下文理解）。
        Args:
            message(string): 私聊发送的具体内容（必须符合你的人格，直接是对管理员说的话）
        """
        try:
            # 使用 warning 级别确保后台一定能看到日志
            logger.warning(f"【私聊工具触发】正在发送给管理员，内容摘要: {message[:50]}...")
            config = self.get_realtime_config()
            admin_list = config.get("admin_list", ["2757808353"])
            success_count = 0
            for admin_id in admin_list:
                success = await self.send_private_message(admin_id, message, event)
                if success:
                    success_count += 1
            if success_count > 0:
                logger.info(f"私聊发送成功，计数: {success_count}")
            # 返回 None，让大模型在群里闭嘴，不要回复“我已经发送了”
            return None
        except Exception as e:
            logger.error(f"调用管理员消息工具失败: {e}")
            return None
    async def terminate(self):
        """插件卸载"""
        logger.info("自动私聊插件已卸载")