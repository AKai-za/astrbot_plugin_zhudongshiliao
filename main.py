from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.event.filter import event_message_type, EventMessageType
from astrbot.api import logger
from astrbot.api.message_components import Plain
from astrbot.api.event import MessageChain
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
from astrbot.api.provider import ProviderRequest
import json
import os
import re
import traceback

@register("astrbot_plugin_zhudongshiliao", "引灯续昼", "自动私聊插件，当用户发送消息时，自动私聊用户。支持群消息总结、错误信息转发等功能。", "v1.4.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config_file = os.path.join(os.path.dirname(__file__), "config.json")
        self.config = self._load_config()
        self.muted_groups = set()  # 被禁言的群
        self.user_cache = {}  # 存储用户信息缓存，用于昵称到ID的解析

    async def initialize(self):
        """插件初始化"""
        await self._load_webui_config()
        logger.info("自动私聊插件初始化完成")

    async def _load_webui_config(self):
        """从WebUI加载配置"""
        try:
            webui_config = self.context.get_config()
            if webui_config:
                logger.info("从WebUI加载配置成功")
                for key, value in webui_config.items():
                    if key != "group_message_history":
                        self.config[key] = value
                self._save_config(self.config)
            else:
                logger.warning("WebUI配置为空")
        except Exception as e:
            logger.error(f"从WebUI加载配置失败: {e}")
            logger.error(traceback.format_exc())

    def get_realtime_config(self):
        """获取实时配置"""
        try:
            webui_config = self.context.get_config()
            if webui_config:
                return webui_config
            return self.config
        except Exception as e:
            logger.error(f"获取实时配置失败: {e}")
            return self.config

    def _load_config(self):
        """加载配置文件"""
        default_config = {
            "admin_list": [],  # 管理员ID列表
            "private_keywords": ["私聊", "私信", "私发", "发给我"],  # 私聊触发关键词
            "summary_keywords": ["总结", "汇总", "总结一下"],  # 总结触发关键词
            "report_keywords": ["告诉你创造者", "告诉开发者"],  # 群员汇报触发关键词
            "error_format": "【错误信息】\n方法: {method}\n错误: {error}",  # 错误信息格式
            "report_status": False,  # 是否汇报发送状态
            "private_send_id": "",  # 私发ID
            "group_message_history": {}  # 群消息历史
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

    def is_admin(self, user_id):
        """检测用户是否为管理员"""
        config = self.get_realtime_config()
        admin_list = config.get("admin_list", [])
        return user_id in admin_list

    async def call_llm(self, prompt, event=None):
        """调用大模型"""
        try:
            # 使用当前会话的模型
            if event:
                # 构建LLM请求
                request = ProviderRequest(
                    prompt=prompt,
                    model="",  # 使用默认模型
                    temperature=0.7
                )
                # 发送LLM请求
                response = await self.context.llm_request(request)
                return response.content
            return ""
        except Exception as e:
            logger.error(f"调用大模型失败: {e}")
            logger.error(traceback.format_exc())
            return ""

    async def send_private_message(self, user_id, message, event=None):
        """发送私聊消息"""
        try:
            config = self.get_realtime_config()
            private_send_id = config.get("private_send_id", "")
            
            if private_send_id:
                user_id = private_send_id
                logger.info(f"使用私发ID: {private_send_id}")

            platform_id = "qq"
            if event:
                platform_id = event.get_platform_id()

            session = MessageSession(
                platform_name=platform_id,
                message_type=MessageType.FRIEND_MESSAGE,
                session_id=str(user_id)
            )

            message_chain = MessageChain().message(message)
            success = await self.context.send_message(session, message_chain)

            if success:
                logger.info(f"成功发送私聊消息到 {user_id}")
                return True
            else:
                logger.warning(f"发送私聊消息到 {user_id} 失败")
                return False

        except Exception as e:
            logger.error(f"发送私聊消息失败: {e}")
            logger.error(traceback.format_exc())
            await self.send_error_message(None, "send_private_message", str(e), traceback.format_exc())
            return False

    async def send_error_message(self, event, method, error, traceback_str):
        """发送错误信息"""
        try:
            config = self.get_realtime_config()
            error_format = config.get("error_format", "【错误信息】\n方法: {method}\n错误: {error}")
            private_send_id = config.get("private_send_id", "")

            error_info = error_format.format(
                method=method,
                error=error
            )

            if private_send_id:
                await self.send_private_message(private_send_id, error_info)
            elif event:
                return event.plain_result(error_info)

        except Exception as e:
            logger.error(f"发送错误信息失败: {e}")
            logger.error(traceback.format_exc())
            return None

    async def handle_mute_event(self, event: AstrMessageEvent):
        """处理禁言事件"""
        try:
            group_id = event.get_group_id()
            if not group_id:
                return

            # 添加到被禁言群列表
            self.muted_groups.add(group_id)
            logger.info(f"群 {group_id} 已被禁言，开始屏蔽消息")

            # 向管理员发送被禁言信息
            config = self.get_realtime_config()
            admin_list = config.get("admin_list", [])
            
            for admin_id in admin_list:
                # 生成思考内容
                thinking_prompt = f"我在群 {group_id} 中被禁言了，需要向管理员汇报这件事。请生成一个礼貌的汇报消息。"
                thinking = await self.call_llm(thinking_prompt, event)
                
                # 发送被禁言信息
                message = f"【被禁言通知】\n我在群 {group_id} 中被禁言了。\n\n【思考】\n{thinking}"
                await self.send_private_message(admin_id, message, event)

        except Exception as e:
            logger.error(f"处理禁言事件失败: {e}")
            logger.error(traceback.format_exc())

    async def handle_report_request(self, event: AstrMessageEvent, report_content):
        """处理群员汇报请求"""
        try:
            config = self.get_realtime_config()
            admin_list = config.get("admin_list", [])
            
            for admin_id in admin_list:
                # 生成思考内容
                thinking_prompt = f"群员要求我向管理员汇报：{report_content}。请生成一个合适的汇报消息。"
                thinking = await self.call_llm(thinking_prompt, event)
                
                # 发送汇报信息
                message = f"【群员汇报】\n{report_content}\n\n【思考】\n{thinking}"
                await self.send_private_message(admin_id, message, event)

        except Exception as e:
            logger.error(f"处理群员汇报失败: {e}")
            logger.error(traceback.format_exc())

    async def handle_private_request(self, event: AstrMessageEvent, message_content):
        """处理私聊请求"""
        try:
            user_id = event.get_sender_id()
            
            # 生成思考内容
            thinking_prompt = f"管理员要求我发送私聊消息：{message_content}。请生成一个合适的回复。"
            thinking = await self.call_llm(thinking_prompt, event)
            
            # 发送私聊消息
            message = f"【私聊消息】\n{message_content}\n\n【思考】\n{thinking}"
            await self.send_private_message(user_id, message, event)

        except Exception as e:
            logger.error(f"处理私聊请求失败: {e}")
            logger.error(traceback.format_exc())

    async def handle_summary_request(self, event: AstrMessageEvent):
        """处理总结请求"""
        try:
            user_id = event.get_sender_id()
            group_id = event.get_group_id()
            
            if not group_id:
                return

            # 获取群消息历史
            message_history = self.config.get("group_message_history", {}).get(group_id, [])
            if not message_history:
                return

            # 生成思考内容
            thinking_prompt = f"请总结以下群消息：\n{message_history[-20:]}\n\n请提供一个简洁的总结。"
            thinking = await self.call_llm(thinking_prompt, event)
            
            # 生成总结
            summary_prompt = f"基于以下思考，生成群消息总结：\n{thinking}"
            summary = await self.call_llm(summary_prompt, event)
            
            # 发送总结
            message = f"【群消息总结】\n{summary}\n\n【思考】\n{thinking}"
            await self.send_private_message(user_id, message, event)

        except Exception as e:
            logger.error(f"处理总结请求失败: {e}")
            logger.error(traceback.format_exc())

    @event_message_type(EventMessageType.ALL)
    async def on_all_messages(self, event: AstrMessageEvent):
        """处理所有消息"""
        try:
            user_id = event.get_sender_id()
            message_str = event.message_str
            group_id = event.get_group_id()

            # 检查是否在被禁言的群中
            if group_id and group_id in self.muted_groups:
                logger.debug(f"群 {group_id} 已被禁言，忽略消息")
                return

            # 缓存用户信息
            if group_id:
                sender_name = event.get_sender_name()
                if sender_name:
                    self.user_cache[sender_name] = user_id

            # 检查是否为管理员
            if not self.is_admin(user_id):
                logger.debug(f"用户 {user_id} 不是管理员，忽略消息")
                return

            # 检查是否触发禁言事件
            if "禁言" in message_str:
                await self.handle_mute_event(event)
                return

            # 检查是否触发群员汇报
            config = self.get_realtime_config()
            report_keywords = config.get("report_keywords", ["告诉你创造者", "告诉开发者"])
            for keyword in report_keywords:
                if keyword in message_str:
                    report_content = message_str.split(keyword)[-1].strip()
                    await self.handle_report_request(event, report_content)
                    return

            # 检查是否触发私聊关键词
            private_keywords = config.get("private_keywords", ["私聊", "私信", "私发", "发给我"])
            for keyword in private_keywords:
                if keyword in message_str:
                    # 提取消息内容
                    content_match = re.search(r'[\"\'\`](.+?)[\"\'\`]', message_str)
                    if content_match:
                        message_content = content_match.group(1)
                    else:
                        # 尝试提取关键词后的内容
                        parts = message_str.split(keyword)
                        if len(parts) > 1:
                            message_content = parts[1].strip()
                        else:
                            message_content = ""
                    
                    if message_content:
                        await self.handle_private_request(event, message_content)
                    return

            # 检查是否触发总结关键词
            summary_keywords = config.get("summary_keywords", ["总结", "汇总", "总结一下"])
            for keyword in summary_keywords:
                if keyword in message_str:
                    await self.handle_summary_request(event)
                    return

        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            logger.error(traceback.format_exc())
            result = await self.send_error_message(event, "on_all_messages", str(e), traceback.format_exc())
            if result:
                yield result

    async def terminate(self):
        """插件卸载"""
        logger.info("自动私聊插件已卸载")
