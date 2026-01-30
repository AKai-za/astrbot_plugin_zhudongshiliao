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

@register("astrbot_plugin_zhudongshiliao", "引灯续昼", "自动私聊插件，当用户发送消息时，自动私聊用户。支持群消息总结、错误信息转发等功能。", "v1.4.38")
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
                logger.debug("从WebUI加载配置成功")
                
                # 确保admin_list存在且不为空
                if "admin_list" not in webui_config:
                    webui_config["admin_list"] = self.config.get("admin_list", ["2757808353"])
                
                # 同步所有配置项
                for key, value in webui_config.items():
                    if key != "group_message_history":
                        self.config[key] = value
                
                # 保存配置
                self._save_config(self.config)
                logger.debug("配置同步完成")
            else:
                logger.warning("WebUI配置为空")
        except Exception as e:
            logger.error(f"从WebUI加载配置失败: {e}")
            logger.error(traceback.format_exc())

    def get_realtime_config(self):
        """获取实时配置"""
        try:
            # 只获取插件相关的配置，避免加载整个AstrBot配置
            webui_config = self.context.get_config()
            if webui_config:
                # 插件相关的配置键列表
                plugin_config_keys = [
                    "admin_list", "private_keywords", "mention_patterns", 
                    "summary_keywords", "report_keywords", "error_format", 
                    "private_send_id", "enable_wake_word", "wake_words", 
                    "enable_private_chat", "enable_summary", "enable_report"
                ]
                
                # 只处理插件相关的配置
                plugin_specific_config = {}
                for key in plugin_config_keys:
                    if key in webui_config:
                        plugin_specific_config[key] = webui_config[key]
                
                if plugin_specific_config:
                    logger.debug(f"获取到插件相关配置: {list(plugin_specific_config.keys())}")
                    
                    # 确保admin_list存在且不为空
                    if "admin_list" not in plugin_specific_config:
                        plugin_specific_config["admin_list"] = self.config.get("admin_list", ["2757808353"])
                    elif not plugin_specific_config["admin_list"]:
                        plugin_specific_config["admin_list"] = ["2757808353"]
                    
                    # 合并配置
                    merged_config = self.config.copy()
                    for key, value in plugin_specific_config.items():
                        if key != "group_message_history":
                            merged_config[key] = value
                    
                    logger.debug("插件配置合并完成")
                    return merged_config
            
            logger.debug("使用本地配置")
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
            logger.info(f"创建默认配置: {default_config}")
            return default_config

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            for key, value in default_config.items():
                if key not in config:
                    config[key] = value
            self._save_config(config)
            logger.info(f"加载配置文件: {config}")
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
            logger.info(f"保存配置文件: {config}")
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
            # 获取当前使用的聊天模型 Provider
            umo = event.unified_msg_origin if event and hasattr(event, 'unified_msg_origin') else None
            provider = self.context.get_using_provider(umo)
            
            if not provider:
                logger.warning("未找到可用的聊天模型 Provider")
                return ""
            
            logger.info(f"使用聊天模型 Provider: {provider.meta().id}")
            logger.info(f"大模型调用提示词: {prompt[:100]}...")
            
            # 调用大模型生成回复
            llm_resp = await provider.text_chat(prompt=prompt)
            logger.info(f"大模型调用返回对象类型: {type(llm_resp)}")
            
            # 尝试多种方式获取回复内容
            if llm_resp:
                # 检查LLMResponse对象的属性
                if hasattr(llm_resp, 'content'):
                    response = llm_resp.content
                    logger.info(f"通过content属性获取大模型回复，长度: {len(response)}")
                    return response
                elif hasattr(llm_resp, 'text'):
                    response = llm_resp.text
                    logger.info(f"通过text属性获取大模型回复，长度: {len(response)}")
                    return response
                elif hasattr(llm_resp, 'result_chain'):
                    # 从result_chain中提取Plain文本
                    result_chain = llm_resp.result_chain
                    logger.info(f"通过result_chain获取大模型回复")
                    if hasattr(result_chain, 'chain'):
                        for item in result_chain.chain:
                            if hasattr(item, 'text'):
                                response = item.text
                                logger.info(f"从Plain对象获取回复内容，长度: {len(response)}")
                                # 尝试从多个选项中提取一个
                                if '或者' in response or '**' in response:
                                    # 提取第一个回复选项
                                    import re
                                    matches = re.findall(r'["“]([^"]*)["”]', response)
                                    if matches:
                                        response = matches[0]
                                        logger.info(f"从多个选项中提取第一个回复: {response}")
                                    else:
                                        # 尝试其他方式提取
                                        lines = response.split('\n')
                                        for line in lines:
                                            line = line.strip()
                                            if line and not line.startswith('**') and not line.startswith('好的'):
                                                response = line
                                                logger.info(f"从多行文本中提取回复: {response}")
                                                break
                                return response
                elif isinstance(llm_resp, str):
                    logger.info(f"大模型直接返回字符串，长度: {len(llm_resp)}")
                    return llm_resp
                else:
                    logger.info(f"大模型返回未知类型: {llm_resp}")
                    # 尝试将对象转换为字符串
                    try:
                        response = str(llm_resp)
                        logger.info(f"转换为字符串后长度: {len(response)}")
                        return response
                    except:
                        pass
            
            logger.warning("大模型未返回有效内容")
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

            user_id_str = str(user_id)
            logger.info(f"准备发送私聊消息到 {user_id_str}")

            # 尝试使用event对象发送消息
            if event and hasattr(event, 'reply'):
                try:
                    logger.info("尝试使用event.reply发送私聊消息")
                    await event.reply(message, private=True)
                    logger.info(f"成功使用event.reply发送私聊消息到 {user_id_str}")
                    return True
                except Exception as e:
                    logger.warning(f"使用event.reply发送私聊消息失败: {e}")
            
            # 尝试使用context的send_private_message方法
            if hasattr(self.context, 'send_private_message'):
                try:
                    logger.info("尝试使用context.send_private_message发送私聊消息")
                    success = await self.context.send_private_message(user_id_str, message)
                    if success:
                        logger.info(f"成功使用context.send_private_message发送私聊消息到 {user_id_str}")
                        return True
                    else:
                        logger.warning(f"使用context.send_private_message发送私聊消息失败")
                except Exception as e:
                    logger.warning(f"使用context.send_private_message发送私聊消息失败: {e}")
            
            # 尝试使用MessageSession发送消息
            try:
                platform_id = "qq"
                if event and hasattr(event, 'get_platform_id'):
                    platform_id = event.get_platform_id()

                session = MessageSession(
                    platform_name=platform_id,
                    message_type=MessageType.FRIEND_MESSAGE,
                    session_id=user_id_str
                )

                message_chain = MessageChain().message(message)
                success = await self.context.send_message(session, message_chain)

                if success:
                    logger.info(f"成功发送私聊消息到 {user_id_str}")
                    return True
                else:
                    logger.warning(f"发送私聊消息到 {user_id_str} 失败")
                    return False
            except Exception as e:
                logger.warning(f"使用MessageSession发送私聊消息失败: {e}")
                
            # 所有方法都失败
            logger.error(f"所有发送私聊消息的方法都失败")
            return False

        except Exception as e:
            logger.error(f"发送私聊消息失败: {e}")
            logger.error(traceback.format_exc())
            error_str = str(e)
            if "禁言" in error_str or "120" in error_str or "EventChecker Failed" in error_str or "1200" in error_str:
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

            # 添加详细的错误信息
            detailed_error = f"{error_info}\n\n【详细错误】\n{traceback_str}"

            admin_list = config.get("admin_list", ["2757808353"])
            logger.info(f"向管理员列表发送错误信息: {admin_list}")
            
            for admin_id in admin_list:
                logger.info(f"向管理员 {admin_id} 发送错误信息")
                await self.send_private_message(admin_id, detailed_error, event)
            
            if private_send_id and private_send_id not in admin_list:
                logger.info(f"向私发ID {private_send_id} 发送错误信息")
                await self.send_private_message(private_send_id, detailed_error, event)

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
                prompt = f"用户在群里说：'{message_content}'，现在我需要通过私聊回复他。请生成一个友好、自然的私聊回复，不需要提及群聊的事情，就像我们在私聊中正常对话一样。"
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
            # 从参数中获取事件对象
            event = None
            for arg in args:
                if arg and not isinstance(arg, MyPlugin):
                    event = arg
                    break
            
            # 确保event是有效的消息事件对象
            if not event:
                logger.error("事件对象为None或无效")
                logger.error(f"接收到的参数: {args}, {kwargs}")
                return
            
            # 尝试获取用户ID
            user_id = None
            try:
                # 尝试多种获取用户ID的方法
                if hasattr(event, 'get_sender_id'):
                    try:
                        user_id = event.get_sender_id()
                        logger.debug(f"通过get_sender_id获取用户ID: {user_id}")
                    except Exception as e:
                        logger.debug(f"get_sender_id失败: {e}")
                
                if user_id is None and hasattr(event, 'sender_id'):
                    user_id = event.sender_id
                    logger.debug(f"通过sender_id获取用户ID: {user_id}")
                
                if user_id is None and hasattr(event, 'user_id'):
                    user_id = event.user_id
                    logger.debug(f"通过user_id获取用户ID: {user_id}")
                
                if user_id is None and hasattr(event, 'user') and hasattr(event.user, 'id'):
                    user_id = event.user.id
                    logger.debug(f"通过user.id获取用户ID: {user_id}")
                
                if user_id is None and hasattr(event, 'message_obj'):
                    try:
                        if hasattr(event.message_obj, 'user_id'):
                            user_id = event.message_obj.user_id
                            logger.debug(f"通过message_obj.user_id获取用户ID: {user_id}")
                        elif hasattr(event.message_obj, 'sender'):
                            user_id = event.message_obj.sender
                            logger.debug(f"通过message_obj.sender获取用户ID: {user_id}")
                    except Exception as e:
                        logger.debug(f"从message_obj获取用户ID失败: {e}")
                
                # 特殊处理：从事件对象的属性中直接查找ID相关属性
                if user_id is None:
                    # 遍历事件对象的所有属性，查找可能的ID
                    for attr_name in dir(event):
                        if 'id' in attr_name.lower() or 'user' in attr_name.lower():
                            try:
                                attr_value = getattr(event, attr_name)
                                if attr_value and isinstance(attr_value, (str, int)):
                                    user_id = attr_value
                                    logger.debug(f"通过{attr_name}获取用户ID: {user_id}")
                                    break
                            except Exception as e:
                                pass
                
                if user_id is None:
                    logger.warning("获取到的用户ID为None")
                    logger.warning(f"事件对象类型: {type(event)}")
                    logger.warning(f"事件对象属性: {dir(event)}")
                    
                    # 尝试获取事件对象的字符串表示，可能包含用户信息
                    try:
                        event_str = str(event)
                        logger.warning(f"事件对象字符串: {event_str}")
                        
                        # 尝试从字符串中提取数字ID
                        import re
                        ids = re.findall(r'\d{5,}', event_str)
                        if ids:
                            user_id = ids[0]
                            logger.warning(f"从事件字符串中提取到用户ID: {user_id}")
                    except Exception as e:
                        logger.warning(f"获取事件字符串失败: {e}")
                
                if user_id is None:
                    logger.warning("仍然无法获取用户ID，返回")
                    return
                else:
                    logger.info(f"成功获取用户ID: {user_id}")
            except Exception as e:
                logger.error(f"获取用户ID失败: {e}")
                logger.error(traceback.format_exc())
                return
            
            # 尝试获取消息内容
            message_str = ""
            try:
                if hasattr(event, 'message_str'):
                    message_str = event.message_str
                    logger.debug(f"通过message_str获取消息内容: {message_str}")
                elif hasattr(event, 'message'):
                    message_str = str(event.message)
                    logger.debug(f"通过message获取消息内容: {message_str}")
                elif hasattr(event, 'content'):
                    message_str = str(event.content)
                    logger.debug(f"通过content获取消息内容: {message_str}")
                elif hasattr(event, 'raw_message'):
                    message_str = str(event.raw_message)
                    logger.debug(f"通过raw_message获取消息内容: {message_str}")
                elif hasattr(event, 'message_obj') and hasattr(event.message_obj, 'content'):
                    message_str = str(event.message_obj.content)
                    logger.debug(f"通过message_obj.content获取消息内容: {message_str}")
                
                if not message_str:
                    logger.warning("获取到的消息内容为空")
                    return
                else:
                    logger.info(f"成功获取消息内容: '{message_str}'")
            except Exception as e:
                logger.error(f"获取消息内容失败: {e}")
                logger.error(traceback.format_exc())
                return
            
            # 尝试获取群ID
            group_id = None
            try:
                if hasattr(event, 'get_group_id'):
                    try:
                        group_id = event.get_group_id()
                        logger.debug(f"通过get_group_id获取群ID: {group_id}")
                    except Exception as e:
                        logger.debug(f"get_group_id失败: {e}")
                
                if group_id is None and hasattr(event, 'group_id'):
                    group_id = event.group_id
                    logger.debug(f"通过group_id获取群ID: {group_id}")
                
                if group_id is None and hasattr(event, 'group') and hasattr(event.group, 'id'):
                    group_id = event.group.id
                    logger.debug(f"通过group.id获取群ID: {group_id}")
                
                if group_id is None and hasattr(event, 'message_obj'):
                    try:
                        if hasattr(event.message_obj, 'group_id'):
                            group_id = event.message_obj.group_id
                            logger.debug(f"通过message_obj.group_id获取群ID: {group_id}")
                    except Exception as e:
                        logger.debug(f"从message_obj获取群ID失败: {e}")
                
                logger.info(f"成功获取群ID: {group_id}")
            except Exception as e:
                logger.error(f"获取群ID失败: {e}")
                logger.error(traceback.format_exc())
            
            logger.info(f"收到消息: 用户 {user_id}, 内容: '{message_str}', 群: {group_id}")

            # 检查是否在被禁言的群中
            if group_id and group_id in self.muted_groups:
                logger.info(f"群 {group_id} 已被禁言，忽略消息")
                return

            # 获取实时配置
            config = self.get_realtime_config()
            
            # 从配置中读取唤醒词设置
            enable_wake_word = config.get("enable_wake_word", True)
            wake_words = config.get("wake_words", ["幽幽", "洛幽幽"])
            
            # 检查是否包含唤醒词
            contains_wake_word = any(wake_word in message_str for wake_word in wake_words)
            
            # 检查是否需要唤醒词
            if enable_wake_word and group_id and not contains_wake_word:
                logger.debug(f"消息不包含唤醒词，忽略")
                return

            # 检查是否启用汇报功能
            enable_report = config.get("enable_report", True)
            
            if enable_report:
                # 检查是否触发群员汇报（非管理员也可触发）
                report_keywords = config.get("report_keywords", ["告诉你创造者", "告诉开发者"])
                for keyword in report_keywords:
                    if keyword in message_str:
                        report_content = message_str.split(keyword)[-1].strip()
                        logger.info(f"触发群员汇报关键词: {keyword}, 内容: {report_content}")
                        await self.handle_report_request(event, report_content)
                        return MessageEventResult().stop_event()
            
            # 只有管理员可以触发其他功能
            if not self.is_admin(user_id):
                logger.info(f"用户 {user_id} 不是管理员，忽略消息")
                return
            else:
                logger.info(f"用户 {user_id} 是管理员，继续处理消息")

            # 检查是否触发禁言事件
            if "禁言" in message_str:
                await self.handle_mute_event(event)
                return MessageEventResult().stop_event()

            # 检查是否启用私聊功能
            enable_private_chat = config.get("enable_private_chat", True)
            
            if enable_private_chat:
                # 检查是否触发私聊关键词
                private_keywords = config.get("private_keywords", ["私聊", "私信", "私发", "发给我"])
                logger.info(f"检查私聊关键词: {private_keywords}")
                logger.info(f"消息内容: '{message_str}'")
                
                # 检查是否包含任何私聊关键词
                has_private_keyword = any(keyword in message_str for keyword in private_keywords)
                
                # 从配置中读取提及私聊模式
                mention_patterns = config.get("mention_patterns", ["和我说话", "跟我私聊", "私信我", "私聊我", "和他说话", "跟他私聊", "私信他", "私聊他"])
                
                # 检查是否有人提到让AI与某人私聊
                mention_private_chat = False
                for pattern in mention_patterns:
                    if pattern in message_str:
                        mention_private_chat = True
                        break
                
                # 只有在关键词匹配或提及私聊时才触发
                if has_private_keyword or mention_private_chat:
                    trigger_type = ""
                    if has_private_keyword:
                        trigger_type = "关键词触发"
                    else:
                        trigger_type = "提及私聊触发"
                    
                    logger.info(f"触发私聊功能: {trigger_type}")
                    
                    # 生成智能回复内容（只在需要时调用大模型）
                    prompt = f"你是一个叫'幽幽'的AI助手，性格俏皮、活泼、有点小傲娇。用户刚刚在群里提到让你私聊他，现在你需要在私聊中直接回复他。\n\n用户说：'{message_str}'\n\n请你直接生成一个符合'幽幽'性格的私聊回复，要自然、口语化，就像真正的朋友聊天一样。注意：\n1. 只需要回复内容本身，不要有任何引言或开场白\n2. 不要包含任何建议性的语言或多个选项\n3. 保持语气一致，符合俏皮、活泼、有点小傲娇的性格\n4. 直接开始回复，不要有任何前缀或标记\n5. 回复要简洁，不要太长"
                    response = await self.call_llm(prompt, event)
                    
                    if response:
                        logger.info(f"使用大模型回复内容，长度: {len(response)}")
                    else:
                        logger.error("大模型未返回内容，不发送私聊消息")
                        return MessageEventResult().stop_event()
                    
                    # 发送私聊消息
                    logger.info(f"向用户 {user_id} 发送智能私聊消息")
                    logger.info(f"私聊消息内容长度: {len(response)}")
                    success = await self.send_private_message(user_id, response, event)
                    
                    if success:
                        logger.info("私聊消息发送成功")
                    else:
                        logger.warning("私聊消息发送失败")
                    return MessageEventResult().stop_event()

            # 检查是否启用总结功能
            enable_summary = config.get("enable_summary", True)
            
            if enable_summary:
                # 检查是否触发总结关键词
                summary_keywords = config.get("summary_keywords", ["总结", "汇总", "总结一下"])
                for keyword in summary_keywords:
                    if keyword in message_str:
                        logger.info(f"触发总结关键词: {keyword}")
                        await self.handle_summary_request(event)
                        return MessageEventResult().stop_event()

        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            logger.error(traceback.format_exc())
            await self.send_error_message(event, "on_all_messages", str(e), traceback.format_exc())

    async def terminate(self):
        """插件卸载"""
        logger.info("自动私聊插件已卸载")
