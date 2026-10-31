from datetime import timedelta
from contextlib import nullcontext
import json
import logging
from secrets import randbelow, token_urlsafe
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from app.api.dependencies import (bearer, consent_policy, current_user, get_ai_provider,
                                  get_database, owned_row, patient, require_consent,
                                  require_reviewer)
from fastapi.security import HTTPAuthorizationCredentials
from app.ai.providers.base import ProviderError
from app.config import (DISCLAIMER, DISCLAIMER_LEGAL, TOKEN_TTL_SECONDS, consent_ttl,
                        demo_auth_enabled, legal_mcp_fallback_enabled, runtime_mode)
from app.db import (Database, audit, consent_dict, conversation_dict, emergency_dict,
                    new_id, token_hash, user_dict, utcnow, vital_dict)
from app.schemas import (ConsentInput, ConversationInput, DemoLogin, Domain,
                         EmergencyInput, MedicationCreate, MessageInput,
                         PasswordLoginInput, PhoneLoginInput, ProfileUpdate,
                         RecordCreate, SendCodeInput, Scope, SetPasswordInput,
                         VitalInput, WechatLoginInput)
from app.services import legal_agent, medical_agent, roles
from app.services import passwords
from app.services.knowledge import citation
from app.services.knowledge_provider import KnowledgeProviderError, LocalKnowledgeProvider
from app.services.rag import answer_record_checklist, answer_visit_question, respond, smalltalk
from app.services.vitals import alert_for, validate_vital
from app.services.wechat import WechatLoginError, exchange_code

router = APIRouter()
logger = logging.getLogger("app.api")


@router.get("/health")
def health():
    """公开探针：只说“活着、数据在哪”。

    模型、运行模式、演示登录开关这些部署细节不放在公开接口上——否则等于在门口
    挂牌告诉别人“这里还能用固定验证码登录”。审核员可看 /admin/runtime。
    """
    return {"status": "ok", "storage": "sqlite_local"}


@router.get("/admin/runtime")
def admin_runtime(request: Request, provider=Depends(get_ai_provider),
                  user=Depends(require_reviewer)):
    knowledge = request.app.state.knowledge_provider
    return {"status": "ok", "mode": runtime_mode(), "demo_auth": demo_auth_enabled(),
            "ai_provider": provider.name, "external_network": provider.external_network,
            "storage": "sqlite_local", "legal_retrieval": knowledge.mode("legal")}


@router.get("/knowledge/search")
def search_knowledge(request: Request, domain: Domain = Query(..., description="medical or legal"),
                     q: str = Query(..., min_length=1, max_length=200),
                     limit: int = Query(default=3, ge=1, le=5),
                     user=Depends(current_user), database: Database = Depends(get_database)):
    provider = request.app.state.knowledge_provider
    try:
        with (database.transaction() if provider.uses_database(domain) else nullcontext()) as connection:
            items = provider.search(connection, domain, q, limit=limit)
    except KnowledgeProviderError as error:
        raise HTTPException(503, str(error)) from None
    return {
        "domain": domain, "query": q, "retrieval": provider.mode(domain),
        "items": [citation(item) for item in items],
        "notice": "知识库只返回已发布且在有效期内的来源；外部 MCP 结果标记为 external，不能替代专业核实。",
    }


@router.post("/auth/demo-login")
def demo_login(payload: DemoLogin, request: Request,
               database: Database = Depends(get_database)):
    # The demo selector is a development door. It must close together with the
    # fixed verification code, otherwise "DEMO_AUTH=0" would still leave a way
    # to log in as the seeded volunteer/reviewer accounts.
    if not demo_auth_enabled():
        raise HTTPException(403, "演示登录已关闭；请使用手机号或微信登录")
    alias = payload.demo_alias or ("demo-patient-001" if payload.role == "patient" else "demo-volunteer-001")
    with database.transaction(write=True) as connection:
        # A phone/WeChat account may be marked for testing while retaining its login.
        row = connection.execute(
            "SELECT * FROM users WHERE id=? AND role=? AND synthetic=1 AND phone IS NULL AND openid IS NULL",
            (alias, payload.role)).fetchone()
        if row is None:
            raise HTTPException(422, "仅支持固定的合成演示账号，不接收openid或真实患者标识")
        if (roles.REVIEWER in roles.roles_of(connection, row["id"])
                and not roles.is_loopback(request.client.host if request.client else None)):
            raise HTTPException(403, "演示审核员只能在开发机本机登录；局域网请用工作人员入口")
        user = user_dict(row)
        token = token_urlsafe(32)
        connection.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                           (token_hash(token), user["id"], utcnow().isoformat(),
                            (utcnow() + timedelta(seconds=TOKEN_TTL_SECONDS)).isoformat()))
        audit(connection, user["id"], "demo_login", user["id"])
    return {"access_token": token, "token_type": "bearer", "expires_in": TOKEN_TTL_SECONDS,
            "user": user, "notice": "公开演示身份选择器，不能用于真实身份认证"}


