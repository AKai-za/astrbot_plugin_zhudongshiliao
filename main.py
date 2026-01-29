from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.event.filter import command
from astrbot.api import logger
from astrbot.api.message_components import Plain
from astrbot.api.event import MessageChain
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
import json
import os
import re
import traceback

@register("astrbot_plugin_zhudongshiliao", "引灯续昼", "自动私聊插件，当用户发送消息时，自动私聊用户。支持群消息总结、错误信息转发等功能。", "v1.3.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config_file = os.path.join(os.path.dirname(__file__), "config.json")
        self.config = self._load_config()
        self.user_origins = {}  # 存储用户的 unified_msg_origin
        self.group_origins = {}  # 存储群的 unified_msg_origin
        self.user_cache = {}  # 存储用户信息缓存，用于昵称到ID的解析
        self.admin_ids = set()  # 存储管理员ID

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        # 从 WebUI 读取配置
        await self._load_webui_config()
        logger.info("自动私聊插件初始化完成")

    async def _load_webui_config(self):
        """从 WebUI 读取配置"""
        try:
            # 使用 context 获取 WebUI 配置
            webui_config = self.context.get_config()
            if webui_config:
                logger.info("从 WebUI 加载配置成功")
                logger.info(f"WebUI 配置内容: {webui_config}")
                # 合并 WebUI 配置和本地配置
                for key, value in webui_config.items():
                    if key != "group_message_history":  # 消息历史不从 WebUI 加载
                        self.config[key] = value
                # 保存合并后的配置
                self._save_config(self.config)
                logger.info(f"合并后的配置: {self.config}")
            else:
                logger.warning("WebUI 配置为空")
        except Exception as e:
            logger.error(f"从 WebUI 加载配置失败: {e}")
            logger.error(traceback.format_exc())
    
    def get_realtime_config(self):
        """获取实时配置
        
        Returns:
            dict: 实时配置
        """
        try:
            webui_config = self.context.get_config()
            if webui_config:
                logger.debug("获取实时配置成功")
                return webui_config
            else:
                logger.debug("WebUI 配置为空，使用本地配置")
                return self.config
        except Exception as e:
            logger.error(f"获取实时配置失败: {e}")
            return self.config
    
    def is_admin(self, user_id):
        """检测用户是否为管理员
        
        Args:
            user_id: 用户ID
            
        Returns:
            bool: 是否为管理员
        """
        # 从配置中获取管理员ID列表
        config = self.get_realtime_config()
        admin_list = config.get("admin_list", [])
        
        # 检查用户ID是否在管理员列表中
        if user_id in admin_list:
            return True
        
        # 检查用户ID是否在内存缓存的管理员集合中
        if user_id in self.admin_ids:
            return True
        
        return False
    
    def add_admin(self, user_id):
        """添加管理员
        
        Args:
            user_id: 用户ID
        """
        self.admin_ids.add(user_id)
        logger.info(f"Added admin: {user_id}")
    
    def remove_admin(self, user_id):
        """移除管理员
        
        Args:
            user_id: 用户ID
        """
        if user_id in self.admin_ids:
            self.admin_ids.remove(user_id)
            logger.info(f"Removed admin: {user_id}")

    def _load_config(self):
        """加载配置文件"""
        default_config = {
            "private_send_id": "",  # 私发ID，所有私发消息都会发给这个ID
            "summary_keywords": ["总结", "汇总", "总结一下"],  # 群消息总结触发关键词
            "private_keywords": ["私聊", "私信","私发"],  # 私聊触发关键词
            "auto_summary": False,  # 是否自动总结群消息
            "summary_interval": 300,  # 自动总结间隔（秒）
            "summary_count": 20,  # 总结消息数量
            "error_send_mode": "private",  # 错误信息发送方式：private（私聊）或 group（群聊）
            "error_format": "【错误信息】\n方法: {method}\n错误: {error}",  # 错误信息格式
            "report_status": True,  # 是否在群里汇报发送状况
            "summary_provider": "",  # 总结模型提供商
            "vision_provider": "",  # 视觉模型提供商
            "private_prompt": "请根据用户的要求，将以下内容发送给用户：{content}",  # 私发提示词
            "summary_prompt": "请总结以下群消息，提取关键信息：{messages}",  # 总结提示词
            "admin_list": [],  # 管理员ID列表
            "group_message_history": {}  # 群消息历史
        }
        
        if not os.path.exists(self.config_file):
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, ensure_ascii=False, indent=2)
            return default_config
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # 合并默认配置和现有配置
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

    # 监听所有消息
    @command("")
    async def on_all_messages(self, event: AstrMessageEvent):
        """监听所有消息，记录群消息历史，处理触发关键词"""
        try:
            # 记录用户的 unified_msg_origin
            user_id = event.get_sender_id()
            unified_msg_origin = event.unified_msg_origin
            if unified_msg_origin:
                self.user_origins[user_id] = unified_msg_origin
                logger.debug(f"记录用户 {user_id} 的 unified_msg_origin: {unified_msg_origin}")
            
            # 检查是否是群消息
            group_id = event.get_group_id()
            if group_id:
                # 记录群的 unified_msg_origin
                if unified_msg_origin:
                    self.group_origins[group_id] = unified_msg_origin
                    logger.debug(f"记录群 {group_id} 的 unified_msg_origin: {unified_msg_origin}")
                
                # 缓存用户信息（昵称到ID的映射）
                sender_name = event.get_sender_name()
                if sender_name:
                    self.user_cache[sender_name] = user_id
                    logger.debug(f"缓存用户信息: {sender_name} -> {user_id}")
                
                # 记录群消息历史
                if group_id not in self.config["group_message_history"]:
                    self.config["group_message_history"][group_id] = []
                
                # 添加消息到历史记录
                message_info = {
                    "sender": event.get_sender_name(),
                    "message": event.message_str,
                    "time": event.get_timestamp()
                }
                self.config["group_message_history"][group_id].append(message_info)
                
                # 限制历史记录长度
                if len(self.config["group_message_history"][group_id]) > 100:
                    self.config["group_message_history"][group_id] = self.config["group_message_history"][group_id][-100:]
                
                # 保存配置
                self._save_config(self.config)
                
                # 检查是否触发总结关键词
                message_str = event.message_str.lower()
                
                # Get real-time configuration
                config = self.get_realtime_config()
                summary_keywords = config.get("summary_keywords", ["总结", "汇总", "总结一下"])
                
                logger.info(f"Checking summary keywords in: {message_str}")
                logger.info(f"Using summary keywords: {summary_keywords}")
                for keyword in summary_keywords:
                    if keyword in message_str:
                        logger.info(f"Found summary keyword: {keyword}")
                        async for result in self.handle_summary_request(event):
                            yield result
                        break
                
                # 检查是否触发私聊关键词
                private_keywords = config.get("private_keywords", ["私聊", "私信", "私发"])
                
                logger.info(f"Using private keywords: {private_keywords}")
                for keyword in private_keywords:
                    if keyword in message_str:
                        logger.info(f"Found private keyword: {keyword}")
                        async for result in self.handle_private_request(event):
                            yield result
                        break
                
                # 处理自动私聊
                async for result in self.auto_private_message(event):
                    yield result
            else:
                # 处理私聊消息
                message_str = event.message_str
                logger.info(f"收到私聊消息 from {user_id}: {message_str}")
                
                # 这里可以添加私聊消息的处理逻辑
                # 例如：处理用户的设置请求，处理用户的命令等
        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            # 转发错误信息
            result = await self.send_error_message(event, "on_all_messages", str(e), traceback.format_exc())
            if result:
                yield result

    async def handle_summary_request(self, event: AstrMessageEvent):
        """处理群消息总结请求"""
        try:
            group_id = event.get_group_id()
            if not group_id:
                return
            
            # 获取实时配置
            config = self.get_realtime_config()
            
            # 获取群消息历史
            message_history = self.config["group_message_history"].get(group_id, [])
            if not message_history:
                yield event.plain_result("暂无消息记录，无法总结")
                return
            
            # 生成消息总结
            summary_count = config.get("summary_count", 20)
            summary = await self.generate_summary(message_history, summary_count)
            
            # 私聊发送总结
            sender_id = event.get_sender_id()
            success = await self.send_private_message(sender_id, f"群消息总结：\n{summary}", event)
            
            # 根据发送结果回复用户
            report_status = config.get("report_status", True)
            logger.info(f"Report status: {report_status}")
            if report_status:
                if success:
                    yield event.plain_result("已将群消息总结发送到您的私聊")
                else:
                    yield event.plain_result("发送私聊消息失败")
        except Exception as e:
            logger.error(f"处理总结请求失败: {e}")
            # 转发错误信息
            async for result in self.send_error_message(event, "handle_summary_request", str(e), traceback.format_exc()):
                yield result

    async def handle_private_request(self, event: AstrMessageEvent):
        """处理私聊请求"""
        try:
            sender_id = event.get_sender_id()
            message_str = event.message_str
            
            # 获取实时配置
            config = self.get_realtime_config()
            
            # 发送私聊消息
            success = await self.send_private_message(sender_id, f"您请求的私聊内容：\n{message_str}", event)
            
            # 根据发送结果回复用户
            report_status = config.get("report_status", True)
            logger.info(f"Report status: {report_status}")
            if report_status:
                if success:
                    yield event.plain_result("已发送私聊消息")
                else:
                    yield event.plain_result("发送私聊消息失败")
        except Exception as e:
            logger.error(f"处理私聊请求失败: {e}")
            # 转发错误信息
            async for result in self.send_error_message(event, "handle_private_request", str(e), traceback.format_exc()):
                yield result

    async def generate_summary(self, message_history, count=20):
        """生成消息总结"""
        # 简单的总结逻辑，实际应用中可以调用AI进行更智能的总结
        summary = "最近的群消息：\n"
        for msg in message_history[-count:]:  # 根据配置总结指定数量的消息
            # 限制每条消息的长度，避免消息过长
            message_text = msg['message']
            if len(message_text) > 100:
                message_text = message_text[:100] + "..."
            summary += f"[{msg['sender']}] {message_text}\n"
        
        # 限制总结总长度，避免消息过长导致发送超时
        if len(summary) > 2000:
            summary = summary[:2000] + "\n...(消息过长，已截断)"
        
        return summary

    async def send_private_message(self, user_id, message, event=None):
        """发送私聊消息
        
        Args:
            user_id: 目标用户ID
            message: 要发送的消息内容
            event: 可选的事件对象，用于获取平台信息
            
        Returns:
            bool: 是否发送成功
        """
        # 使用 AstrBot 的消息发送API发送私聊消息
        try:
            logger.info(f"发送私聊消息到 {user_id}: {message}")
            
            # 获取实时配置
            config = self.get_realtime_config()
            private_send_id = config.get("private_send_id", "")
            summary_provider = config.get("summary_provider", "")
            private_prompt = config.get("private_prompt", "请根据用户的要求，将以下内容发送给用户：{content}")
            
            # 检查是否配置了私发ID
            if private_send_id:
                # 如果配置了私发ID，所有私发消息都发给这个ID
                user_id = private_send_id
                logger.info(f"使用私发ID: {private_send_id}")
            
            # 获取平台 ID
            platform_id = "qq"  # 默认使用 qq 作为平台 ID
            if event:
                # 如果提供了事件，使用事件的平台信息
                platform_id = event.get_platform_id()
                logger.info(f"使用事件平台ID: {platform_id}")
            
            # 构建私聊消息会话
            # MessageSession 格式: {platform_id}:{message_type}:{session_id}
            session = MessageSession(
                platform_name=platform_id,
                message_type=MessageType.FRIEND_MESSAGE,
                session_id=str(user_id)
            )
            
            logger.info(f"构建私聊会话: {session}")
            
            # 构建消息链
            message_chain = MessageChain().message(message)
            
            # 发送消息
            success = await self.context.send_message(session, message_chain)
            
            if success:
                logger.info(f"成功发送私聊消息到 {user_id}")
                return True
            else:
                logger.warning(f"发送私聊消息到 {user_id} 失败，可能平台不匹配")
                return False
                
        except Exception as e:
            logger.error(f"发送私聊消息失败: {e}")
            logger.error(traceback.format_exc())
            # 转发错误信息
            await self.send_error_message(None, "send_private_message", str(e), traceback.format_exc())
            return False

    def resolve_user_id(self, identifier):
        """解析用户标识符（可能是昵称或ID）为用户ID
        
        Args:
            identifier: 用户标识符（昵称或ID）
            
        Returns:
            str: 用户ID
        """
        # 如果已经是数字ID，直接返回
        if identifier.isdigit():
            return identifier
        
        # 尝试从用户缓存中查找昵称对应的ID
        if identifier in self.user_cache:
            user_id = self.user_cache[identifier]
            logger.info(f"从缓存中解析昵称 {identifier} 为ID: {user_id}")
            return user_id
        
        # 如果没有找到，返回原始标识符
        logger.warning(f"无法解析昵称 {identifier} 为ID，返回原始标识符")
        return identifier

    async def send_error_message(self, event, method, error, traceback_str):
        """发送错误信息"""
        try:
            # 获取实时配置
            config = self.get_realtime_config()
            private_send_id = config.get("private_send_id", "")
            error_send_mode = config.get("error_send_mode", "private")
            error_format = config.get("error_format", "【错误信息】\n方法: {method}\n错误: {error}")
            
            logger.info(f"Error send mode: {error_send_mode}")
            logger.info(f"Private send ID: {private_send_id}")
            
            # 生成错误信息（只包含简短信息，不包含完整 traceback）
            error_info = error_format.format(
                method=method,
                error=error,
                traceback=""  # 不显示完整 traceback，只显示简短错误信息
            )
            
            # 根据配置选择发送方式
            if error_send_mode == "private" and private_send_id:
                # 私聊发送错误信息
                success = await self.send_private_message(private_send_id, error_info)
                if not success:
                    # 如果私聊发送失败，根据配置决定是否发送到当前会话
                    # 只有当 error_send_mode 为 "group" 时才发送到群聊
                    logger.info("私聊发送失败，根据配置不发送到当前会话")
            elif error_send_mode == "group" and event:
                # 群聊发送错误信息
                group_id = event.get_group_id()
                if group_id and group_id in self.group_origins:
                    origin = self.group_origins[group_id]
                    message_chain = MessageChain().message(error_info)
                    await self.context.send_message(origin, message_chain)
                    logger.info(f"已在群 {group_id} 中发送错误信息")
                else:
                    # 如果没有找到群的 unified_msg_origin，发送到当前会话
                    return event.plain_result(error_info)
                    logger.info("未找到群的 unified_msg_origin，已将错误信息发送到当前会话")
            elif event:
                # 其他情况，发送到当前会话
                return event.plain_result(error_info)
                logger.info("已将错误信息发送到当前会话")
            else:
                logger.warning("无法发送错误信息：没有配置私发ID且没有事件对象")
                
        except Exception as e:
            logger.error(f"发送错误信息失败: {e}")
            logger.error(traceback.format_exc())
            return None

    # 主动私聊指令
    @command("private")
    async def command_private(self, event: AstrMessageEvent):
        """主动触发私聊，格式：/private <用户ID> <消息内容>"""
        try:
            message_str = event.message_str
            # 解析命令参数
            parts = message_str.split(" ", 2)
            if len(parts) < 3:
                yield event.plain_result("命令格式错误，请使用：/private <用户ID> <消息内容>")
                return
            
            user_id = parts[1]
            # 尝试解析昵称到ID
            user_id = self.resolve_user_id(user_id)
            private_message = parts[2]
            
            # 发送私聊消息
            success = await self.send_private_message(user_id, private_message, event)
            
            # 根据发送结果回复用户
            config = self.get_realtime_config()
            report_status = config.get("report_status", True)
            if report_status:
                if success:
                    yield event.plain_result(f"已向用户 {user_id} 发送私聊消息")
                else:
                    yield event.plain_result("发送私聊消息失败")
        except Exception as e:
            logger.error(f"处理私聊指令失败: {e}")
            # 转发错误信息
            result = await self.send_error_message(event, "command_private", str(e), traceback.format_exc())
            if result:
                yield result

    # 自动私聊功能 - 基于关键词的被动私聊
    async def auto_private_message(self, event: AstrMessageEvent):
        """自动私聊功能，当用户发送特定消息时自动私聊"""
        try:
            user_id = event.get_sender_id()
            message_str = event.message_str
            logger.info(f"Processing auto private message for: {message_str}")
            
            # 获取实时配置
            config = self.get_realtime_config()
            private_keywords = config.get("private_keywords", ["私聊", "私信", "私发"])
            summary_keywords = config.get("summary_keywords", ["总结", "汇总", "总结一下"])
            report_status = config.get("report_status", True)
            
            logger.info(f"Report status: {report_status}")
            
            # 检查用户是否为管理员
            is_admin_user = self.is_admin(user_id)
            logger.info(f"User {user_id} is admin: {is_admin_user}")
            
            # 检查是否包含发给特定用户的模式
            send_to_pattern = re.search(r'发给([^\s]+)\s*(.*)', message_str)
            if send_to_pattern:
                target_name = send_to_pattern.group(1)
                message_content = send_to_pattern.group(2).strip()
                logger.info(f"Found send to pattern: target={target_name}, content={message_content}")
                
                # 解析目标用户ID（支持昵称）
                target_id = self.resolve_user_id(target_name)
                logger.info(f"Resolved target ID: {target_id}")
                
                if message_content:
                    # 发送私聊消息
                    success = await self.send_private_message(target_id, message_content, event)
                    
                    # 根据发送结果回复用户
                    if report_status:
                        if success:
                            yield event.plain_result(f"已向用户 {target_name} 发送私聊消息")
                        else:
                            yield event.plain_result("发送私聊消息失败")
                else:
                    if report_status:
                        yield event.plain_result("请告诉我要发送的消息内容")
                return
            
            # 检查是否包含私发相关的自然语言模式
            private_patterns = private_keywords + ["发给我", "私信我", "私聊我", "私发给我"]
            has_private_pattern = any(pattern in message_str for pattern in private_patterns)
            
            # 检查是否包含总结相关的自然语言模式
            summary_patterns = summary_keywords + ["总结一下", "汇总一下", "总结群里的消息"]
            has_summary_pattern = any(pattern in message_str for pattern in summary_patterns)
            
            if has_private_pattern:
                logger.info("Found private message pattern")
                # 尝试提取要发送的消息内容
                # 支持多种格式：
                # "幽幽，你私发'测试'这条消息给我"
                # "私发 测试"
                # "私发：测试"
                # "把'测试'发给我"
                
                # 尝试匹配引号内的内容
                quote_match = re.search(r'["''](.+?)["'']', message_str)
                if quote_match:
                    # 提取引号内的内容
                    private_message = quote_match.group(1)
                    logger.info(f"从引号中提取消息: {private_message}")
                else:
                    # 尝试匹配私发关键词后面的内容
                    # 去掉私发关键词
                    remaining_text = message_str
                    for pattern in private_patterns:
                        remaining_text = remaining_text.replace(pattern, "").strip()
                    # 去掉常见的连接词
                    remaining_text = re.sub(r'^(这条消息|给我|一下|一下给我|，|。|！|？|,|\.|!|\?)+', '', remaining_text)
                    private_message = remaining_text.strip()
                    logger.info(f"从文本中提取消息: {private_message}")
                
                # 如果提取到了消息内容，发送私聊
                if private_message:
                    success = await self.send_private_message(user_id, private_message, event)
                    
                    # 根据发送结果回复用户
                    if report_status:
                        if success:
                            yield event.plain_result("已发送私聊消息")
                        else:
                            yield event.plain_result("发送私聊消息失败")
                else:
                    # 如果没有提取到消息内容，提示用户
                    if report_status:
                        yield event.plain_result("请告诉我你要发送什么消息")
            
            # 检查是否包含总结相关的自然语言模式
            elif has_summary_pattern:
                logger.info("Found summary pattern")
                # 触发总结并私发
                async for result in self.handle_summary_request(event):
                    yield result
            
            # 示例：当用户发送 "你好" 时，自动私聊用户
            elif "你好" in message_str:
                await self.send_private_message(user_id, "你好！", event)
                if report_status:
                    yield event.plain_result("已发送私聊消息")
        except Exception as e:
            logger.error(f"处理自动私聊失败: {e}")
            logger.error(traceback.format_exc())
            # 转发错误信息
            result = await self.send_error_message(event, "auto_private_message", str(e), traceback.format_exc())
            if result:
                yield result

    # 群消息总结指令
    @command("summary")
    async def command_summary(self, event: AstrMessageEvent):
        """手动触发群消息总结，格式：/summary [群ID]"""
        try:
            message_str = event.message_str
            # 解析命令参数
            parts = message_str.split(" ")
            
            # 获取实时配置
            config = self.get_realtime_config()
            
            # 如果指定了群ID，使用指定的群ID
            if len(parts) > 1:
                group_id = parts[1]
                # 检查群ID是否存在于历史记录中
                if group_id not in self.config["group_message_history"]:
                    yield event.plain_result(f"未找到群 {group_id} 的消息记录")
                    return
                
                # 生成消息总结
                message_history = self.config["group_message_history"][group_id]
                summary_count = config.get("summary_count", 20)
                summary = await self.generate_summary(message_history, summary_count)
                
                # 私聊发送总结
                sender_id = event.get_sender_id()
                success = await self.send_private_message(sender_id, f"群 {group_id} 的消息总结：\n{summary}", event)
                
                # 根据发送结果回复用户
                report_status = config.get("report_status", True)
                if report_status:
                    if success:
                        yield event.plain_result(f"已将群 {group_id} 的消息总结发送到您的私聊")
                    else:
                        yield event.plain_result("发送私聊消息失败")
            else:
                # 否则使用当前群
                async for result in self.handle_summary_request(event):
                    yield result
        except Exception as e:
            logger.error(f"处理总结指令失败: {e}")
            # 转发错误信息
            async for result in self.send_error_message(event, "command_summary", str(e), traceback.format_exc()):
                yield result

    # 设置私发ID指令
    @command("set_private_id")
    async def command_set_private_id(self, event: AstrMessageEvent):
        """设置私发ID，格式：/set_private_id <用户ID>"""
        try:
            message_str = event.message_str
            # 解析命令参数
            parts = message_str.split(" ")
            if len(parts) < 2:
                yield event.plain_result("命令格式错误，请使用：/set_private_id <用户ID>")
                return
            
            private_send_id = parts[1]
            # 更新配置
            self.config["private_send_id"] = private_send_id
            self._save_config(self.config)
            
            yield event.plain_result(f"已设置私发ID为：{private_send_id}")
        except Exception as e:
            logger.error(f"处理设置私发ID指令失败: {e}")
            # 转发错误信息
            result = await self.send_error_message(event, "command_set_private_id", str(e), traceback.format_exc())
            if result:
                yield result

    # 查看配置指令
    @command("config")
    async def command_config(self, event: AstrMessageEvent):
        """查看当前配置"""
        try:
            config_info = f"【自动私聊插件配置】\n"
            config_info += f"私发ID：{self.config['private_send_id']}\n"
            config_info += f"群消息总结触发关键词：{', '.join(self.config['summary_keywords'])}\n"
            config_info += f"私聊触发关键词：{', '.join(self.config['private_keywords'])}\n"
            config_info += f"是否自动总结群消息：{'是' if self.config['auto_summary'] else '否'}\n"
            config_info += f"自动总结间隔：{self.config['summary_interval']} 秒\n"
            config_info += f"总结消息数量：{self.config['summary_count']}\n"
            config_info += f"错误信息发送方式：{self.config['error_send_mode']}\n"
            config_info += f"错误信息格式：{self.config['error_format']}\n"
            config_info += f"已记录消息的群数量：{len(self.config['group_message_history'])}\n"
            
            # 发送配置信息给用户
            sender_id = event.get_sender_id()
            await self.send_private_message(sender_id, config_info, event)
            yield event.plain_result("已将当前配置发送到您的私聊")
        except Exception as e:
            logger.error(f"处理配置指令失败: {e}")
            # 转发错误信息
            result = await self.send_error_message(event, "command_config", str(e), traceback.format_exc())
            if result:
                yield result

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        logger.info("自动私聊插件已卸载")
