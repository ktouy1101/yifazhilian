from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.db import Database, token_hash, user_dict, utcnow

bearer = HTTPBearer(auto_error=False)


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_ai_provider(request: Request):
    return request.app.state.ai_provider


def consent_policy(scope: str, provider) -> dict:
    if scope == "vitals":
        return {"recipient": "local_health_service", "policy_version": "health-records-1",
                "notice": "将您主动填写的本人测量值、测量时间与来源、身体感受、用药计划、实际服药记录和复诊待办保存到当前连接的电脑，用于记录回顾和待办展示；不自动接入设备，不发送给外部AI，也不提供疾病诊断或自动改药。授权有效期30天，可随时撤回；撤回阻断后续访问，已存记录不会自动删除，可在重新授权后逐项删除。当前电脑数据库未加密，当前登录与部署仍为开发验证环境。",
                "external_network": False, "provider": "local"}
    if scope == "records_read":
        return {"recipient": "local_record_service", "policy_version": "records-local-3",
                "notice": "将您上传的本人检验单或病历照片保存到当前连接的电脑，用于本地文字识别、原图核对、保存草稿、确认归档和更正回查；资料归入当前登录账号，不发送给外部AI。请确认资料属于本人，并检查照片内容。授权有效期30天，可随时撤回；撤回阻断后续访问与识别结果保存，已存资料不会自动删除。当前电脑的数据库未加密。",
                "external_network": False, "provider": "local"}
    if scope.startswith("ai_"):
        return {"recipient": provider.recipient, "policy_version": provider.policy_version,
                "notice": provider.consent_notice, "external_network": provider.external_network,
                "provider": provider.name}
    purpose = "保存和展示合成设备读数" if scope == "vitals" else "查看本机合成病历"
    return {"recipient": "local_demo_process", "policy_version": "demo-1",
            "notice": f"仅在这台电脑{purpose}。授权有效期30天，可随时撤回；撤回后停止后续使用，已保存记录不会自动删除，重启后仍保留。禁止上传真实患者资料。",
            "external_network": False, "provider": "local"}


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                 database: Database = Depends(get_database)):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "需要有效的演示访问令牌")
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.expires_at>? AND u.deleted_at IS NULL",
            (token_hash(credentials.credentials), utcnow().isoformat())).fetchone()
    if row is None:
        raise HTTPException(401, "演示令牌无效或已过期")
    return user_dict(row)


def patient(user=Depends(current_user)):
    if user["role"] != "patient":
        raise HTTPException(403, "志愿者无患者健康数据权限")
    return user


def require_reviewer(user=Depends(current_user), database: Database = Depends(get_database)):
    """审核员/管理员：能力来自数据库（user_roles 或导航审核位），不看客户端声明。"""
    from app.services import roles

    with database.transaction() as connection:
        if not roles.capabilities(connection, user)["is_reviewer"]:
            raise HTTPException(403, "需要审核员权限")
    return user


def require_consent(connection, user_id: str, scope: str, policy: dict | None = None):
    row = connection.execute(
        "SELECT * FROM consents WHERE user_id=? AND scope=? AND granted=1 AND revoked_at IS NULL AND expires_at>?",
        (user_id, scope, utcnow().isoformat())).fetchone()
    if row is None:
        raise HTTPException(403, f"用途 {scope} 未获授权、已撤回或已到期")
    if policy and (row["recipient"] != policy["recipient"] or row["policy_version"] != policy["policy_version"]):
        raise HTTPException(403, "接收方或用途告知已变化，请在我的→设置重新阅读并授权")
    return (row["id"], row["created_at"], row["recipient"], row["policy_version"])


def owned_row(row):
    if row is None:
        raise HTTPException(404, "资源不存在")
    return row