@router.post("/auth/wechat-login")
def wechat_login(payload: WechatLoginInput, database: Database = Depends(get_database),
                 request: Request = None):
    config = request.app.state.wechat_config if request else None
    try:
        result = exchange_code(payload.code, config)
    except WechatLoginError as error:
        raise HTTPException(error.code, error.message)
    openid = result["openid"]
    with database.transaction(write=True) as connection:
        row = connection.execute("SELECT * FROM users WHERE openid=?", (openid,)).fetchone()
        if row is None:
            uid = f"wx_{uuid4().hex[:12]}"
            connection.execute(
                "INSERT INTO users(id,role,display_name,synthetic,openid) VALUES(?,?,?,0,?)",
                (uid, "patient", "微信用户", openid))
            connection.execute(
                "SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            row = connection.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        user = user_dict(row)
        token = token_urlsafe(32)
        connection.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                           (token_hash(token), user["id"], utcnow().isoformat(),
                            (utcnow() + timedelta(seconds=TOKEN_TTL_SECONDS)).isoformat()))
        audit(connection, user["id"], "wechat_login", user["id"])
    return {"access_token": token, "token_type": "bearer", "expires_in": TOKEN_TTL_SECONDS,
            "user": user, "notice": "真实微信登录"}


@router.post("/auth/send-code")
def send_code(payload: SendCodeInput, database: Database = Depends(get_database)):
    """发送验证码。

    本地演示模式（默认，YIFAZHILIAN_DEMO_AUTH=1）固定 123456 并在响应里回显
    dev_code，只用于开发者工具和 M11 HTTP 验收；上线前必须设
    YIFAZHILIAN_DEMO_AUTH=0 并接入真实短信通道——那时验证码随机生成，响应
    不再包含 dev_code，任何人无法从接口读到别人的验证码。
    """
    demo = demo_auth_enabled()
    code = "123456" if demo else f"{randbelow(1_000_000):06d}"
    with database.transaction(write=True) as connection:
        now = utcnow()
        connection.execute("DELETE FROM verification_codes WHERE phone=?", (payload.phone,))
        connection.execute(
            "INSERT INTO verification_codes(phone,code,created_at,expires_at,used) VALUES(?,?,?,?,0)",
            (payload.phone, code, now.isoformat(),
             (now + timedelta(minutes=5)).isoformat()))
    body = {"sent": True, "expires_in": 300}
    if demo:
        body["dev_code"] = code
    return body


@router.post("/auth/phone-login")
def phone_login(payload: PhoneLoginInput, database: Database = Depends(get_database)):
    with database.transaction(write=True) as connection:
        row = connection.execute(
            "SELECT * FROM verification_codes WHERE phone=? AND code=? AND used=0",
            (payload.phone, payload.code)).fetchone()
        if row is None:
            raise HTTPException(401, "验证码错误或已过期")
        if utcnow().isoformat() > row["expires_at"]:
            raise HTTPException(401, "验证码已过期，请重新获取")
        connection.execute("UPDATE verification_codes SET used=1 WHERE phone=? AND code=?",
                           (payload.phone, payload.code))

        user_row = connection.execute("SELECT * FROM users WHERE phone=?", (payload.phone,)).fetchone()
        if user_row is None:
            uid = f"u_{uuid4().hex[:12]}"
            masked = payload.phone[:3] + "****" + payload.phone[7:]
            connection.execute(
                "INSERT INTO users(id,role,display_name,synthetic,phone) VALUES(?,?,?,0,?)",
                (uid, "patient", masked, payload.phone))
            user_row = connection.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        user = user_dict(user_row)
        # 审核员由配置指定：只有 YIFAZHILIAN_ADMIN_PHONE 里的号码会在登录时获得权限。
        roles.grant_admin(connection, user, payload.phone)
        token = token_urlsafe(32)
        connection.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                           (token_hash(token), user["id"], utcnow().isoformat(),
                            (utcnow() + timedelta(seconds=TOKEN_TTL_SECONDS)).isoformat()))
        audit(connection, user["id"], "phone_login", user["id"])
    return {"access_token": token, "token_type": "bearer", "expires_in": TOKEN_TTL_SECONDS,
            "user": user, "notice": "手机号登录"}


