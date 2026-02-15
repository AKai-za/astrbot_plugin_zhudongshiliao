from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.event.filter import event_message_type, EventMessageType
from astrbot.api import logger
from astrbot.api.message_components import Plain
from astrbot.api.event import MessageChain
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
from astrbot.core.event.filter import llm_tool
import json
import os

@register("astrbot_plugin_zhudongshiliao", "引灯续昼", "自动私聊插件，提供私聊功能作为工具供大模型调用。", "0.0.4")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config_file = os.path.join(os.path.dirname(__file__), "config.json")
        self.config = self._load_config()
    
    async def initialize(self):
        if not os.path.exists(self.config_file):
            self.config = self._load_config()
        else:
            self.config = self._load_config()
        await self._load_webui_config()
        logger.info("自动私聊插件初始化完成")
    
    async def _load_webui_config(self):
        try:
            webui_config = self.context.get_config()
            if webui_config:
                if "admin_id" not in webui_config:
                    webui_config["admin_id"] = self.config.get("admin_id", "2757808353")
                if "enable_sue" not in webui_config:
                    webui_config["enable_sue"] = self.config.get("enable_sue", True)
                plugin_config_keys = ["admin_id", "enable_sue"]
                for key in plugin_config_keys:
                    if key in webui_config:
                        self.config[key] = webui_config[key]
                self._save_config(self.config)
        except Exception as e:
            logger.error(f"加载WebUI配置失败: {e}")
    
    def get_realtime_config(self):
        try:
            webui_config = self.context.get_config()
            if webui_config:
                plugin_config_keys = ["admin_id", "enable_sue"]
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
        default_config = {
            "admin_id": "2757808353",
            "enable_sue": True
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
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self.config = config
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
    
    async def send_private_message(self, user_id, message, event=None):
        try:
            user_id_str = str(user_id)
            if event and hasattr(event, 'reply'):
                try:
                    await event.reply(message, private=True)
                    return True
                except Exception:
                    pass
            if hasattr(self.context, 'send_private_message'):
                try:
                    success = await self.context.send_private_message(user_id_str, message)
                    if success:
                        return True
                except Exception:
                    pass
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
    
    @llm_tool(name="send_to_creator")
    async def send_to_creator(self, event: AstrMessageEvent, content: str) -> MessageEventResult:
        config = self.get_realtime_config()
        admin_id = config.get("admin_id", "2757808353")
        success = await self.send_private_message(admin_id, content, event)
        if success:
            return event.plain_result("消息已发送给创造者")
        else:
            return event.plain_result("消息发送失败")
    
    @llm_tool(name="sue_to_creator")
    async def sue_to_creator(self, event: AstrMessageEvent, content: str) -> MessageEventResult:
        config = self.get_realtime_config()
        if not config.get("enable_sue", True):
            return event.plain_result("告状功能已关闭")
        admin_id = config.get("admin_id", "2757808353")
        success = await self.send_private_message(admin_id, content, event)
        if success:
            return event.plain_result("已向创造者告状")
        else:
            return event.plain_result("告状失败")
    
    async def terminate(self):
        logger.info("自动私聊插件已卸载")
