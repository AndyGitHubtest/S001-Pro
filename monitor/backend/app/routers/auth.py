"""
登录认证接口
"""
from datetime import timedelta
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..auth import authenticate_user, create_access_token, get_settings

router = APIRouter()
settings = get_settings()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    success: bool
    data: dict


@router.post("/auth/login")
async def login(request: LoginRequest):
    """用户登录"""
    user = authenticate_user(request.username, request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]}, expires_delta=access_token_expires
    )
    
    return {
        "success": True,
        "data": {
            "token": access_token,
            "token_type": "bearer",
            "username": user["username"],
            "role": user["role"]
        }
    }