@router.post("/auth/password-login")
def password_login(payload: PasswordLoginInput, database: Database = Depends(get_database)):
    """密码登录。只在账号已设置密码时可用；没设过密码的账号仍走验证码。"""
    with database.transaction(write=True) as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE phone=? AND deleted_at IS NULL", (payload.phone,)).fetchone()
        # 账号不存在与密码错误返回同一句话，避免泄露号码是否注册。
        if row is None or not passwords.verify_password(payload.password, row["password_hash"]):
            raise HTTPException(401, "手机号或密码不正确")
        user = user_dict(row)
        roles.grant_admin(connection, user, payload.phone)
        token = token_urlsafe(32)
        connection.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                           (token_hash(token), user["id"], utcnow().isoformat(),
                            (utcnow() + timedelta(seconds=TOKEN_TTL_SECONDS)).isoformat()))
        audit(connection, user["id"], "password_login", user["id"])
    return {"access_token": token, "token_type": "bearer", "expires_in": TOKEN_TTL_SECONDS,
            "user": user, "notice": "密码登录"}


@router.post("/auth/password")
def set_own_password(payload: SetPasswordInput, user=Depends(current_user),
                     database: Database = Depends(get_database)):
    """已登录用户设置/修改自己的密码。"""
    with database.transaction(write=True) as connection:
        connection.execute("UPDATE users SET password_hash=? WHERE id=?",
                           (passwords.hash_password(payload.password), user["id"]))
        audit(connection, user["id"], "password_set", user["id"])
    return {"ok": True}


@router.post("/auth/logout", status_code=204)
def logout(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
           database: Database = Depends(get_database)):
    # Idempotent: missing or already-invalid tokens still return 204 so client
    # cleanup never fails. The raw token is only used to look up its sha256 row.
    if credentials and credentials.scheme.lower() == "bearer":
        digest = token_hash(credentials.credentials)
        with database.transaction(write=True) as connection:
            row = connection.execute(
                "SELECT user_id FROM sessions WHERE token_hash=?", (digest,)).fetchone()
            if row is not None:
                connection.execute("DELETE FROM sessions WHERE token_hash=?", (digest,))
                audit(connection, row["user_id"], "session_revoked", digest)
    return None


@router.get("/users/me")
def me(user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        row = connection.execute("SELECT * FROM user_profiles WHERE user_id=?", (user["id"],)).fetchone()
        profile = dict(row) if row else None
        # 身份与能力由服务端算好再给客户端，客户端只负责显示与隐藏入口。
        capabilities = roles.capabilities(connection, user)
    return {**user, "profile": profile, "capabilities": capabilities}


@router.get("/admin/ping")
def admin_ping(user=Depends(require_reviewer)):
    """权限探针占位：P3 的管理台接口都挂在 /admin 下，这里先证明鉴权生效。"""
    return {"ok": True, "user_id": user["id"]}


@router.get("/admin/users")
def admin_list_users(user=Depends(require_reviewer), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT id,role,display_name,synthetic,phone,deleted_at FROM users "
            "ORDER BY (deleted_at IS NOT NULL), synthetic DESC, id").fetchall()
        granted = {}
        for row in connection.execute("SELECT user_id,role FROM user_roles"):
            granted.setdefault(row["user_id"], set()).add(row["role"])
        items = []
        for row in rows:
            phone = row["phone"]
            items.append({
                "id": row["id"], "role": row["role"], "display_name": row["display_name"],
                "synthetic": bool(row["synthetic"]),
                "phone": (phone[:3] + "****" + phone[7:]) if phone else None,
                "deleted": bool(row["deleted_at"]),
                "roles": sorted(granted.get(row["id"], set())),
            })
    return {"items": items}


@router.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: str, user=Depends(require_reviewer),
                      database: Database = Depends(get_database)):
    """软删除账号：保留用户行，让审计记录始终指向真实对象。

    同时释放手机号与 openid（便于同一号码重新注册）并撤销全部会话，
    已发出的令牌立刻失效；历史消息、授权、会话记录随之不再可访问。
    """
    if user_id == user["id"]:
        raise HTTPException(400, "不能删除当前登录的账号")
    with database.transaction(write=True) as connection:
        row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "账号不存在")
        if row["deleted_at"]:
            return {"id": user_id, "deleted": True, "already_deleted": True}
        connection.execute(
            "UPDATE users SET deleted_at=?, phone=NULL, openid=NULL, display_name=? WHERE id=?",
            (utcnow().isoformat(), "已注销账号", user_id))
        connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        connection.execute("DELETE FROM user_roles WHERE user_id=?", (user_id,))
        connection.execute("DELETE FROM navigation_memberships WHERE user_id=?", (user_id,))
        audit(connection, user["id"], "admin_delete_user", user_id)
    return {"id": user_id, "deleted": True}


