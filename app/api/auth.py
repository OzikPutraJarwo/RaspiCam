from fastapi import APIRouter, Body, HTTPException, Request, Response

from ..auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    authenticated,
    clear_failures,
    client_key,
    create_session,
    is_configured,
    rate_limited,
    register_failure,
    require_session,
    set_password,
    verify_password,
)
from ..config import config

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _apply_session(response: Response):
    response.set_cookie(
        SESSION_COOKIE,
        create_session(),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )


@router.get("/state")
async def state(request: Request):
    return {"configured": is_configured(), "authenticated": authenticated(request)}


@router.post("/setup")
async def setup(response: Response, password: str = Body(..., embed=True)):
    if is_configured():
        raise HTTPException(status_code=409, detail="Already configured")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    set_password(password)
    _apply_session(response)
    return {"ok": True}


@router.post("/login")
async def login(request: Request, response: Response, password: str = Body(..., embed=True)):
    if not is_configured():
        raise HTTPException(status_code=409, detail="Setup required")
    key = client_key(request)
    if rate_limited(key):
        raise HTTPException(status_code=429, detail="Too many attempts, try again later")
    if not verify_password(password, config.section("auth").get("password")):
        register_failure(key)
        raise HTTPException(status_code=401, detail="Incorrect password")
    clear_failures(key)
    _apply_session(response)
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post("/password")
async def change_password(
    request: Request,
    response: Response,
    current: str = Body(...),
    password: str = Body(...),
):
    require_session(request)
    if not verify_password(current, config.section("auth").get("password")):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    set_password(password)
    _apply_session(response)
    return {"ok": True}
