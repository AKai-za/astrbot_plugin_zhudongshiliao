from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
from astrbot.api import logger
import time
import re
from collections import defaultdict

# 默认配置常量
DEFAULT_CONFIG = {
    "admin_id": "",  # 空字符串，强制用户在WebUI中设置
    "enable_sue": True,
    "custom_error_message": "请有人告诉管理员我的AI出现了问题",
    "enable_custom_error": True,
    "default_platform": "qq"
}

@register("astrbot_plugin_zhudongshiliao", "引灯续昼", "自动私聊插件，提供私聊功能作为工具供大模型调用。", "0.3.9")
class MyPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config
        # 频率限制存储
        self.message_rate_limit = defaultdict(list)  # {source_id: [timestamp1, timestamp2, ...]}
        self.rate_limit_window = 60  # 时间窗口（秒）
        self.rate_limit_max = 5  # 时间窗口内最大消息数

        # 新增：记录上一次执行全局内存清理的时间
        self.last_cleanup_time = time.time()

    def _check_rate_limit(self, source_id):
        """
        检查频率限制，并包含惰性内存清理机制

        Args:
            source_id: 调用来源ID (如 pm_12345 或 group_67890)

        Returns:
            bool: 是否通过频率限制
        """
        source_id_str = str(source_id)
        current_time = time.time()

        # 1. 触发全局惰性清理 (Lazy Sweep)
        # 如果距离上次清理超过了时间窗口，则遍历清理所有过期的键，防止内存泄漏
        if current_time - self.last_cleanup_time > self.rate_limit_window:
            # 必须转换为 list，避免在遍历字典时修改字典导致 RuntimeError
            for sid in list(self.message_rate_limit.keys()):
                # 过滤出未过期的时间戳
                valid_timestamps = [
                    ts for ts in self.message_rate_limit[sid]
                    if current_time - ts < self.rate_limit_window
                ]

                if not valid_timestamps:
                    # 如果该用户/群的所有记录都已过期，直接删除键释放内存
                    del self.message_rate_limit[sid]
                else:
                    # 否则，更新为仅包含有效时间戳的列表
                    self.message_rate_limit[sid] = valid_timestamps

            # 更新最后清理时间
            self.last_cleanup_time = current_time
            logger.debug("已执行全局频率限制字典的内存清理")

        # 2. 针对当前请求的常规校验
        # 如果刚才进行了全局清理，当前用户的过期记录已经被清理了。
        # 如果没有触发全局清理，我们依然需要单独清理当前用户的过期记录。
        if source_id_str in self.message_rate_limit:
            self.message_rate_limit[source_id_str] = [
                ts for ts in self.message_rate_limit[source_id_str]
                if current_time - ts < self.rate_limit_window
            ]

        # 3. 检查是否超过限制
        if len(self.message_rate_limit[source_id_str]) >= self.rate_limit_max:
            return False

        # 4. 记录当前时间戳并放行
        self.message_rate_limit[source_id_str].append(current_time)
        return True

    async def send_private_message(self, target_id, message, event=None):
        """
        发送私聊消息底层实现
        返回: bool (是否发送成功/通过限流)
        """
        target_id_str = str(target_id)

        # 1. 提取真实的调用来源 ID (Source ID)
        source_id = "unknown_source"
        if event:
            try:
                # 尝试从 event 中获取触发对话的用户 ID
                if hasattr(event, 'user_id'):
                    source_id = str(event.user_id)
                elif hasattr(event, 'get_sender_id'):
                    source_id = str(event.get_sender_id())
            except Exception as e:
                logger.warning(f"无法获取事件来源ID：{str(e)}")

        # 2. 针对【调用来源】进行限流，而不是目标对象
        if not self._check_rate_limit(f"user_{source_id}"):
            logger.warning(f"私聊频率限制：调用来源 {source_id} 触发频率过高")
            return False

        # 审计日志：记录是谁发给了谁
        logger.info(f"发送私聊消息：来源 [{source_id}] -> 目标 [{target_id_str}]，消息长度 {len(message)}")

        # 尝试通过事件回复发送（仅当目标用户是当前事件发送者时）
        if event and hasattr(event, 'reply') and hasattr(event, 'user_id'):
            try:
                if str(event.user_id) == target_id_str:
                    await event.reply(message, private=True)
                    return True
            except Exception as e:
                logger.warning(f"获取事件用户ID失败：{str(e)}")
                pass

        # 尝试通过上下文发送
        if hasattr(self.context, 'send_private_message'):
            await self.context.send_private_message(target_id_str, message)
            return True

        # 尝试通过消息会话发送
        # 1. 从配置获取基础回退值，而不是硬编码
        config = self._get_config()
        platform_id = config.get("default_platform")
        # 2. 尝试从事件上下文中动态提取真实的平台 ID
        if event:
            # 方案 A: 尝试调用标准方法
            if hasattr(event, 'get_platform_id'):
                try:
                    ext_platform = event.get_platform_id()
                    if ext_platform:
                        platform_id = ext_platform
                except Exception as e:
                    logger.debug(f"调用 get_platform_id 失败: {str(e)}")

            # 方案 B: 备用提取路径 (如果 AstrBot 底层适配器暴露了 adapter 属性)
            elif hasattr(event, 'adapter') and hasattr(event.adapter, 'platform_name'):
                if event.adapter.platform_name:
                    platform_id = event.adapter.platform_name

        # 3. 构建跨平台的 MessageSession
        session = MessageSession(
            platform_name=platform_id,
            message_type=MessageType.FRIEND_MESSAGE,
            session_id=target_id_str
        )
        message_chain = MessageChain()
        message_chain.chain = [Plain(message)]
        await self.context.send_message(session, message_chain)
        return True

    @filter.llm_tool(name="private_message")
    async def private_message(self, event: AstrMessageEvent, user_id: str, content: str) -> MessageEventResult:
        """
        发送私聊消息工具
        """
        success = await self.send_private_message(user_id, content, event)
        event.stop_event()

        # 增加反馈：如果被限流，明确告诉 LLM，防止它反复尝试
        if not success:
            return event.plain_result("发送失败：您的发送频率过高，请稍后再试。")
        return event.plain_result("私聊消息已成功发送。")

    def _get_config(self):
        """
        获取最新配置，确保配置同步

        Returns:
            dict: 最新的配置字典
        """
        # 第一步：浅拷贝由于 DEFAULT_CONFIG 只有一层的简单键值对（字符串、布尔值），使用 .copy() 进行浅拷贝已经足够切断引用联系。
        base_config = DEFAULT_CONFIG.copy()
        try:
            # 获取传入的插件配置
            config = self.config
            # 验证配置完整性
            if not isinstance(config, dict):
                logger.warning("插件配置格式错误或为空，已回退至默认配置")
                return base_config
            # 第二步：合并配置
            # 将用户的实际配置覆盖到 base_config 的副本上。
            # 这替代了原来遍历 DEFAULT_CONFIG 去修改 config 的做法，更加安全且符合直觉。
            base_config.update(config)
            return base_config

        except Exception as e:
            # 发生异常时返回默认配置的副本，并记录日志
            logger.warning(f"获取配置时发生异常: {str(e)}，已回退至默认配置")
            return base_config

    @filter.llm_tool(name="message_to_admin")
    async def message_to_admin(self, event: AstrMessageEvent, content: str) -> MessageEventResult:
        """
        向管理员发送消息工具

        Args:
            content(string): 消息内容
        """
        # 获取最新配置
        config = self._get_config()
        admin_id = config.get("admin_id", "")

        # 增加校验：如果未配置管理员 ID，则拒绝执行并反馈给大模型
        if not admin_id:
            logger.warning("尝试向管理员发送消息失败：未配置 admin_id")
            return event.plain_result("发送失败：系统未配置管理员联系方式。")

        success = await self.send_private_message(admin_id, content, event)
        event.stop_event()
        if not success:
            return event.plain_result("发送失败：您的发送频率过高，触发了系统的防刷屏保护。")
        return event.plain_result("消息已成功发送给管理员。")

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
        # 获取最新配置
        config = self._get_config()
        if config.get("enable_sue", True):
            admin_id = config.get("admin_id", "")

            # 增加校验
            if not admin_id:
                logger.warning("尝试告状失败：未配置 admin_id")
                return event.plain_result("告状失败：系统未配置管理员联系方式。")

            success = await self.send_private_message(admin_id, f"【告状】\n{content}", event)
            event.stop_event()
            if not success:
                return event.plain_result("发送失败：您的发送频率过高，触发了系统的防刷屏保护。")
            return event.plain_result("告状消息已成功发送给管理员。")

        return event.plain_result("告状失败：系统当前未开启告状功能。")

    @filter.llm_tool(name="get_admin_info")
    async def get_admin_info(self, event: AstrMessageEvent) -> MessageEventResult:
        """
        获取管理员信息工具
        """
        # 获取最新配置
        config = self._get_config()
        admin_id = config.get("admin_id", "")
        display_admin_id = admin_id if admin_id else "未配置"
        enable_sue = config.get("enable_sue", True)
        custom_error_message = config.get("custom_error_message")
        enable_custom_error = config.get("enable_custom_error", True)

        return event.plain_result(
            f"管理员ID: {display_admin_id}\n"
            f"告状功能: {'开启' if enable_sue else '关闭'}\n"
            f"自定义错误消息: {custom_error_message}\n"
            f"启用自定义错误: {'开启' if enable_custom_error else '关闭'}"
        )

    @filter.llm_tool(name="group_message")
    async def send_group_message(self, event: AstrMessageEvent, group_id: str, content: str) -> MessageEventResult:
        """
        发送消息到群里的工具
        """
        # 1. 提取真实的调用来源 ID
        source_id = "unknown_source"
        if event:
            try:
                if hasattr(event, 'user_id'):
                    source_id = str(event.user_id)
            except Exception:
                pass

        # 2. 针对【调用来源】进行限流
        if not self._check_rate_limit(f"group_{source_id}"):
            logger.warning(f"群消息频率限制：调用来源 {source_id} 触发频率过高")
            return event.plain_result("群消息发送失败：您调用工具的频率过高，请稍后再试。")

        group_id_str = str(group_id)
        logger.info(f"发送群消息：来源 [{source_id}] -> 目标群 [{group_id_str}]，消息长度 {len(content)}")

        try:
            if hasattr(event, 'bot') and hasattr(event.bot, 'send_group_msg'):
                await event.bot.send_group_msg(group_id=group_id_str, message=content)
                return event.plain_result("群消息发送成功")
            else:
                return event.plain_result("群消息发送失败：不支持的平台或方法")
        except Exception as e:
            logger.error(f"群消息发送失败：{str(e)}")
            return event.plain_result("群消息发送失败：系统暂时无法发送消息，请稍后再试")
    
    def _replace_error_variables(self, message, error_message="", error_code=""):
        """
        替换错误消息中的变量
        
        Args:
            message: 原始消息
            error_message: 系统错误消息
            error_code: 错误代码
            
        Returns:
            替换变量后的消息
        """
        message = message.replace("{error_message}", error_message)
        message = message.replace("{error_code}", error_code)
        return message

    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent):
        """
        发送消息前的事件钩子，用于拦截并修改错误消息
        """
        # 获取最新配置，确保实时同步
        config = self._get_config()
        if not config.get("enable_custom_error", True):
            return

        # 获取当前结果
        result = event.get_result()
        if not result:
            return

        try:
            # 1. 统一提取待检测的文本内容（避免重复编写 chain 和 text 的处理逻辑）
            text_to_check = ""
            if hasattr(result, 'chain') and result.chain:
                # 提取纯文本组件的内容并拼接
                text_to_check = "".join([comp.text for comp in result.chain if hasattr(comp, 'text') and comp.text])
            elif hasattr(result, 'text') and result.text:
                text_to_check = result.text

            if not text_to_check:
                return

            # 2. 严格的正则匹配规则：告别模糊搜索，只匹配真正的系统级报错特征
            # 使用 ^ 锚定开头，或匹配极度特殊的字符串结构
            ERROR_PATTERNS = [
                r"^(?:\[AstrBot\]\s*)?LLM\s*响应错误",  # AstrBot 框架自身报错
                r"^(?:\[AstrBot\]\s*)?All chat models failed",  # 模型全挂了
                r"^Error code:\s*\d+\s*-",  # OpenAI 等标准 API 报错 (通常开头是 Error code: 400 - {...)
                r"AuthenticationError",  # 极度特殊的异常名
                r"API key is invalid",  # 极度特殊的异常描述
                r"^(?:Exception|Traceback).*?(?:most recent call last)",  # Python 原生异常堆栈特征
            ]

            is_error = False
            error_code = ""

            for pattern in ERROR_PATTERNS:
                # 使用正则表达式进行严格检测
                if re.search(pattern, text_to_check, re.IGNORECASE):
                    is_error = True

                    # 如果匹配到了错误，顺便尝试精准提取错误码（如果有的话）
                    code_match = re.search(r'Error code:\s*(\d+)', text_to_check, re.IGNORECASE)
                    if code_match:
                        error_code = code_match.group(1)

                    logger.debug(f"拦截到大模型系统错误，匹配规则: {pattern}")
                    break

            # 3. 如果确认为系统错误，执行替换操作
            if is_error:
                # 获取最新自定义报错消息
                custom_error = config.get("custom_error_message")

                # 替换变量
                custom_error = self._replace_error_variables(custom_error, text_to_check, error_code)

                # 覆写结果的消息链和文本
                if hasattr(result, 'chain'):
                    result.chain = [Plain(custom_error)]
                if hasattr(result, 'text'):
                    result.text = custom_error

        except Exception as e:
            # 记录异常，确保事件钩子自身崩溃不会影响系统主流程
            logger.error(f"错误消息替换拦截器内部异常：{str(e)}")
    
    async def terminate(self):
        pass