@router.patch("/users/me")
def update_profile(payload: ProfileUpdate, user=Depends(current_user), database: Database = Depends(get_database)):
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "没有要更新的字段")
    with database.transaction(write=True) as connection:
        existing = connection.execute("SELECT user_id FROM user_profiles WHERE user_id=?", (user["id"],)).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO user_profiles(user_id,nickname,age,gender,bed_location,allergies,emergency_name,emergency_phone,doctor_phone,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (user["id"], fields.get("nickname"), fields.get("age"), fields.get("gender"),
                 fields.get("bed_location"), fields.get("allergies"),
                 fields.get("emergency_name"), fields.get("emergency_phone"),
                 fields.get("doctor_phone"), utcnow().isoformat()))
        else:
            sets = ", ".join(f"{k}=?" for k in fields)
            connection.execute(f"UPDATE user_profiles SET {sets}, updated_at=? WHERE user_id=?",
                               (*fields.values(), utcnow().isoformat(), user["id"]))
        row = connection.execute("SELECT * FROM user_profiles WHERE user_id=?", (user["id"],)).fetchone()
        audit(connection, user["id"], "profile_updated", user["id"])
    return {**user, "profile": dict(row) if row else None}


@router.get("/consents")
def list_consents(user=Depends(patient), database: Database = Depends(get_database), provider=Depends(get_ai_provider)):
    with database.transaction() as connection:
        return {"items": [consent_dict(connection, row) for row in connection.execute(
            "SELECT * FROM consents WHERE user_id=? ORDER BY scope", (user["id"],))],
                "policies": {scope: consent_policy(scope, provider) for scope in
                             ("ai_medical", "ai_legal", "vitals", "records_read")}}


@router.post("/consents", status_code=201)
def grant_consent(payload: ConsentInput, user=Depends(patient), database: Database = Depends(get_database), provider=Depends(get_ai_provider)):
    policy = consent_policy(payload.scope, provider)
    supplied = payload.recipient is not None or payload.policy_version is not None
    if (policy["external_network"] or supplied) and (payload.recipient != policy["recipient"] or payload.policy_version != policy["policy_version"]):
        raise HTTPException(409, "请先读取当前接收方和告知版本，再单独确认授权")
    with database.transaction(write=True) as connection:
        now = utcnow()
        connection.execute(
            """INSERT INTO consents(id,user_id,scope,granted,policy_version,recipient,purpose,created_at,expires_at,revoked_at)
               VALUES(?,?,?,1,?,?,?,?,?,NULL)
               ON CONFLICT(user_id,scope) DO UPDATE SET granted=1,policy_version=excluded.policy_version,
               recipient=excluded.recipient,purpose=excluded.purpose,created_at=excluded.created_at,
               expires_at=excluded.expires_at,revoked_at=NULL""",
            (new_id("consent"), user["id"], payload.scope, policy["policy_version"], policy["recipient"], payload.scope, now.isoformat(),
             (now + timedelta(seconds=consent_ttl(payload.scope))).isoformat()))
        row = connection.execute("SELECT * FROM consents WHERE user_id=? AND scope=?", (user["id"], payload.scope)).fetchone()
        fields = {"ai_medical": ["synthetic_question"], "ai_legal": ["synthetic_question"],
                  "vitals": ["measurement_value", "measurement_time", "measurement_source", "symptom_note", "medication_plan", "self_reported_dose", "followup_task"],
                  "records_read": ["record_image", "record_metadata", "ocr_text", "reviewed_fields", "archive_versions", "correction_history"]}[payload.scope]
        if policy["external_network"]:
            fields = fields + ["matched_reference_text"]
        connection.execute("DELETE FROM consent_fields WHERE consent_id=?", (row["id"],))
        connection.executemany("INSERT INTO consent_fields(consent_id,field_name) VALUES(?,?)",
                               [(row["id"], field) for field in fields])
        audit(connection, user["id"], "consent_granted", row["id"])
        return consent_dict(connection, row)


