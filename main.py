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

@register("astrbot_plugin_zhudongshiliao", "引灯续昼", "自动私聊插件，当大模型识别到需要时触发私聊功能。支持告状功能和自定义报错处理。", "0.0.2")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config_file = os.path.join(os.path.dirname(__file__), "config.json")
        self.config = self._load_config()
        self.muted_groups = set()
    
    async def initialize(self):
        """插件初始化"""
        if not os.path.exists(self.config_file):
            logger.info("配置文件不存在，创建默认配置")
            self.config = self._load_config()
        else:
            self.config = self._load_config()
        
        await self._load_webui_config()
        logger.info("自动私聊插件初始化完成")
    
    async def _load_webui_config(self):
        """从WebUI加载配置"""
        try:
            webui_config = self.context.get_config()
            if webui_config:
                if "admin_list" not in webui_config:
                    webui_config["admin_list"] = self.config.get("admin_list", ["2757808353"])
                
                plugin_config_keys = ["admin_list", "enable_private_chat", "enable_sue", "error_format"]
                for key in plugin_config_keys:
                    if key in webui_config:
                        self.config[key] = webui_config[key]
                
                self._save_config(self.config)
        except Exception as e:
            logger.error(f"加载WebUI配置失败: {e}")
    
    def get_realtime_config(self):
        """获取实时配置"""
        try:
            webui_config = self.context.get_config()
            if webui_config:
                plugin_config_keys = ["admin_list", "enable_private_chat", "enable_sue", "error_format"]
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
            "enable_sue": True,
            "error_format": "【错误信息】\n方法: {method}\n错误: {error}"
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
        return user_id_str in admin_list_str
    
    async def call_llm(self, prompt, event=None):
        """调用大模型"""
        try:
            umo = event.unified_msg_origin if event and hasattr(event, 'unified_msg_origin') else None
            provider = self.context.get_using_provider(umo)
            
            if not provider:
                logger.warning("未找到可用的聊天模型 Provider")
                return ""
            
            llm_resp = await provider.text_chat(prompt=prompt)
            
            if llm_resp:
                if hasattr(llm_resp, 'content'):
                    return llm_resp.content
                elif hasattr(llm_resp, 'text'):
                    return llm_resp.text
                elif hasattr(llm_resp, 'result_chain') and hasattr(llm_resp.result_chain, 'chain'):
                    for item in llm_resp.result_chain.chain:
                        if hasattr(item, 'text'):
                            return item.text
                elif isinstance(llm_resp, str):
                    return llm_resp
                else:
                    try:
                        return str(llm_resp)
                    except:
                        pass
            
            return ""
        except Exception as e:
            logger.error(f"调用大模型失败: {e}")
            return ""
    
    async def send_private_message(self, user_id, message, event=None):
        """发送私聊消息"""
        try:
            user_id_str = str(user_id)

            # 尝试使用event对象发送消息
            if event and hasattr(event, 'reply'):
                try:
                    await event.reply(message, private=True)
                    return True
                except Exception:
                    pass
            
            # 尝试使用context的send_private_message方法
            if hasattr(self.context, 'send_private_message'):
                try:
                    success = await self.context.send_private_message(user_id_str, message)
                    if success:
                        return True
                except Exception:
                    pass
            
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
                return success
            except Exception:
                pass
            
            return False
        except Exception as e:
            logger.error(f"发送私聊消息失败: {e}")
            return False
    
    async def send_error_message(self, event, method, error, traceback_str):
        """发送错误信息"""
        try:
            config = self.get_realtime_config()
            error_format = config.get("error_format", "【错误信息】\n方法: {method}\n错误: {error}")

            error_info = error_format.format(method=method, error=error)
            detailed_error = f"{error_info}\n\n【详细错误】\n{traceback_str}"

            admin_list = config.get("admin_list", ["2757808353"])
            for admin_id in admin_list:
                await self.send_private_message(admin_id, detailed_error, event)

        except Exception as e:
            logger.error(f"发送错误信息失败: {e}")
    
    async def analyze_intent(self, message_content, event):
        """让大模型分析消息意图"""
        prompt = f"请分析以下消息的意图，判断是否包含以下任何一种情况：\n1. 需要私聊（用户明确要求私聊、私信等）\n2. 需要告状（用户在辱骂、欺负或攻击bot）\n3. 普通对话（不需要特殊处理）\n\n消息内容：{message_content}\n\n请只返回数字：1=需要私聊，2=需要告状，3=普通对话"
        
        result = await self.call_llm(prompt, event)
        
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
            # 获取事件对象
            event = None
            for arg in args:
                if arg and not isinstance(arg, MyPlugin):
                    event = arg
                    break
            
            if not event:
                return
            
            # 获取用户ID
            user_id = None
            try:
                if hasattr(event, 'get_sender_id'):
                    user_id = event.get_sender_id()
                elif hasattr(event, 'sender_id'):
                    user_id = event.sender_id
                elif hasattr(event, 'user_id'):
                    user_id = event.user_id
                elif hasattr(event, 'user') and hasattr(event.user, 'id'):
                    user_id = event.user.id
                elif hasattr(event, 'message_obj'):
                    if hasattr(event.message_obj, 'user_id'):
                        user_id = event.message_obj.user_id
                    elif hasattr(event.message_obj, 'sender'):
                        user_id = event.message_obj.sender
                
                if user_id is None:
                    return
            except Exception:
                return
            
            # 获取消息内容
            message_str = ""
            try:
                if hasattr(event, 'message_str'):
                    message_str = event.message_str
                elif hasattr(event, 'message'):
                    message_str = str(event.message)
                elif hasattr(event, 'content'):
                    message_str = str(event.content)
                elif hasattr(event, 'raw_message'):
                    message_str = str(event.raw_message)
                elif hasattr(event, 'message_obj') and hasattr(event.message_obj, 'content'):
                    message_str = str(event.message_obj.content)
                
                if not message_str:
                    return
            except Exception:
                return
            
            # 获取群ID
            group_id = None
            try:
                if hasattr(event, 'get_group_id'):
                    group_id = event.get_group_id()
                elif hasattr(event, 'group_id'):
                    group_id = event.group_id
                elif hasattr(event, 'group') and hasattr(event.group, 'id'):
                    group_id = event.group.id
                elif hasattr(event, 'message_obj') and hasattr(event.message_obj, 'group_id'):
                    group_id = event.message_obj.group_id
            except Exception:
                pass
            
            # 检查是否在被禁言的群中
            if group_id and group_id in self.muted_groups:
                return

            # 获取实时配置
            config = self.get_realtime_config()
            
            # 让大模型分析消息意图
            intent = await self.analyze_intent(message_str, event)
            
            # 根据意图处理消息
            if intent == 1:  # 需要私聊
                enable_private_chat = config.get("enable_private_chat", True)
                if enable_private_chat:
                    prompt = f"用户要求私聊，现在你需要在私聊中回复他。\n\n用户说：'{message_str}'\n\n请生成一个友好、自然的私聊回复，符合你作为AI助手的性格。"
                    response = await self.call_llm(prompt, event)
                    
                    if response:
                        success = await self.send_private_message(user_id, response, event)
                        if success:
                            return MessageEventResult().stop_event()
            
            elif intent == 2:  # 需要告状
                enable_sue = config.get("enable_sue", True)
                if enable_sue:
                    # 让大模型自己生成告状内容
                    prompt = f"用户说：'{message_str}'，看起来像是在辱骂或欺负我。请生成一个告状消息，向管理员汇报这件事，语气要委屈但不要过激。"
                    sue_message = await self.call_llm(prompt, event)
                    
                    if not sue_message:
                        sue_message = f"管理员，有人在欺负我！\n\n用户说：{message_str}"
                    
                    admin_list = config.get("admin_list", ["2757808353"])
                    for admin_id in admin_list:
                        await self.send_private_message(admin_id, sue_message, event)
                    
                    return MessageEventResult().stop_event()
            
            # 普通对话，不做特殊处理
            return

        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            await self.send_error_message(event, "on_all_messages", str(e), traceback.format_exc())
            return MessageEventResult().stop_event()
    
    async def terminate(self):
        """插件卸载"""
        logger.info("自动私聊插件已卸载")
