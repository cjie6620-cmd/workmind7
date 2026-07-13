"""认证相关 Pydantic 模型"""

from pydantic import BaseModel, Field


class UserContext(BaseModel):
    """当前请求用户上下文（来自 JWT access token）"""

    user_id: str = Field(description='用户唯一 ID，对应 JWT sub')
    username: str = Field(description='登录用户名')
    role: str = Field(description='角色：user / admin')


class LoginRequest(BaseModel):
    """登录请求"""

    username: str = Field(..., min_length=1, max_length=64, description='用户名')
    password: str = Field(..., min_length=1, max_length=128, description='密码')


class RefreshRequest(BaseModel):
    """刷新 access token 请求"""

    refreshToken: str = Field(..., min_length=10, description='refresh token')


class TokenResponse(BaseModel):
    """登录 / 刷新成功响应"""

    accessToken: str = Field(description='JWT access token')
    refreshToken: str = Field(description='JWT refresh token')
    tokenType: str = Field(default='Bearer', description='Token 类型')
    expiresIn: int = Field(description='access token 有效期（秒）')
    role: str = Field(description='用户角色')
    userId: str = Field(description='用户 ID')