@router.delete("/consents/{scope}")
def revoke_consent(scope: Scope, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as connection:
        connection.execute("UPDATE consents SET granted=0,revoked_at=? WHERE user_id=? AND scope=?",
                           (utcnow().isoformat(), user["id"], scope))
        audit(connection, user["id"], "consent_revoked", scope)
    return {"scope": scope, "granted": False, "effective": "immediate_next_request",
            "notice": "撤回阻断后续请求；进行中结果不再保存或返回。已发往外部模型的内容无法收回，已存本机历史不会自动删除。"}


@router.post("/conversations", status_code=201)
def create_conversation(payload: ConversationInput, user=Depends(patient), database: Database = Depends(get_database), provider=Depends(get_ai_provider)):
    with database.transaction(write=True) as connection:
        require_consent(connection, user["id"], f"ai_{payload.domain}", consent_policy(f"ai_{payload.domain}", provider))
        cid = new_id("chat")
        connection.execute("INSERT INTO conversations(id,user_id,domain,created_at) VALUES(?,?,?,?)",
                           (cid, user["id"], payload.domain, utcnow().isoformat()))
        audit(connection, user["id"], "conversation_created", cid)
        return conversation_dict(connection, connection.execute("SELECT * FROM conversations WHERE id=? AND user_id=?", (cid, user["id"])).fetchone())


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user=Depends(patient), database: Database = Depends(get_database), provider=Depends(get_ai_provider)):
    with database.transaction() as connection:
        row = owned_row(connection.execute("SELECT * FROM conversations WHERE id=? AND user_id=?", (conversation_id, user["id"])).fetchone())
        require_consent(connection, user["id"], f"ai_{row['domain']}", consent_policy(f"ai_{row['domain']}", provider))
        return conversation_dict(connection, row)


