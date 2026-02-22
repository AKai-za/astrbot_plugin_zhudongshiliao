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
    KEY_ADMIN_ID: "",
    KEY_ENABLE_SUE: True,
    KEY_CUSTOM_ERROR_MSG: "系统出现异常，请联系管理员处理。{error_message}",
    KEY_ENABLE_CUSTOM_ERROR: True,
    KEY_DEFAULT_PLATFORM: "qq"
}

# 预编译错误匹配正则
COMPILED_ERROR_PATTERNS = [
    re.compile(r"^(?:\[AstrBot\]\s*)?LLM\s*响应错误", re.IGNORECASE),
    re.compile(r"^(?:\[AstrBot\]\s*)?All chat models failed", re.IGNORECASE),
    re.compile(r"^Error code:\s*\d+\s*-", re.IGNORECASE),
    re.compile(r"AuthenticationError", re.IGNORECASE),
    re.compile(r"API key is invalid", re.IGNORECASE),
    re.compile(r"^(?:Exception|Traceback).*?(?:most recent call last)", re.IGNORECASE),
]

COMPILED_ERROR_CODE_PATTERN = re.compile(r'Error code:\s*(\d+)', re.IGNORECASE)


class MyPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config
        self.message_rate_limit = defaultdict(list)
        self.rate_limit_window = 60
        self.rate_limit_max = 5
        self.last_cleanup_time = time.time()
        self._cached_config = None
        self._last_raw_config = None

    def _get_config(self):
        """
        获取最新配置（兼顾热更新与极致性能）
        """
        # 1. 缓存命中判断：如果缓存存在，且原始配置没有被框架热更新过，直接返回 O(1)
        # 注意：Python 的 dict == 判断会先比较内存地址(id)，再比较长度，最后比较内容，非常快
        if self._cached_config is not None and self.config == self._last_raw_config:
            return self._cached_config

        # 2. 缓存未命中或配置已变更：执行深拷贝合并（仅在初始化或配置被修改的那一瞬间执行一次）
        base_config = copy.deepcopy(DEFAULT_CONFIG)
        try:
            if isinstance(self.config, dict):
                base_config.update(self.config)
            else:
                logger.warning("插件配置格式错误或为空，已回退至默认配置")

            # 3. 更新缓存与快照
            self._cached_config = base_config
            # 使用浅拷贝保存原始配置的快照，用于下次对比
            self._last_raw_config = self.config.copy() if isinstance(self.config, dict) else None

            logger.debug("已重新加载并缓存最新配置")

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
                if hasattr(event, 'get_sender_id') and callable(event.get_sender_id):
                    source_id = str(event.get_sender_id())
                elif hasattr(event, 'user_id'):
                    source_id = str(event.user_id)
            except Exception as e:
                logger.warning(f"无法动态获取事件来源ID：{str(e)}")
        return source_id

    def _filter_valid_ts(self, timestamps: list, current_time: float) -> list:
        """辅助方法：过滤出窗口期内的有效时间戳"""
        return [ts for ts in timestamps if current_time - ts < self.rate_limit_window]

    def _check_rate_limit(self, source_id):
        """
        检查频率限制，包含 DRY 优化的惰性内存清理机制
        """
        source_id_str = str(source_id)
        current_time = time.time()

        # 1. 始终优先清理当前调用者的过期记录
        if source_id_str in self.message_rate_limit:
            self.message_rate_limit[source_id_str] = self._filter_valid_ts(
                self.message_rate_limit[source_id_str], current_time
            )

        # 2. 全局惰性清理机制 (跳过已清理的当前调用者)
        if current_time - self.last_cleanup_time > self.rate_limit_window:
            for sid in list(self.message_rate_limit.keys()):
                if sid == source_id_str:
                    continue

                valid_ts = self._filter_valid_ts(self.message_rate_limit[sid], current_time)
                if not valid_ts:
                    del self.message_rate_limit[sid]
                else:
                    self.message_rate_limit[sid] = valid_ts

            self.last_cleanup_time = current_time
            logger.debug("已执行全局频率限制字典的内存清理")

        # 3. 检查限流阈值
        if len(self.message_rate_limit[source_id_str]) >= self.rate_limit_max:
            return False

        # 4. 放行并记录
        self.message_rate_limit[source_id_str].append(current_time)
        return True

    def _extract_platform_id(self, event) -> str:
        """
        提取平台 ID，防范多平台环境下的路由串线降级风险
        """
        # 如果没有 event（纯主动下发），则安全使用默认配置
        if not event:
            return self._get_config().get(KEY_DEFAULT_PLATFORM)

        # 如果有 event，必须强制依赖事件自带的平台属性，禁止盲目降级
        if hasattr(event, 'get_platform_id') and callable(event.get_platform_id):
            try:
                ext_platform = event.get_platform_id()
                if ext_platform:
                    return ext_platform
            except Exception as e:
                logger.debug(f"调用 get_platform_id 失败: {str(e)}")

        if hasattr(event, 'adapter') and hasattr(event.adapter, 'platform_name'):
            if event.adapter.platform_name:
                return event.adapter.platform_name

        # 极度异常情况：存在 event 但完全无法提取平台特征，记录风险日志
        fallback_platform = self._get_config().get(KEY_DEFAULT_PLATFORM)
        logger.warning(
            f"无法从有效事件中提取平台标识，被迫降级路由至默认平台 [{fallback_platform}]，"
            f"多适配器环境下存在跨平台串线风险！"
        )
        return fallback_platform

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

        platform_id = self._extract_platform_id(event)

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
        success = await self.send_private_message(user_id, content, event)
        event.stop_event()
        if not success:
            return event.plain_result("发送失败：您的发送频率过高，请稍后再试。")
        return event.plain_result("私聊消息已成功发送。")

    @filter.llm_tool(name="message_to_admin")
    async def message_to_admin(self, event: AstrMessageEvent, content: str) -> MessageEventResult:
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
        config = self._get_config()
        admin_id = config.get(KEY_ADMIN_ID, "")
        display_admin_id = admin_id if admin_id else "未配置"

        return event.plain_result(
            f"管理员ID: {display_admin_id}\n"
            f"告状功能: {'开启' if config.get(KEY_ENABLE_SUE, True) else '关闭'}\n"
            f"自定义错误消息: {config.get(KEY_CUSTOM_ERROR_MSG)}\n"
            f"启用自定义错误: {'开启' if config.get(KEY_ENABLE_CUSTOM_ERROR, True) else '关闭'}"
        )

    @filter.llm_tool(name="group_message")
    async def send_group_message(self, event: AstrMessageEvent, group_id: str, content: str) -> MessageEventResult:
        source_id = self._get_source_id(event)
        limit_key = f"group_{source_id}"

        if not self._check_rate_limit(limit_key):
            logger.warning(f"群消息频率限制：调用来源 {source_id} 触发频率过高")
            return event.plain_result("群消息发送失败：您调用工具的频率过高，请稍后再试。")

        group_id_str = str(group_id)
        logger.info(f"发送群消息：来源 [{source_id}] -> 目标群 [{group_id_str}]，消息长度 {len(content)}")

        platform_id = self._extract_platform_id(event)

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
        except Exception as e:
            logger.exception(
                f"群消息底层发送接口调用失败 | "
                f"当前路由平台: {platform_id} | "
                f"目标群ID(str): '{group_id_str}' | "
                f"异常信息: {e}"
            )
            return event.plain_result("群消息发送失败：系统暂时无法发送消息，请稍后再试")

    def _replace_error_variables(self, message, error_message="", error_code=""):
        message = message.replace("{error_message}", error_message)
        message = message.replace("{error_code}", error_code)
        return message

    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent):
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

        except (AttributeError, TypeError) as e:
            logger.exception(f"错误拦截器解析消息结构失败（属性或类型错误）: {e}")
        except re.error as e:
            logger.exception(f"错误拦截器执行正则匹配异常: {e}")

    async def terminate(self):
        pass