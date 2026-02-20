from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain
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
        message_chain = MessageChain()
        message_chain.chain = [Plain(message)]
        await self.context.send_message(session, message_chain)
    
    @filter.llm_tool(name="private_message")
    async def private_message(self, event: AstrMessageEvent, user_id: str, content: str) -> MessageEventResult:
        """
        发送私聊消息工具
        
        Args:
            user_id(string): 用户ID
            content(string): 消息内容
        """
        await self.send_private_message(user_id, content, event)
        event.stop_event()
        return event.plain_result("")
    
    @filter.llm_tool(name="message_to_admin")
    async def message_to_admin(self, event: AstrMessageEvent, content: str) -> MessageEventResult:
        """
        向管理员发送消息工具
        
        Args:
            content(string): 消息内容
        """
        admin_id = self.context.get_config().get("admin_id", "2757808353")
        await self.send_private_message(admin_id, content, event)
        event.stop_event()
        return event.plain_result("")
    
    @filter.llm_tool(name="sue_to_admin")
    async def sue_to_admin(self, event: AstrMessageEvent, content: str) -> MessageEventResult:
        """
        告状工具 - 向管理员发送告状消息
        
        Args:
            content(string): 告状内容，建议包含以下信息：
                1. 发生的群聊（如果是群聊中发生的）
                2. 具体是谁说的坏话
                3. 说了什么具体内容

        """
        config = self.context.get_config()
        if config.get("enable_sue", True):
            admin_id = config.get("admin_id", "2757808353")
            await self.send_private_message(admin_id, f"【告状】\n{content}", event)
        event.stop_event()
        return event.plain_result("")
    
    @filter.llm_tool(name="get_admin_info")
    async def get_admin_info(self, event: AstrMessageEvent) -> MessageEventResult:
        """
        获取管理员信息工具
        """
        config = self.context.get_config()
        admin_id = config.get("admin_id", "2757808353")
        enable_sue = config.get("enable_sue", True)
        return event.plain_result(f"管理员ID: {admin_id}\n告状功能: {'开启' if enable_sue else '关闭'}")
    
    @filter.llm_tool(name="group_message")
    async def send_group_message(self, event: AstrMessageEvent, group_id: str, content: str) -> MessageEventResult:
        """
        发送消息到群里的工具
        
        Args:
            group_id (string): 群聊ID
            content(string): 消息内容
        """
        try:
            # 确保群ID是字符串
            group_id_str = str(group_id)
            
            # 使用平台特定的发送方式（aiocqhttp）
            if hasattr(event, 'bot') and hasattr(event.bot, 'send_group_msg'):
                await event.bot.send_group_msg(group_id=group_id_str, message=content)
                return event.plain_result("群消息发送成功")
            else:
                return event.plain_result("群消息发送失败：不支持的平台或方法")
                
        except Exception as e:
            # 捕获所有异常并返回详细错误信息
            return event.plain_result(f"群消息发送失败：{str(e)}")
    


    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent):
        """
        发送消息前的事件钩子，用于拦截并修改错误消息
        """
        # 检查是否启用了自定义报错
        config = self.context.get_config()
        if not config.get("enable_custom_error", True):
            return
        
        # 获取当前结果
        result = event.get_result()
        if not result:
            return
        
        # 检查并修改错误消息
        try:
            # 检查结果是否是错误消息
            is_error = False
            error_message = ""
            
            # 检查不同格式的结果对象
            if hasattr(result, 'chain') and result.chain:
                # 检查消息链
                for comp in result.chain:
                    if hasattr(comp, 'text') and comp.text:
                        text = comp.text
                        if any(keyword in text for keyword in [
                            "错误", "失败", "error", "failed", "Error", "Failed",
                            "LLM 响应错误", "All chat models failed", "AuthenticationError",
                            "API key is invalid", "Error code:"
                        ]):
                            is_error = True
                            error_message = text
                            break
            elif hasattr(result, 'text') and result.text:
                # 检查文本结果
                text = result.text
                if any(keyword in text for keyword in [
                    "错误", "失败", "error", "failed", "Error", "Failed",
                    "LLM 响应错误", "All chat models failed", "AuthenticationError",
                    "API key is invalid", "Error code:"
                ]):
                    is_error = True
                    error_message = text
            
            # 如果是错误消息，替换为自定义报错
            if is_error:
                # 获取自定义报错消息（优先使用WebUI配置）
                custom_error = config.get("custom_error_message", "我的ai好像出错了喵，有好心人帮我联系一下我的创造者吗")
                
                # 提取错误代码
                error_code = ""
                import re
                match = re.search(r'Error code: (\d+)', error_message)
                if match:
                    error_code = match.group(1)
                
                # 替换变量
                custom_error = custom_error.replace("{error_message}", error_message)
                custom_error = custom_error.replace("{error_code}", error_code)
                
                # 替换结果的消息链
                from astrbot.api.message_components import Plain
                if hasattr(result, 'chain'):
                    result.chain = [Plain(custom_error)]
                elif hasattr(result, 'text'):
                    result.text = custom_error
                
        except Exception as e:
            # 捕获所有异常，确保钩子不会崩溃
            pass
    async def terminate(self):
        pass