@router.post("/conversations/{conversation_id}/messages")
def send_message(conversation_id: str, payload: MessageInput, request: Request,
                 user=Depends(patient), database: Database = Depends(get_database), provider=Depends(get_ai_provider)):
    knowledge = request.app.state.knowledge_provider
    # Authorize just before dispatch. Never hold a SQLite transaction over network I/O.
    with database.transaction() as connection:
        row = owned_row(connection.execute("SELECT * FROM conversations WHERE id=? AND user_id=?", (conversation_id, user["id"])).fetchone())
        domain = row["domain"]
        scope = f"ai_{domain}"
        policy = consent_policy(scope, provider)
        authorization = require_consent(connection, user["id"], scope, policy)
        # M05 local branches: visit questions and record completeness. Neither
        # calls an external model; both run under the current request's consent.
        care_result = answer_visit_question(connection, user["id"], payload.text) if domain == "medical" else None
        checklist_result = (answer_record_checklist(connection, user["id"], payload.text)
                            if domain == "medical" and care_result is None else None)
        medical_plan = (medical_agent.plan(payload.text)
                        if domain == "medical" and care_result is None and checklist_result is None
                        else None)
        boundary_result = (medical_agent.boundary_answer(connection, payload.text, medical_plan)
                           if medical_plan is not None else None)
        legal_plan = legal_agent.plan(payload.text) if domain == "legal" else None
        legal_result = (legal_agent.answer(connection, payload.text)
                        if legal_plan is not None else None)
        # Greetings and thanks are answered locally, after every safety branch,
        # so "你好，我突然胸痛" still hits the crisis path below.
        chitchat_result = (smalltalk(domain, payload.text)
                           if care_result is None and checklist_result is None
                           and boundary_result is None and legal_result is None
                           else None)
    if care_result is not None:
        result = medical_agent.decorate(care_result, payload.text) if domain == "medical" else care_result
    elif checklist_result is not None:
        result = medical_agent.decorate(checklist_result, payload.text) if domain == "medical" else checklist_result
    elif boundary_result is not None:
        result = boundary_result
    elif legal_result is not None:
        result = legal_result
    elif chitchat_result is not None:
        # No topic block and no suggestion chips: a greeting should just read
        # like a person answering, not like a knowledge-base result page.
        result = chitchat_result
    else:
        try:
            # Local knowledge is short and transactional; the optional legal MCP is
            # called outside any SQLite transaction and receives only the question.
            with (database.transaction() if knowledge.uses_database(domain) else nullcontext()) as context_connection:
                context = knowledge.search(context_connection, domain, payload.text,
                                           limit=3 if domain in ("medical", "legal") else 2)
            result = respond(domain, payload.text, provider=provider, context=context,
                             retrieval=knowledge.mode(domain))
            if domain == "medical":
                result = medical_agent.enrich(result, payload.text)
            elif domain == "legal":
                result = legal_agent.enrich(result, payload.text)
        except KnowledgeProviderError as error:
            if not legal_mcp_fallback_enabled():
                logger.warning("legal_mcp_failed action=503 error=%s", type(error).__name__)
                raise HTTPException(503, str(error)) from None
            # Opt-in degradation: the external statute library is down, so this
            # turn is answered from the small local corpus and says so, instead of
            # failing the whole conversation.
            logger.warning("legal_mcp_failed action=local_fallback error=%s",
                           type(error).__name__)
            with database.transaction() as fallback_connection:
                context = LocalKnowledgeProvider().search(
                    fallback_connection, domain, payload.text, limit=2)
            result = respond(domain, payload.text, provider=provider, context=context,
                             retrieval="sqlite_keyword_v1_fallback")
            result["fallback_notice"] = "外部法规库暂不可用，本条回答只基于本地演示资料。"
            if domain == "medical":
                result = medical_agent.enrich(result, payload.text)
            else:
                result = legal_agent.enrich(result, payload.text)
        except ProviderError as error:
            raise HTTPException(error.status_code, error.safe_message) from None
    with database.transaction(write=True) as connection:
        # Regrant also invalidates an in-flight request, even after a revoke/regrant cycle.
        if require_consent(connection, user["id"], scope, policy) != authorization:
            raise HTTPException(403, "请求期间授权已变化，回复未保存；请重新确认后再提问")
        result.update({"role": "assistant",
                       "disclaimer": DISCLAIMER_LEGAL if domain == "legal" else DISCLAIMER})
        for removed in ("sources", "followups", "doctor_questions"):
            result.pop(removed, None)
        now = utcnow().isoformat()
        connection.execute("INSERT INTO messages(conversation_id,role,text,created_at) VALUES(?,'user',?,?)",
                           (conversation_id, payload.text, now))
        mid = connection.execute(
            "INSERT INTO messages(conversation_id,role,text,provider,retrieval,disclaimer,created_at) VALUES(?,'assistant',?,?,?,?,?)",
            (conversation_id, result["answer"], result["provider"], result["retrieval"], result["disclaimer"], now)).lastrowid
        metadata = {key: result[key] for key in
                    ("category", "topic", "topic_key",
                     "materials", "next_steps", "external_ai")
                    if key in result}
        if metadata:
            connection.execute("INSERT INTO message_metadata(message_id,data) VALUES(?,?)",
                               (mid, json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))))
        audit(connection, user["id"], "conversation_answered", conversation_id)
        return result


