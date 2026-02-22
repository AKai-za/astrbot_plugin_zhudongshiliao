from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star
from astrbot.api.event import filter
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
from astrbot.api import logger
import time
import re
import copy
from collections import defaultdict

# --- 配置键常量定义 ---
KEY_ADMIN_ID = "admin_id"
KEY_ENABLE_SUE = "enable_sue"
KEY_CUSTOM_ERROR_MSG = "custom_error_message"
KEY_ENABLE_CUSTOM_ERROR = "enable_custom_error"
KEY_DEFAULT_PLATFORM = "default_platform"

# --- 业务常量定义 ---
UNKNOWN_SOURCE = "unknown_source"

# 默认配置常量
DEFAULT_CONFIG = {
    KEY_ADMIN_ID: "",  # 空字符串，强制用户在WebUI中设置
    KEY_ENABLE_SUE: True,
    KEY_CUSTOM_ERROR_MSG: "系统出现异常，请联系管理员处理。{error_message}",
    KEY_ENABLE_CUSTOM_ERROR: True,
    KEY_DEFAULT_PLATFORM: "qq"
}

# 预编译所有错误匹配的正则表达式，提升高频拦截钩子的性能
COMPILED_ERROR_PATTERNS = [
    re.compile(r"^(?:\[AstrBot\]\s*)?LLM\s*响应错误", re.IGNORECASE),
    re.compile(r"^(?:\[AstrBot\]\s*)?All chat models failed", re.IGNORECASE),
    re.compile(r"^Error code:\s*\d+\s*-", re.IGNORECASE),
    re.compile(r"AuthenticationError", re.IGNORECASE),
    re.compile(r"API key is invalid", re.IGNORECASE),
    re.compile(r"^(?:Exception|Traceback).*?(?:most recent call last)", re.IGNORECASE),
]

# 单独预编译提取错误码的正则
COMPILED_ERROR_CODE_PATTERN = re.compile(r'Error code:\s*(\d+)', re.IGNORECASE)


class MyPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config
        # 频率限制存储
        self.message_rate_limit = defaultdict(list)  # {source_id: [timestamp1, timestamp2, ...]}
        self.rate_limit_window = 60  # 时间窗口（秒）
        self.rate_limit_max = 5  # 时间窗口内最大消息数

        # 记录上一次执行全局内存清理的时间
        self.last_cleanup_time = time.time()

    def _get_config(self):
        """
        获取最新配置，确保配置同步
        """
        # 使用深拷贝，彻底切断与全局默认配置的任何嵌套引用联系
        base_config = copy.deepcopy(DEFAULT_CONFIG)
        try:
            config = self.config
            if not isinstance(config, dict):
                logger.warning("插件配置格式错误或为空，已回退至默认配置")
                return base_config

            base_config.update(config)
            return base_config
        except Exception as e:
            logger.warning(f"获取配置时发生异常: {str(e)}，已回退至默认配置")
            return base_config

    def _get_source_id(self, event) -> str:
        """
        统一提取事件的调用来源 ID
        """
        source_id = UNKNOWN_SOURCE
        if event:
            try:
                if hasattr(event, 'user_id'):
                    source_id = str(event.user_id)
                elif hasattr(event, 'get_sender_id'):
                    source_id = str(event.get_sender_id())
            except Exception as e:
                logger.warning(f"无法动态获取事件来源ID：{str(e)}")
        return source_id

    def _check_rate_limit(self, source_id):
        """
        检查频率限制，并包含惰性内存清理机制
        """
        source_id_str = str(source_id)
        current_time = time.time()

        # 1. 触发全局惰性清理 (Lazy Sweep)
        if current_time - self.last_cleanup_time > self.rate_limit_window:
            for sid in list(self.message_rate_limit.keys()):
                valid_timestamps = [
                    ts for ts in self.message_rate_limit[sid]
                    if current_time - ts < self.rate_limit_window
                ]
                if not valid_timestamps:
                    del self.message_rate_limit[sid]
                else:
                    self.message_rate_limit[sid] = valid_timestamps

            self.last_cleanup_time = current_time
            logger.debug("已执行全局频率限制字典的内存清理")
        else:
            # 2. 针对当前请求的常规校验（仅在没有执行全局清理时才需要单独过滤）
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
        source_id = self._get_source_id(event)

        limit_key = f"user_{source_id}"
        if not self._check_rate_limit(limit_key):
            logger.warning(f"私聊频率限制：调用来源 {source_id} 触发频率过高")
            return False

        logger.info(f"发送私聊消息：来源 [{source_id}] -> 目标 [{target_id_str}]，消息长度 {len(message)}")

        if event and hasattr(event, 'reply') and hasattr(event, 'user_id'):
            if str(event.user_id) == target_id_str:
                try:
                    await event.reply(message, private=True)
                    return True
                except (AttributeError, NotImplementedError) as e:
                    logger.debug(f"当前平台不支持 event.reply 快捷回复，准备回退到常规发送接口: {str(e)}")
                except Exception:
                    logger.warning("通过 event.reply 发送私聊消息时发生异常", exc_info=True)

        if hasattr(self.context, 'send_private_message'):
            await self.context.send_private_message(target_id_str, message)
            return True

        config = self._get_config()
        platform_id = config.get(KEY_DEFAULT_PLATFORM)

        if event:
            if hasattr(event, 'get_platform_id'):
                try:
                    ext_platform = event.get_platform_id()
                    if ext_platform:
                        platform_id = ext_platform
                except (AttributeError, NotImplementedError) as e:
                    logger.debug(f"当前事件未实现 get_platform_id，将尝试备用方案: {str(e)}")
            elif hasattr(event, 'adapter') and hasattr(event.adapter, 'platform_name'):
                if event.adapter.platform_name:
                    platform_id = event.adapter.platform_name

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

        if not success:
            return event.plain_result("发送失败：您的发送频率过高，请稍后再试。")
        return event.plain_result("私聊消息已成功发送。")

    @filter.llm_tool(name="message_to_admin")
    async def message_to_admin(self, event: AstrMessageEvent, content: str) -> MessageEventResult:
        """
        向管理员发送消息工具
        """
        config = self._get_config()
        admin_id = config.get(KEY_ADMIN_ID, "")

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
        """
        config = self._get_config()
        if config.get(KEY_ENABLE_SUE, True):
            admin_id = config.get(KEY_ADMIN_ID, "")

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
        config = self._get_config()
        admin_id = config.get(KEY_ADMIN_ID, "")
        display_admin_id = admin_id if admin_id else "未配置"
        enable_sue = config.get(KEY_ENABLE_SUE, True)
        custom_error_message = config.get(KEY_CUSTOM_ERROR_MSG)
        enable_custom_error = config.get(KEY_ENABLE_CUSTOM_ERROR, True)

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
        source_id = self._get_source_id(event)
        limit_key = f"group_{source_id}"

        if not self._check_rate_limit(limit_key):
            logger.warning(f"群消息频率限制：调用来源 {source_id} 触发频率过高")
            return event.plain_result("群消息发送失败：您调用工具的频率过高，请稍后再试。")

        group_id_str = str(group_id)
        logger.info(f"发送群消息：来源 [{source_id}] -> 目标群 [{group_id_str}]，消息长度 {len(content)}")

        config = self._get_config()
        platform_id = config.get(KEY_DEFAULT_PLATFORM)

        if event:
            if hasattr(event, 'get_platform_id'):
                try:
                    ext_platform = event.get_platform_id()
                    if ext_platform:
                        platform_id = ext_platform
                except (AttributeError, NotImplementedError) as e:
                    logger.debug(f"调用 get_platform_id 失败: {str(e)}")
            elif hasattr(event, 'adapter') and hasattr(event.adapter, 'platform_name'):
                if event.adapter.platform_name:
                    platform_id = event.adapter.platform_name

        session = MessageSession(
            platform_name=platform_id,
            message_type=MessageType.GROUP_MESSAGE,
            session_id=group_id_str
        )
        message_chain = MessageChain()
        message_chain.chain = [Plain(content)]

        try:
            await self.context.send_message(session, message_chain)
            return event.plain_result("群消息发送成功")
        except Exception:
            logger.exception("群消息底层发送接口调用失败")
            return event.plain_result("群消息发送失败：系统暂时无法发送消息，请稍后再试")

    def _replace_error_variables(self, message, error_message="", error_code=""):
        """
        替换错误消息中的变量
        """
        message = message.replace("{error_message}", error_message)
        message = message.replace("{error_code}", error_code)
        return message

    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent):
        """
        发送消息前的事件钩子，用于拦截并修改错误消息
        """
        config = self._get_config()
        if not config.get(KEY_ENABLE_CUSTOM_ERROR, True):
            return

        result = event.get_result()
        if not result:
            return

        try:
            text_to_check = ""
            if hasattr(result, 'chain') and result.chain:
                text_to_check = "".join([comp.text for comp in result.chain if hasattr(comp, 'text') and comp.text])
            elif hasattr(result, 'text') and result.text:
                text_to_check = result.text

            if not text_to_check:
                return

            is_error = False
            error_code = ""

            for pattern in COMPILED_ERROR_PATTERNS:
                if pattern.search(text_to_check):
                    is_error = True

                    code_match = COMPILED_ERROR_CODE_PATTERN.search(text_to_check)
                    if code_match:
                        error_code = code_match.group(1)

                    logger.debug(f"拦截到大模型系统错误，匹配规则: {pattern.pattern}")
                    break

            if is_error:
                custom_error = config.get(KEY_CUSTOM_ERROR_MSG)
                custom_error = self._replace_error_variables(custom_error, text_to_check, error_code)

                if hasattr(result, 'chain'):
                    result.chain = [Plain(custom_error)]
                if hasattr(result, 'text'):
                    result.text = custom_error

        except Exception:
            logger.exception("错误消息替换拦截器内部发生致命异常")

    async def terminate(self):
        pass