from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.event.filter import event_message_type, EventMessageType
from astrbot.api import logger
from astrbot.api.message_components import Plain
from astrbot.api.event import MessageChain
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
import json
import os
import re
import traceback

@register("astrbot_plugin_zhudongshiliao", "引灯续昼", "自动私聊插件，当大模型识别到需要时触发私聊功能。支持告状功能和自定义报错处理。", "0.0.1")
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
                
                # 只处理插件相关的配置
                plugin_config_keys = [
                    "admin_list", "enable_private_chat", "enable_report", 
                    "enable_sue", "sue_keywords", "error_format"
                ]
                
                for key in plugin_config_keys:
                    if key in webui_config:
                        self.config[key] = webui_config[key]
                
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
            webui_config = self.context.get_config()
            if webui_config:
                # 只处理插件相关的配置
                plugin_config_keys = [
                    "admin_list", "enable_private_chat", "enable_report", 
                    "enable_sue", "sue_keywords", "error_format"
                ]
                
                plugin_specific_config = {}
                for key in plugin_config_keys:
                    if key in webui_config:
                        plugin_specific_config[key] = webui_config[key]
                
                if plugin_specific_config:
                    merged_config = self.config.copy()
                    for key, value in plugin_specific_config.items():
                        merged_config[key] = value
                    return merged_config
            
            return self.config
        except Exception as e:
            logger.error(f"获取实时配置失败: {e}")
            return self.config
    
    def _load_config(self):
        """加载配置文件"""
        default_config = {
            "admin_list": ["2757808353"],
            "enable_private_chat": True,
            "enable_report": True,
            "enable_sue": True,
            "sue_keywords": ["辱骂", "欺负", "骂", "侮辱", "攻击"],
            "error_format": "【错误信息】\n方法: {method}\n错误: {error}"
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
                if hasattr(llm_resp, 'content'):
                    response = llm_resp.content
                    logger.info(f"通过content属性获取大模型回复，长度: {len(response)}")
                    return response
                elif hasattr(llm_resp, 'text'):
                    response = llm_resp.text
                    logger.info(f"通过text属性获取大模型回复，长度: {len(response)}")
                    return response
                elif hasattr(llm_resp, 'result_chain'):
                    result_chain = llm_resp.result_chain
                    if hasattr(result_chain, 'chain'):
                        for item in result_chain.chain:
                            if hasattr(item, 'text'):
                                response = item.text
                                logger.info(f"从Plain对象获取回复内容，长度: {len(response)}")
                                return response
                elif isinstance(llm_resp, str):
                    logger.info(f"大模型直接返回字符串，长度: {len(llm_resp)}")
                    return llm_resp
                else:
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
    
    async def handle_sue_request(self, event, user_id, message_content):
        """处理告状请求"""
        try:
            config = self.get_realtime_config()
            admin_list = config.get("admin_list", ["2757808353"])
            
            logger.info(f"处理告状请求: 用户 {user_id}, 内容: {message_content}")
            
            for admin_id in admin_list:
                prompt = f"用户说：'{message_content}'，看起来像是在辱骂或欺负我。请生成一个告状消息，向管理员汇报这件事，语气要委屈但不要过激。"
                sue_message = await self.call_llm(prompt, event)
                
                if not sue_message:
                    sue_message = f"管理员，有人在欺负我！\n\n用户说：{message_content}"
                
                await self.send_private_message(admin_id, sue_message, event)

        except Exception as e:
            logger.error(f"处理告状请求失败: {e}")
            logger.error(traceback.format_exc())
            await self.send_error_message(event, "handle_sue_request", str(e), traceback.format_exc())
    
    async def analyze_intent(self, message_content, event):
        """让大模型分析消息意图"""
        prompt = f"请分析以下消息的意图，判断是否包含以下任何一种情况：\n1. 需要私聊（用户明确要求私聊、私信等）\n2. 需要告状（用户在辱骂、欺负或攻击bot）\n3. 普通对话（不需要特殊处理）\n\n消息内容：{message_content}\n\n请只返回数字：1=需要私聊，2=需要告状，3=普通对话"
        
        result = await self.call_llm(prompt, event)
        logger.info(f"大模型意图分析结果: {result}")
        
        try:
            intent = int(result.strip())
            if intent in [1, 2, 3]:
                return intent
        except:
            pass
        
        return 3  # 默认普通对话
    
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
                
                if user_id is None:
                    logger.warning("获取到的用户ID为None")
                    logger.warning(f"事件对象类型: {type(event)}")
                    logger.warning(f"事件对象属性: {dir(event)}")
                    
                    try:
                        event_str = str(event)
                        logger.warning(f"事件对象字符串: {event_str}")
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
            
            # 让大模型分析消息意图
            intent = await self.analyze_intent(message_str, event)
            logger.info(f"消息意图分析结果: {intent}")
            
            # 根据意图处理消息
            if intent == 1:  # 需要私聊
                enable_private_chat = config.get("enable_private_chat", True)
                if enable_private_chat:
                    # 生成私聊回复
                    prompt = f"用户要求私聊，现在你需要在私聊中回复他。\n\n用户说：'{message_str}'\n\n请生成一个友好、自然的私聊回复，符合你作为AI助手的性格。"
                    response = await self.call_llm(prompt, event)
                    
                    if response:
                        logger.info(f"向用户 {user_id} 发送私聊消息")
                        success = await self.send_private_message(user_id, response, event)
                        if success:
                            logger.info("私聊消息发送成功")
                            return MessageEventResult().stop_event()  # 阻止事件继续传播
                    else:
                        logger.warning("大模型未返回私聊内容")
            
            elif intent == 2:  # 需要告状
                enable_sue = config.get("enable_sue", True)
                if enable_sue:
                    await self.handle_sue_request(event, user_id, message_str)
                    return MessageEventResult().stop_event()  # 阻止事件继续传播
            
            # 普通对话，不做特殊处理
            logger.debug("普通对话，不做特殊处理")
            return

        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            logger.error(traceback.format_exc())
            # 发送自定义错误消息
            await self.send_error_message(event, "on_all_messages", str(e), traceback.format_exc())
            # 截断错误向上冒泡
            return MessageEventResult().stop_event()
    
    async def terminate(self):
        """插件卸载"""
        logger.info("自动私聊插件已卸载")