@router.get("/records")
def list_records(user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        require_consent(connection, user["id"], "records_read")
        rows = connection.execute("SELECT * FROM medical_records WHERE user_id=? ORDER BY created_at DESC",
                                  (user["id"],)).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/records", status_code=201)
def create_record(payload: RecordCreate, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as connection:
        require_consent(connection, user["id"], "records_read")
        rid = new_id("rec")
        connection.execute(
            "INSERT INTO medical_records(id,user_id,title,summary,record_date,created_at) VALUES(?,?,?,?,?,?)",
            (rid, user["id"], payload.title, payload.summary, payload.record_date, utcnow().isoformat()))
        audit(connection, user["id"], "record_created", rid)
        row = connection.execute("SELECT * FROM medical_records WHERE id=?", (rid,)).fetchone()
        return dict(row)


@router.delete("/records/{record_id}")
def delete_record(record_id: str, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as connection:
        connection.execute("DELETE FROM medical_records WHERE id=? AND user_id=?", (record_id, user["id"]))
        audit(connection, user["id"], "record_deleted", record_id)
    return {"deleted": record_id}


@router.get("/medications")
def medications(user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        require_consent(connection, user["id"], "vitals", consent_policy("vitals", None))
        rows = connection.execute("SELECT * FROM medications WHERE user_id=? ORDER BY scheduled_time,created_at",
                                  (user["id"],)).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/medications", status_code=201)
def create_medication(payload: MedicationCreate, user=Depends(patient), database: Database = Depends(get_database)):
    raise HTTPException(410, "旧版用药录入已停用，请使用健康记录与用药中的计划功能")


@router.delete("/medications/{medication_id}")
def delete_medication(medication_id: str, user=Depends(patient), database: Database = Depends(get_database)):
    raise HTTPException(410, "请在健康记录与用药中删除计划及对应记录")


@router.get("/vitals")
def list_vitals(user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        require_consent(connection, user["id"], "vitals")
        return {"items": [vital_dict(row) for row in connection.execute("SELECT * FROM vitals WHERE user_id=? ORDER BY created_at", (user["id"],))]}


@router.post("/vitals", status_code=201)
def upload_vital(payload: VitalInput, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as connection:
        require_consent(connection, user["id"], "vitals")
        previous = connection.execute("SELECT * FROM vitals WHERE user_id=? AND source=? AND sample_id=?",
                                      (user["id"], payload.source, payload.sample_id)).fetchone()
        if previous:
            result = vital_dict(previous)
            if result["sample"] != payload.model_dump(mode="json"):
                raise HTTPException(409, "同一sample_id不能覆盖不同采样内容")
            return result
        validate_vital(payload)
        alert = alert_for(payload)
        vid = new_id("vital")
        connection.execute(
            """INSERT INTO vitals(id,user_id,sample_id,source,kind,value,unit,measured_at,quality,alert_status,alert_message,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (vid, user["id"], payload.sample_id, payload.source, payload.kind, payload.value, payload.unit,
             payload.model_dump(mode="json")["measured_at"], payload.quality, alert["status"], alert["message"], utcnow().isoformat()))
        audit(connection, user["id"], "vital_received", vid)
        return vital_dict(connection.execute("SELECT * FROM vitals WHERE id=? AND user_id=?", (vid, user["id"])).fetchone())


@router.post("/emergencies", status_code=201)
def create_emergency(payload: EmergencyInput, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as connection:
        previous = connection.execute("SELECT * FROM emergency_events WHERE user_id=? AND idempotency_key=?",
                                      (user["id"], payload.idempotency_key)).fetchone()
        if previous:
            return emergency_dict(previous)
        eid = new_id("sos")
        connection.execute(
            """INSERT INTO emergency_events(id,user_id,idempotency_key,status,delivery,created_at,acknowledged_at,message)
               VALUES(?,?,?,'received','recorded',?,NULL,?)""",
            (eid, user["id"], payload.idempotency_key, utcnow().isoformat(),
             "紧急呼叫已记录，请立即前往护士站或拨打病区呼叫电话。"))
        audit(connection, user["id"], "emergency_demo_received", eid)
        return emergency_dict(connection.execute("SELECT * FROM emergency_events WHERE id=? AND user_id=?", (eid, user["id"])).fetchone())


@router.get("/emergencies/{event_id}")
def get_emergency(event_id: str, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        return emergency_dict(owned_row(connection.execute("SELECT * FROM emergency_events WHERE id=? AND user_id=?", (event_id, user["id"])).fetchone()))


@router.get("/audit-events")
def audit_events(user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        return {"items": [dict(row) for row in connection.execute(
            "SELECT id,user_id,action,object_id,created_at FROM audit_events WHERE user_id=? ORDER BY created_at", (user["id"],))],
                "durable": True, "tamper_evident": False}
