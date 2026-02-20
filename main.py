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
        
        # 检查结果是否包含错误信息
        try:
            # 获取消息链的纯文本内容
            plain_text = ""
            if hasattr(result, 'chain') and result.chain:
                for comp in result.chain:
                    if hasattr(comp, 'text'):
                        plain_text += comp.text
                    elif hasattr(comp, 'content'):
                        plain_text += comp.content
            elif hasattr(result, 'text'):
                plain_text = result.text
            
            # 检查是否是系统默认的错误消息
            error_keywords = [
                "LLM 响应错误", 
                "request error", 
                "All chat models failed",
                "AuthenticationError",
                "Error code:"
            ]
            
            has_error = any(keyword in plain_text for keyword in error_keywords)
            
            if has_error:
                # 获取自定义报错消息
                custom_error = config.get("custom_error_message", "抱歉，我遇到了一些问题，暂时无法完成这个操作。请稍后再试或联系管理员。")
                
                # 提取错误信息
                error_message = plain_text
                error_code = ""
                
                # 尝试提取错误代码
                import re
                match = re.search(r'Error code: (\d+)', plain_text)
                if match:
                    error_code = match.group(1)
                
                # 替换变量
                custom_error = self._replace_error_variables(custom_error, error_message, error_code)
                
                # 替换结果
                from astrbot.api.message_components import Plain
                result.chain = [Plain(custom_error)]
                
                # 停止事件传播
                if hasattr(event, 'stop_event'):
                    event.stop_event()
        except Exception as e:
            # 捕获所有异常，确保钩子不会崩溃
            pass
    async def terminate(self):
        pass