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
        # 确保配置文件存在
        if not os.path.exists(self.config_file):
            logger.info("配置文件不存在，创建默认配置")
            self.config = self._load_config()
        else:
            logger.info("配置文件存在，加载配置")
            self.config = self._load_config()
        
        await self._load_webui_config()
        logger.info("自动私聊插件初始化完成")
        logger.info(f"管理员列表: {self.config.get('admin_list', [])}")
        logger.info(f"私聊关键词: {self.config.get('private_keywords', [])}")
        logger.info(f"总结关键词: {self.config.get('summary_keywords', [])}")
        logger.info(f"汇报关键词: {self.config.get('report_keywords', [])}")

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
                # 确保webui_config中有admin_list
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
        # 确保用户ID是字符串类型
        user_id_str = str(user_id)
        # 确保admin_list中的元素都是字符串类型
        admin_list_str = [str(admin) for admin in admin_list]
        logger.info(f"检查用户 {user_id_str} 是否为管理员，管理员列表: {admin_list_str}")
        is_admin_result = user_id_str in admin_list_str
        logger.info(f"用户 {user_id_str} 是管理员: {is_admin_result}")
        return is_admin_result

    async def call_llm(self, prompt, event=None):
        """调用大模型"""
        try:
            # 使用当前会话的模型
            if event:
                # 构建LLM请求（移除temperature参数）
                request = ProviderRequest(
                    prompt=prompt,
                    model=""  # 使用默认模型
                )
                # 发送LLM请求
                response = await self.context.llm_request(request)
                logger.info(f"大模型调用成功，响应长度: {len(response.content) if response else 0}")
                return response.content if response else ""
            else:
                # 即使没有event，也尝试使用默认方式调用大模型
                try:
                    request = ProviderRequest(
                        prompt=prompt,
                        model=""  # 使用默认模型
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
            # 检查是否是禁言错误
            error_str = str(e)
            if "禁言" in error_str or "120" in error_str or "EventChecker Failed" in error_str:
                logger.warning(f"检测到禁言错误: {e}")
                if event:
                    await self.handle_mute_event(event)
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
                # 确保event对象有plain_result方法
                try:
                    return event.plain_result(error_info)
                except AttributeError:
                    logger.error(f"event对象没有plain_result方法")
                    # 尝试直接发送错误信息到群里
                    if hasattr(event, 'get_group_id') and event.get_group_id():
                        await self.send_private_message(event.get_sender_id(), error_info)
                    return None

        except Exception as e:
            logger.error(f"发送错误信息失败: {e}")
            logger.error(traceback.format_exc())
            return None

    async def handle_mute_event(self, event: AstrMessageEvent):
        """处理禁言事件"""
        try:
            group_id = event.get_group_id()
            if not group_id:
                # 尝试从事件中获取更多信息
                try:
                    # 检查事件的其他属性
                    if hasattr(event, 'message_obj') and hasattr(event.message_obj, 'group_id'):
                        group_id = event.message_obj.group_id
                except Exception as e:
                    logger.debug(f"获取群ID失败: {e}")
                if not group_id:
                    logger.warning("无法获取群ID，禁言事件处理失败")
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
                # 使用直接的消息发送方式，避免递归调用
                try:
                    platform_id = "qq"
                    if event:
                        platform_id = event.get_platform_id()

                    session = MessageSession(
                        platform_name=platform_id,
                        message_type=MessageType.FRIEND_MESSAGE,
                        session_id=str(admin_id)
                    )

                    message_chain = MessageChain().message(message)
                    success = await self.context.send_message(session, message_chain)
                    if success:
                        logger.info(f"成功向管理员 {admin_id} 发送禁言通知")
                    else:
                        logger.warning(f"向管理员 {admin_id} 发送禁言通知失败")
                except Exception as e:
                    logger.error(f"发送禁言通知失败: {e}")

        except Exception as e:
            logger.error(f"处理禁言事件失败: {e}")
            logger.error(traceback.format_exc())

    async def handle_report_request(self, event: AstrMessageEvent, report_content):
        """处理群员汇报请求"""
        try:
            user_id = event.get_sender_id()
            group_id = event.get_group_id()
            logger.info(f"处理群员汇报请求: 用户 {user_id}, 群 {group_id}, 内容: {report_content}")
            
            config = self.get_realtime_config()
            admin_list = config.get("admin_list", [])
            logger.info(f"向管理员列表发送汇报: {admin_list}")
            
            for admin_id in admin_list:
                # 生成思考内容
                thinking_prompt = f"群员要求我向管理员汇报：{report_content}。请生成一个合适的汇报消息。"
                thinking = await self.call_llm(thinking_prompt, event)
                logger.debug(f"生成思考内容: {thinking}")
                
                # 发送汇报信息
                message = f"【群员汇报】\n{report_content}\n\n【思考】\n{thinking}"
                logger.info(f"向管理员 {admin_id} 发送群员汇报")
                await self.send_private_message(admin_id, message, event)

        except Exception as e:
            logger.error(f"处理群员汇报失败: {e}")
            logger.error(traceback.format_exc())

    async def handle_private_request(self, event: AstrMessageEvent, message_content):
        """处理私聊请求"""
        try:
            user_id = event.get_sender_id()
            logger.info(f"处理私聊请求: 用户 {user_id}, 内容: {message_content}")
            
            # 检查是否在群聊中触发
            group_id = event.get_group_id()
            if group_id:
                # 生成智能回复内容
                prompt = f"用户在群里说：'你私聊我看看'，现在我需要通过私聊回复他。请生成一个友好、自然的私聊回复，不需要提及群聊的事情，就像我们在私聊中正常对话一样。"
                response = await self.call_llm(prompt, event)
                
                if not response:
                    response = "你好，有什么我可以帮助你的吗？"
                
                # 发送私聊消息
                logger.info(f"向用户 {user_id} 发送私聊消息")
                success = await self.send_private_message(user_id, response, event)
                
                if success:
                    # 不回复群消息，避免重复
                    logger.info("私聊消息发送成功，不回复群消息")
                    return event.plain_result("")
            else:
                # 私聊中触发，处理管理员回复
                await self.handle_private_forward(event)

        except Exception as e:
            logger.error(f"处理私聊请求失败: {e}")
            logger.error(traceback.format_exc())
            return event.plain_result("")

    async def handle_summary_request(self, event: AstrMessageEvent):
        """处理总结请求"""
        try:
            user_id = event.get_sender_id()
            group_id = event.get_group_id()
            logger.info(f"处理总结请求: 用户 {user_id}, 群 {group_id}")
            
            if not group_id:
                logger.warning("没有群ID，无法处理总结请求")
                return

            # 获取群消息历史
            message_history = self.config.get("group_message_history", {}).get(group_id, [])
            logger.info(f"群消息历史数量: {len(message_history)}")
            if not message_history:
                logger.warning("没有群消息历史，无法处理总结请求")
                return

            # 生成思考内容
            thinking_prompt = f"请总结以下群消息：\n{message_history[-20:]}\n\n请提供一个简洁的总结。"
            thinking = await self.call_llm(thinking_prompt, event)
            logger.debug(f"生成思考内容: {thinking}")
            
            # 生成总结
            summary_prompt = f"基于以下思考，生成群消息总结：\n{thinking}"
            summary = await self.call_llm(summary_prompt, event)
            logger.info(f"生成总结内容: {summary}")
            
            # 发送总结
            message = f"【群消息总结】\n{summary}\n\n【思考】\n{thinking}"
            logger.info(f"向用户 {user_id} 发送群消息总结")
            await self.send_private_message(user_id, message, event)

        except Exception as e:
            logger.error(f"处理总结请求失败: {e}")
            logger.error(traceback.format_exc())

    @event_message_type(EventMessageType.ALL)
    async def on_all_messages(self, event: AstrMessageEvent, *args, **kwargs):
        """处理所有消息"""
        try:
            # 尝试获取用户ID
            try:
                user_id = event.get_sender_id()
            except AttributeError as e:
                logger.error(f"获取用户ID失败: {e}")
                return
            
            # 尝试不同的方式获取消息内容
            try:
                message_str = event.message_str
            except AttributeError:
                message_str = str(event)
            
            # 尝试获取群ID
            try:
                group_id = event.get_group_id()
            except AttributeError:
                group_id = None
            
            logger.info(f"收到消息: 用户 {user_id}, 内容: {message_str}, 群: {group_id}")

            # 检查是否在被禁言的群中
            if group_id and group_id in self.muted_groups:
                logger.info(f"群 {group_id} 已被禁言，忽略消息")
                return
            
            # 检查是否包含唤醒词（如机器人名称）
            # 这里假设唤醒词是机器人的名称，如"幽幽"
            wake_words = ["幽幽", "洛幽幽"]
            contains_wake_word = any(wake_word in message_str for wake_word in wake_words)
            
            # 如果是群消息且不包含唤醒词，直接返回
            if group_id and not contains_wake_word:
                logger.debug(f"消息不包含唤醒词，忽略")
                return

            # 缓存用户信息
            if group_id:
                try:
                    sender_name = event.get_sender_name()
                    if sender_name:
                        self.user_cache[sender_name] = user_id
                        logger.info(f"缓存用户信息: {sender_name} -> {user_id}")
                except Exception as e:
                    logger.info(f"获取发送者名称失败: {e}")

            # 检查是否为管理员
            is_admin_result = self.is_admin(user_id)
            if not is_admin_result:
                # 即使不是管理员，也检查群员汇报关键词
                config = self.get_realtime_config()
                report_keywords = config.get("report_keywords", ["告诉你创造者", "告诉开发者"])
                logger.info(f"用户 {user_id} 不是管理员，检查群员汇报关键词: {report_keywords}")
                for keyword in report_keywords:
                    if keyword in message_str:
                        report_content = message_str.split(keyword)[-1].strip()
                        logger.info(f"触发群员汇报关键词: {keyword}, 内容: {report_content}")
                        await self.handle_report_request(event, report_content)
                        return
                logger.info(f"用户 {user_id} 不是管理员，忽略消息")
                return
            else:
                logger.info(f"用户 {user_id} 是管理员，继续处理消息")

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
            logger.info(f"检查私聊关键词: {private_keywords}")
            for keyword in private_keywords:
                if keyword in message_str:
                    logger.info(f"触发私聊关键词: {keyword}")
                    # 提取消息内容
                    content_match = re.search(r'["\'\`](.+?)["\'\`]', message_str)
                    if content_match:
                        message_content = content_match.group(1)
                        logger.info(f"从引号中提取私聊内容: {message_content}")
                    else:
                        # 尝试提取关键词后的内容
                        parts = message_str.split(keyword)
                        if len(parts) > 1:
                            message_content = parts[1].strip()
                            logger.info(f"从关键词后提取私聊内容: {message_content}")
                        else:
                            message_content = "测试私聊功能"
                            logger.info(f"使用默认私聊内容: {message_content}")
                    
                    logger.info(f"最终私聊内容: {message_content}")
                    result = await self.handle_private_request(event, message_content)
                    if result:
                        yield result
                    return

            # 检查是否触发总结关键词
            summary_keywords = config.get("summary_keywords", ["总结", "汇总", "总结一下"])
            for keyword in summary_keywords:
                if keyword in message_str:
                    logger.info(f"触发总结关键词: {keyword}")
                    await self.handle_summary_request(event)
                    return

        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            logger.error(traceback.format_exc())
            # 发送错误信息，但不返回结果，避免在群里重复回复
            await self.send_error_message(event, "on_all_messages", str(e), traceback.format_exc())
            # 直接返回，不yield结果，避免在群里显示错误信息
            return

    async def handle_private_forward(self, event: AstrMessageEvent):
        """处理私聊消息转接"""
        try:
            user_id = event.get_sender_id()
            # 尝试不同的方式获取消息内容
            try:
                message_str = event.message_str
            except AttributeError:
                message_str = str(event)
            
            logger.info(f"收到私聊消息: 用户 {user_id}, 内容: {message_str}")
            
            # 检查是否是管理员回复
            if self.is_admin(user_id):
                # 检查是否是回复转接消息
                # 这里需要一个机制来识别管理员回复的是哪个用户的消息
                # 暂时简单处理，检查消息中是否包含用户ID
                import re
                user_id_match = re.search(r'用户ID:(\d+)', message_str)
                if user_id_match:
                    target_user_id = user_id_match.group(1)
                    # 提取回复内容
                    reply_content = re.sub(r'用户ID:\d+', '', message_str).strip()
                    if reply_content:
                        logger.info(f"管理员 {user_id} 回复用户 {target_user_id}: {reply_content}")
                        # 发送回复给目标用户
                        await self.send_private_message(target_user_id, reply_content)
                        return event.plain_result(f"已将回复发送给用户 {target_user_id}")
            else:
                # 非管理员私聊消息，转接到管理员
                config = self.get_realtime_config()
                admin_list = config.get("admin_list", [])
                
                for admin_id in admin_list:
                    logger.info(f"将用户 {user_id} 的私聊消息转接到管理员 {admin_id}")
                    # 生成思考内容
                    thinking_prompt = f"用户 {user_id} 发送了一条私聊消息，需要转接给管理员。请生成一个转接提示。"
                    thinking = await self.call_llm(thinking_prompt, event)
                    
                    # 发送转接消息给管理员
                    forward_message = f"【私聊转接】\n用户ID: {user_id}\n消息内容: {message_str}\n\n【思考】\n{thinking}\n\n回复格式: 直接回复内容即可，系统会自动转发给用户"
                    await self.send_private_message(admin_id, forward_message, event)
                
                # 回复用户
                user_reply_prompt = f"用户发送了私聊消息，我已将消息转接到管理员。请生成一个友好的回复。"
                user_reply = await self.call_llm(user_reply_prompt, event)
                if not user_reply:
                    user_reply = "您好，您的消息已转接到管理员，我们会尽快回复您。"
                return event.plain_result(user_reply)
            
        except Exception as e:
            logger.error(f"处理私聊转接失败: {e}")
            logger.error(traceback.format_exc())
            return event.plain_result("处理私聊消息时发生错误，请稍后再试。")

    @event_message_type(EventMessageType.PRIVATE_MESSAGE)
    async def on_private_message(self, event: AstrMessageEvent, *args, **kwargs):
        """处理私聊消息"""
        return await self.handle_private_forward(event)

    async def terminate(self):
        """插件卸载"""
        logger.info("自动私聊插件已卸载")