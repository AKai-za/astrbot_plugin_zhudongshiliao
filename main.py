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
        self.muted_groups = set()
        self.user_cache = {}

    async def initialize(self):
        """插件初始化"""
        if not os.path.exists(self.config_file):
            logger.info("配置文件不存在，创建默认配置")
            self.config = self._load_config()
        else:
            logger.info("配置文件存在，加载配置")
            self.config = self._load_config()
        
        await self._load_webui_config()
        logger.info("自动私聊插件初始化完成")
        logger.info(f"管理员列表: {self.config.get('admin_list', [])}")

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
                if "admin_list" not in webui_config or not webui_config["admin_list"]:
                    webui_config["admin_list"] = self.config.get("admin_list", ["2757808353"])
                return webui_config
            return self.config
        except Exception as e:
            logger.error(f"获取实时配置失败: {e}")
            return self.config

    def _load_config(self):
        """加载配置文件"""
        default_config = {
            "admin_list": ["2757808353"],
            "private_keywords": ["私聊", "私信", "私发", "发给我"],
            "summary_keywords": ["总结", "汇总", "总结一下"],
            "report_keywords": ["告诉你创造者", "告诉开发者"],
            "error_format": "【错误信息】\n方法: {method}\n错误: {error}",
            "report_status": False,
            "private_send_id": "",
            "group_message_history": {}
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
        user_id_str = str(user_id)
        admin_list_str = [str(admin) for admin in admin_list]
        logger.info(f"检查用户 {user_id_str} 是否为管理员，管理员列表: {admin_list_str}")
        return user_id_str in admin_list_str

    async def call_llm(self, prompt, event=None):
        """调用大模型"""
        try:
            if event:
                request = ProviderRequest(
                    prompt=prompt,
                    model=""
                )
                response = await self.context.llm_request(request)
                logger.info(f"大模型调用成功，响应长度: {len(response.content) if response else 0}")
                return response.content if response else ""
            else:
                try:
                    request = ProviderRequest(
                        prompt=prompt,
                        model=""
                    )
                    response = await self.context.llm_request(request)
                    logger.info(f"无event大模型调用成功，响应长度: {len(response.content) if response else 0}")
                    return response.content if response else ""
                except Exception as e:
                    logger.debug(f"无event大模型调用失败: {e}")
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
            if event and hasattr(event, 'get_platform_id'):
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
            error_str = str(e)
            if "禁言" in error_str or "120" in error_str or "EventChecker Failed" in error_str:
                logger.warning(f"检测到禁言错误: {e}")
                if event:
                    await self.handle_mute_event(event)
            await self.send_error_message(event, "send_private_message", str(e), traceback.format_exc())
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

            admin_list = config.get("admin_list", ["2757808353"])
            for admin_id in admin_list:
                await self.send_private_message(admin_id, error_info)
            
            if private_send_id and private_send_id not in admin_list:
                await self.send_private_message(private_send_id, error_info)

        except Exception as e:
            logger.error(f"发送错误信息失败: {e}")
            logger.error(traceback.format_exc())

    async def handle_mute_event(self, event):
        """处理禁言事件"""
        try:
            group_id = None
            try:
                if hasattr(event, 'get_group_id'):
                    group_id = event.get_group_id()
                elif hasattr(event, 'message_obj') and hasattr(event.message_obj, 'group_id'):
                    group_id = event.message_obj.group_id
            except Exception as e:
                logger.error(f"获取群ID失败: {e}")
            
            if not group_id:
                logger.warning("无法获取群ID，禁言事件处理失败")
                return

            self.muted_groups.add(group_id)
            logger.info(f"群 {group_id} 已被禁言，开始屏蔽消息")

            config = self.get_realtime_config()
            admin_list = config.get("admin_list", ["2757808353"])
            
            for admin_id in admin_list:
                thinking_prompt = f"我在群 {group_id} 中被禁言了，需要向管理员汇报这件事。请生成一个礼貌的汇报消息。"
                thinking = await self.call_llm(thinking_prompt, event)
                message = f"【被禁言通知】\n我在群 {group_id} 中被禁言了。\n\n【思考】\n{thinking}"
                await self.send_private_message(admin_id, message, event)

        except Exception as e:
            logger.error(f"处理禁言事件失败: {e}")
            logger.error(traceback.format_exc())
            await self.send_error_message(event, "handle_mute_event", str(e), traceback.format_exc())

    async def handle_report_request(self, event, report_content):
        """处理群员汇报请求"""
        try:
            user_id = None
            group_id = None
            try:
                if hasattr(event, 'get_sender_id'):
                    user_id = event.get_sender_id()
                if hasattr(event, 'get_group_id'):
                    group_id = event.get_group_id()
            except Exception as e:
                logger.error(f"获取用户ID或群ID失败: {e}")
            
            logger.info(f"处理群员汇报请求: 用户 {user_id}, 群 {group_id}, 内容: {report_content}")
            
            config = self.get_realtime_config()
            admin_list = config.get("admin_list", ["2757808353"])
            
            for admin_id in admin_list:
                thinking_prompt = f"群员要求我向管理员汇报：{report_content}。请生成一个合适的汇报消息。"
                thinking = await self.call_llm(thinking_prompt, event)
                message = f"【群员汇报】\n{report_content}\n\n【思考】\n{thinking}"
                await self.send_private_message(admin_id, message, event)

        except Exception as e:
            logger.error(f"处理群员汇报失败: {e}")
            logger.error(traceback.format_exc())
            await self.send_error_message(event, "handle_report_request", str(e), traceback.format_exc())

    async def handle_private_request(self, event, message_content):
        """处理私聊请求"""
        try:
            user_id = None
            group_id = None
            try:
                if hasattr(event, 'get_sender_id'):
                    user_id = event.get_sender_id()
                if hasattr(event, 'get_group_id'):
                    group_id = event.get_group_id()
            except Exception as e:
                logger.error(f"获取用户ID或群ID失败: {e}")
            
            logger.info(f"处理私聊请求: 用户 {user_id}, 内容: {message_content}")
            
            if group_id:
                prompt = f"用户在群里说：'你私聊我看看'，现在我需要通过私聊回复他。请生成一个友好、自然的私聊回复，不需要提及群聊的事情，就像我们在私聊中正常对话一样。"
                response = await self.call_llm(prompt, event)
                
                if not response:
                    response = "你好，有什么我可以帮助你的吗？"
                
                logger.info(f"向用户 {user_id} 发送私聊消息")
                success = await self.send_private_message(user_id, response, event)
                
                if success:
                    logger.info("私聊消息发送成功")

        except Exception as e:
            logger.error(f"处理私聊请求失败: {e}")
            logger.error(traceback.format_exc())
            await self.send_error_message(event, "handle_private_request", str(e), traceback.format_exc())

    async def handle_summary_request(self, event):
        """处理总结请求"""
        try:
            user_id = None
            group_id = None
            try:
                if hasattr(event, 'get_sender_id'):
                    user_id = event.get_sender_id()
                if hasattr(event, 'get_group_id'):
                    group_id = event.get_group_id()
            except Exception as e:
                logger.error(f"获取用户ID或群ID失败: {e}")
            
            logger.info(f"处理总结请求: 用户 {user_id}, 群 {group_id}")
            
            if not group_id:
                logger.warning("没有群ID，无法处理总结请求")
                return

            message_history = self.config.get("group_message_history", {}).get(group_id, [])
            logger.info(f"群消息历史数量: {len(message_history)}")
            if not message_history:
                logger.warning("没有群消息历史，无法处理总结请求")
                return

            thinking_prompt = f"请总结以下群消息：\n{message_history[-20:]}\n\n请提供一个简洁的总结。"
            thinking = await self.call_llm(thinking_prompt, event)
            
            summary_prompt = f"基于以下思考，生成群消息总结：\n{thinking}"
            summary = await self.call_llm(summary_prompt, event)
            
            message = f"【群消息总结】\n{summary}\n\n【思考】\n{thinking}"
            logger.info(f"向用户 {user_id} 发送群消息总结")
            await self.send_private_message(user_id, message, event)

        except Exception as e:
            logger.error(f"处理总结请求失败: {e}")
            logger.error(traceback.format_exc())
            await self.send_error_message(event, "handle_summary_request", str(e), traceback.format_exc())

    @event_message_type(EventMessageType.ALL)
    async def on_all_messages(self, *args, **kwargs):
        """处理所有消息"""
        try:
            event = None
            if args:
                event = args[0]
            
            if not event:
                logger.warning("没有事件对象，忽略消息")
                return
            
            user_id = None
            try:
                if hasattr(event, 'get_sender_id'):
                    user_id = event.get_sender_id()
            except Exception as e:
                logger.error(f"获取用户ID失败: {e}")
                return
            
            message_str = ""
            try:
                if hasattr(event, 'message_str'):
                    message_str = event.message_str
                else:
                    message_str = str(event)
            except Exception as e:
                logger.error(f"获取消息内容失败: {e}")
                return
            
            group_id = None
            try:
                if hasattr(event, 'get_group_id'):
                    group_id = event.get_group_id()
            except Exception as e:
                logger.error(f"获取群ID失败: {e}")
            
            logger.info(f"收到消息: 用户 {user_id}, 内容: {message_str}, 群: {group_id}")

            if group_id and group_id in self.muted_groups:
                logger.info(f"群 {group_id} 已被禁言，忽略消息")
                return
            
            wake_words = ["幽幽", "洛幽幽"]
            contains_wake_word = any(wake_word in message_str for wake_word in wake_words)
            
            if group_id and not contains_wake_word:
                logger.debug(f"消息不包含唤醒词，忽略")
                return

            config = self.get_realtime_config()
            report_keywords = config.get("report_keywords", ["告诉你创造者", "告诉开发者"])
            for keyword in report_keywords:
                if keyword in message_str:
                    report_content = message_str.split(keyword)[-1].strip()
                    logger.info(f"触发群员汇报关键词: {keyword}, 内容: {report_content}")
                    await self.handle_report_request(event, report_content)
                    return
            
            if not self.is_admin(user_id):
                logger.info(f"用户 {user_id} 不是管理员，忽略消息")
                return
            else:
                logger.info(f"用户 {user_id} 是管理员，继续处理消息")

            if "禁言" in message_str:
                await self.handle_mute_event(event)
                return

            private_keywords = config.get("private_keywords", ["私聊", "私信", "私发", "发给我"])
            logger.info(f"检查私聊关键词: {private_keywords}")
            for keyword in private_keywords:
                if keyword in message_str:
                    logger.info(f"触发私聊关键词: {keyword}")
                    message_content = "测试私聊功能"
                    try:
                        content_match = re.search(r'["\'\`](.+?)["\'\`]', message_str)
                        if content_match:
                            message_content = content_match.group(1)
                            logger.info(f"从引号中提取私聊内容: {message_content}")
                        else:
                            parts = message_str.split(keyword)
                            if len(parts) > 1:
                                message_content = parts[1].strip()
                                logger.info(f"从关键词后提取私聊内容: {message_content}")
                    except Exception as e:
                        logger.error(f"提取私聊内容失败: {e}")
                    
                    logger.info(f"最终私聊内容: {message_content}")
                    await self.handle_private_request(event, message_content)
                    return

            summary_keywords = config.get("summary_keywords", ["总结", "汇总", "总结一下"])
            for keyword in summary_keywords:
                if keyword in message_str:
                    logger.info(f"触发总结关键词: {keyword}")
                    await self.handle_summary_request(event)
                    return

        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            logger.error(traceback.format_exc())
            await self.send_error_message(event, "on_all_messages", str(e), traceback.format_exc())

    async def terminate(self):
        """插件卸载"""
        logger.info("自动私聊插件已卸载")
