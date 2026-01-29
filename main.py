from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import json
import os
import traceback

# 错误捕获装饰器
def error_catcher(func):
    async def wrapper(self, *args, **kwargs):
        try:
            # 调用原始函数
            result = await func(self, *args, **kwargs)
            # 检查结果是否是异步生成器
            if hasattr(result, '__aiter__'):
                # 如果是异步生成器，就异步迭代它
                async for item in result:
                    yield item
            else:
                # 如果不是异步生成器，就直接返回
                return result
        except Exception as e:
            # 捕获错误
            error_message = f"{func.__name__} 方法执行失败: {str(e)}"
            error_traceback = traceback.format_exc()
            logger.error(f"{error_message}\n{error_traceback}")
            
            # 转发错误信息给指定用户
            if self.config["error_target"]:
                error_info = f"【错误信息】\n方法: {func.__name__}\n错误: {str(e)}\n\n【详细信息】\n{error_traceback}"
                await self.send_private_message(self.config["error_target"], error_info)
            
            # 如果是事件处理方法，返回错误信息给用户
            for arg in args:
                if isinstance(arg, AstrMessageEvent):
                    try:
                        # 返回错误信息
                        yield arg.plain_result(f"操作失败: {str(e)}")
                    except Exception as yield_error:
                        logger.error(f"返回错误信息失败: {yield_error}")
                    break
    return wrapper

