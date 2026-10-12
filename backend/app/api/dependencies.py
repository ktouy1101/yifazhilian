from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.db import Database, token_hash, user_dict, utcnow

bearer = HTTPBearer(auto_error=False)


def get_database(request: Request) -> Database:
    return request.app.state.database


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                 database: Database = Depends(get_database)):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "需要有效的演示访问令牌")
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?",
            (token_hash(credentials.credentials), utcnow().isoformat())).fetchone()
    if row is None:
        raise HTTPException(401, "演示令牌无效或已过期")
    return user_dict(row)


def patient(user=Depends(current_user)):
    if user["role"] != "patient":
        raise HTTPException(403, "志愿者无患者健康数据权限")
    return user


def require_consent(connection, user_id: str, scope: str):
    row = connection.execute(
        "SELECT 1 FROM consents WHERE user_id=? AND scope=? AND granted=1 AND expires_at>?",
        (user_id, scope, utcnow().isoformat())).fetchone()
    if row is None:
        raise HTTPException(403, f"用途 {scope} 未获授权、已撤回或已到期")


def owned_row(row):
    if row is None:
        raise HTTPException(404, "资源不存在")
    return row
