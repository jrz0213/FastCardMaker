import os
import logging
import tempfile
from logging.handlers import RotatingFileHandler

# 将此变量设置为 True 即可默认开启日志
ENABLE_LOGGING = True

class TruncatingFormatter(logging.Formatter):
    """
    自定义的日志格式化器，用于自动截断过长的日志消息
    """
    def __init__(self, fmt=None, max_len=500):
        super().__init__(fmt)
        self.max_len = max_len

    def format(self, record):
        # 先把消息和参数拼接成最终的字符串
        msg = record.getMessage()
        
        # 如果长度超过限制，进行截断并加上提示
        if len(msg) > self.max_len:
            msg = msg[:self.max_len] + f" ... [后续内容过长已自动截断，原长 {len(msg)} 字符]"
            
        # 临时替换 record 的信息以便父类按照格式（fmt）生成最终文本
        original_msg = record.msg
        original_args = record.args
        record.msg = msg
        record.args = None
        
        result = super().format(record)
        
        # 恢复现场（防止影响其他可能存在的 Handler）
        record.msg = original_msg
        record.args = original_args
        
        return result


logger = logging.getLogger('FastCardMaker_Log')
logger.propagate = False
def set_logging_state(enable: bool):
    global ENABLE_LOGGING
    ENABLE_LOGGING = enable
    
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
        
    if enable:
        logger.setLevel(logging.INFO)
        
        # ========== 【最优修改】 ==========
        # 获取操作系统的临时目录 (如 C:\Users\xxx\AppData\Local\Temp)
        # 这个目录的文件会被操作系统自动回收清理，且不会锁死 Anki 插件更新
        temp_dir = tempfile.gettempdir()
        log_path = os.path.join(temp_dir, 'FastCardMaker.log')
        # ==================================
        
        fh = RotatingFileHandler(log_path, maxBytes=1024*1024, backupCount=1, encoding='utf-8')
        fmt = '%(asctime)s | %(levelname)s | %(message)s'
        fh.setFormatter(TruncatingFormatter(fmt, max_len=500)) 
        logger.addHandler(fh)
        logger.info(f"[系统控制] 日志已开启，临时存储于: {log_path}")
    else:
        logger.setLevel(logging.WARNING)
        logger.addHandler(logging.NullHandler())