@register("astrbot_plugin_zhudongshiliao", "引灯续昼", "自动私聊插件，当用户发送消息时，自动私聊用户。支持群消息总结、错误信息转发等功能。", "v1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config_file = os.path.join(os.path.dirname(__file__), "config.json")
        self.config = self._load_config()

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        # 从 WebUI 读取配置
        self._load_webui_config()
        logger.info("自动私聊插件初始化完成")

    def _load_webui_config(self):
        """从 WebUI 读取配置"""
        try:
            # 使用 context 获取 WebUI 配置
            webui_config = self.context.get_config()
            if webui_config:
                logger.info("从 WebUI 加载配置成功")
                # 合并 WebUI 配置和本地配置
                for key, value in webui_config.items():
                    if key != "group_message_history":  # 消息历史不从 WebUI 加载
                        self.config[key] = value
                # 保存合并后的配置
                self._save_config(self.config)
        except Exception as e:
            logger.error(f"从 WebUI 加载配置失败: {e}")

    def _load_config(self):
        """加载配置文件"""
        default_config = {
            "error_target": "",  # 错误信息转发目标用户
            "summary_keywords": ["总结", "汇总", "总结一下"],  # 群消息总结触发关键词
            "private_keywords": ["私聊", "私信"],  # 私聊触发关键词
            "auto_summary": False,  # 是否自动总结群消息
            "summary_interval": 300,  # 自动总结间隔（秒）
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

    # 监听群消息
    @filter.group_message()
    @error_catcher
    async def on_group_message(self, event: AstrMessageEvent):
        """监听群消息，记录消息历史，处理触发关键词"""
        group_id = event.get_group_id()
        if group_id:
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
            for keyword in self.config["summary_keywords"]:
                if keyword in message_str:
                    await self.handle_summary_request(event)
                    break
            
            # 检查是否触发私聊关键词
            for keyword in self.config["private_keywords"]:
                if keyword in message_str:
                    await self.handle_private_request(event)
                    break
            
            # 处理自动私聊
            await self.auto_private_message(event)

    # 监听私聊消息
    @filter.private_message()
    @error_catcher
    async def on_private_message(self, event: AstrMessageEvent):
        """监听私聊消息，处理用户请求"""
        user_id = event.get_sender_id()
        message_str = event.message_str
        logger.info(f"收到私聊消息 from {user_id}: {message_str}")
        
        # 这里可以添加私聊消息的处理逻辑
        # 例如：处理用户的设置请求，处理用户的命令等

    @error_catcher
    async def handle_summary_request(self, event: AstrMessageEvent):
        """处理群消息总结请求"""
        group_id = event.get_group_id()
        if not group_id:
            return
        
        # 获取群消息历史
        message_history = self.config["group_message_history"].get(group_id, [])
        if not message_history:
            yield event.plain_result("暂无消息记录，无法总结")
            return
        
        # 生成消息总结
        summary = await self.generate_summary(message_history)
        
        # 私聊发送总结
        sender_id = event.get_sender_id()
        await self.send_private_message(sender_id, f"群消息总结：\n{summary}")
        
        # 回复用户
        yield event.plain_result("已将群消息总结发送到您的私聊")

    @error_catcher
    async def handle_private_request(self, event: AstrMessageEvent):
        """处理私聊请求"""
        sender_id = event.get_sender_id()
        message_str = event.message_str
        
        # 发送私聊消息
        await self.send_private_message(sender_id, f"您请求的私聊内容：\n{message_str}")
        
        # 回复用户
        yield event.plain_result("已发送私聊消息")

    async def generate_summary(self, message_history):
        """生成消息总结"""
        # 简单的总结逻辑，实际应用中可以调用AI进行更智能的总结
        summary = "最近的群消息：\n"
        for msg in message_history[-20:]:  # 只总结最近20条消息
            summary += f"[{msg['sender']}] {msg['message']}\n"
        return summary

    async def send_private_message(self, user_id, message):
        """发送私聊消息"""
        # 使用 AstrBot 的消息发送API发送私聊消息
        try:
            # 构建私聊消息事件
            # 注意：这里需要根据 AstrBot 的具体API进行调整
            # 暂时使用 logger 记录，实际实现中需要使用正确的API
            logger.info(f"发送私聊消息到 {user_id}: {message}")
            
            # 示例：使用 context 发送私聊消息
            # 假设 context 有 send_private_message 方法
            # await self.context.send_private_message(user_id, message)
            
            # 另一种可能的实现方式：使用 event 的方法
            # 假设 event 有 send_private 方法
            # await event.send_private(user_id, message)
        except Exception as e:
            logger.error(f"发送私聊消息失败: {e}")
            # 转发错误信息给指定用户
            if self.config["error_target"]:
                await self.send_private_message(self.config["error_target"], f"发送私聊消息失败: {e}")

    # 主动私聊指令
    @filter.command("private")
    @error_catcher
    async def command_private(self, event: AstrMessageEvent):
        """主动触发私聊，格式：/private <用户ID> <消息内容>"""
        message_str = event.message_str
        # 解析命令参数
        parts = message_str.split(" ", 2)
        if len(parts) < 3:
            yield event.plain_result("命令格式错误，请使用：/private <用户ID> <消息内容>")
            return
        
        user_id = parts[1]
        private_message = parts[2]
        
        # 发送私聊消息
        await self.send_private_message(user_id, private_message)
        yield event.plain_result(f"已向用户 {user_id} 发送私聊消息")

    # 自动私聊功能 - 基于关键词的被动私聊
    @error_catcher
    async def auto_private_message(self, event: AstrMessageEvent):
        """自动私聊功能，当用户发送特定消息时自动私聊"""
        user_id = event.get_sender_id()
        message_str = event.message_str
        
        # 这里可以添加自动私聊的触发条件
        # 例如：当用户发送特定关键词时，自动私聊用户
        
        # 示例：当用户发送 "你好" 时，自动私聊用户
        if "你好" in message_str:
            await self.send_private_message(user_id, "你好！我是自动私聊机器人，有什么可以帮助你的吗？")

    # 群消息总结指令
    @filter.command("summary")
    @error_catcher
    async def command_summary(self, event: AstrMessageEvent):
        """手动触发群消息总结，格式：/summary [群ID]"""
        message_str = event.message_str
        # 解析命令参数
        parts = message_str.split(" ")
        
        # 如果指定了群ID，使用指定的群ID
        if len(parts) > 1:
            group_id = parts[1]
            # 检查群ID是否存在于历史记录中
            if group_id not in self.config["group_message_history"]:
                yield event.plain_result(f"未找到群 {group_id} 的消息记录")
                return
            
            # 生成消息总结
            message_history = self.config["group_message_history"][group_id]
            summary = await self.generate_summary(message_history)
            
            # 私聊发送总结
            sender_id = event.get_sender_id()
            await self.send_private_message(sender_id, f"群 {group_id} 的消息总结：\n{summary}")
            yield event.plain_result(f"已将群 {group_id} 的消息总结发送到您的私聊")
        else:
            # 否则使用当前群
            await self.handle_summary_request(event)

    # 设置错误信息转发目标指令
    @filter.command("set_target")
    @error_catcher
    async def command_set_target(self, event: AstrMessageEvent):
        """设置错误信息转发目标，格式：/set_target <用户ID>"""
        message_str = event.message_str
        # 解析命令参数
        parts = message_str.split(" ")
        if len(parts) < 2:
            yield event.plain_result("命令格式错误，请使用：/set_target <用户ID>")
            return
        
        target_user_id = parts[1]
        # 更新配置
        self.config["error_target"] = target_user_id
        self._save_config(self.config)
        
        yield event.plain_result(f"已设置错误信息转发目标为：{target_user_id}")

    # 查看配置指令
    @filter.command("config")
    @error_catcher
    async def command_config(self, event: AstrMessageEvent):
        """查看当前配置"""
        config_info = f"【自动私聊插件配置】\n"
        config_info += f"错误信息转发目标：{self.config['error_target']}\n"
        config_info += f"群消息总结触发关键词：{', '.join(self.config['summary_keywords'])}\n"
        config_info += f"私聊触发关键词：{', '.join(self.config['private_keywords'])}\n"
        config_info += f"是否自动总结群消息：{'是' if self.config['auto_summary'] else '否'}\n"
        config_info += f"自动总结间隔：{self.config['summary_interval']} 秒\n"
        config_info += f"已记录消息的群数量：{len(self.config['group_message_history'])}\n"
        
        # 发送配置信息给用户
        sender_id = event.get_sender_id()
        await self.send_private_message(sender_id, config_info)
        yield event.plain_result("已将当前配置发送到您的私聊")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        logger.info("自动私聊插件已卸载")
