"""
文件验证工具

提供上传文件的安全校验：
1. 扩展名白名单校验
2. 文件大小限制
3. 魔数（MIME 类型）校验，防止伪造后缀
"""

import os

# 允许的扩展名
ALLOWED_EXTS = {".txt", ".md", ".pdf"}

# 扩展名 → 合法 MIME 类型（魔数验证）
# .txt/.md 的 magic 检测结果因 libmagic 版本不同会有差异，放宽匹配
EXT_MIME_MAP = {
    ".pdf": ["application/pdf"],
    ".txt": ["text/plain", "text/x-algol68", "application/octet-stream"],
    ".md": ["text/plain", "text/markdown", "text/x-algol68", "application/octet-stream"],
}

# 默认最大文件大小 10MB
MAX_FILE_SIZE = 10 * 1024 * 1024


def validate_ext(filename):
    """校验文件扩展名，返回小写扩展名或抛出 ValueError"""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError(f"不支持的文件格式 {ext}，只支持 {', '.join(ALLOWED_EXTS)}")
    return ext


def validate_size(file_path, max_size=MAX_FILE_SIZE):
    """校验文件大小，超限则抛出 ValueError"""
    size = os.path.getsize(file_path)
    if size > max_size:
        raise ValueError(f"文件大小 {size // 1024 // 1024}MB 超过限制 {max_size // 1024 // 1024}MB")


def validate_mime(file_path, ext):
    """魔数校验：使用 filetype 库检测真实类型，失败则 fallback 到后缀判断"""
    try:
        import filetype

        kind = filetype.guess(file_path)
        if kind is None:
            return
        detected = kind.mime
        allowed = EXT_MIME_MAP.get(ext, [])
        if allowed and detected not in allowed:
            raise ValueError(f"文件内容类型 {detected} 与扩展名 {ext} 不匹配，疑似伪造文件")
    except ImportError:
        pass


def validate_file(file_path, filename):
    """一站式校验：扩展名 + 大小 + 魔数（魔数不可用时降级为后缀）。全部通过返回小写扩展名。"""
    ext = validate_ext(filename)
    validate_size(file_path)
    validate_mime(file_path, ext)
    return ext
