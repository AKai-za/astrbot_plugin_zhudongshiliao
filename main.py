from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType

@register("astrbot_plugin_zhudongshiliao", "引灯续昼", "自动私聊插件，提供私聊功能作为工具供大模型调用。", "2.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
    
    async def send_private_message(self, user_id, message, event=None):
        # 发送私聊消息
        user_id_str = str(user_id)
        # 尝试通过事件回复发送
        if event and hasattr(event, 'reply'):
            await event.reply(message, private=True)
            return
        # 尝试通过上下文发送
        if hasattr(self.context, 'send_private_message'):
            await self.context.send_private_message(user_id_str, message)
            return
        # 尝试通过消息会话发送
        platform_id = "qq"
        if event and hasattr(event, 'get_platform_id'):
            platform_id = event.get_platform_id()
        session = MessageSession(
            platform_name=platform_id,
            message_type=MessageType.FRIEND_MESSAGE,
            session_id=user_id_str
        )
        await self.context.send_message(session, message)
    
    async def private_message(self, event: AstrMessageEvent, user_id: str, content: str) -> MessageEventResult:
        """
        发送私聊消息工具
        
        Args:
            event: 消息事件
            user_id: 用户ID
            content: 消息内容
        """
        await self.send_private_message(user_id, content, event)
        return event.plain_result("")
    
    async def message_to_admin(self, event: AstrMessageEvent, content: str) -> MessageEventResult:
        """
        向管理员发送消息工具
        
        Args:
            event: 消息事件
            content: 消息内容
        """
        admin_id = self.context.get_config().get("admin_id", "2757808353")
        await self.send_private_message(admin_id, content, event)
        return event.plain_result("")
    
    async def sue_to_admin(self, event: AstrMessageEvent, content: str) -> MessageEventResult:
        """
        告状工具 - 向管理员发送告状消息
        
        Args:
            event: 消息事件
            content: 告状内容
        """
        config = self.context.get_config()
        if config.get("enable_sue", True):
            admin_id = config.get("admin_id", "2757808353")
            await self.send_private_message(admin_id, f"【告状】\n{content}", event)
        return event.plain_result("")
    
    async def get_admin_info(self, event: AstrMessageEvent) -> MessageEventResult:
        """
        获取管理员信息工具
        
        Args:
            event: 消息事件
        """
        config = self.context.get_config()
        admin_id = config.get("admin_id", "2757808353")
        enable_sue = config.get("enable_sue", True)
        return event.plain_result(f"管理员ID: {admin_id}\n告状功能: {'开启' if enable_sue else '关闭'}")
    
    async def terminate(self):
        pass