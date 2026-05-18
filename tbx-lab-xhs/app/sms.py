import hashlib
import hmac
import json
import os
import time
from typing import Any
from urllib import request


TEMPLATE_ENV_KEYS = {
    "verification": "SMS_TEMPLATE_VERIFICATION",
    "order_opened": "SMS_TEMPLATE_ORDER_OPENED",
    "plan_expire_3d": "SMS_TEMPLATE_PLAN_EXPIRE_3D",
    "refund_approved": "SMS_TEMPLATE_REFUND_APPROVED",
}


def sms_enabled() -> bool:
    return os.getenv("SMS_ENABLED", "0").strip() == "1"


def sms_config() -> dict[str, str]:
    return {
        "provider": os.getenv("SMS_PROVIDER", "tencent").strip() or "tencent",
        "app_id": os.getenv("SMS_APP_ID", "").strip(),
        "app_key": os.getenv("SMS_APP_KEY", "").strip(),
        "sign_name": os.getenv("SMS_SIGN_NAME", "").strip(),
        "region": os.getenv("SMS_REGION", "ap-guangzhou").strip() or "ap-guangzhou",
    }


def send_sms(phone: str, template_key: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    if not sms_enabled():
        return {"ok": True, "skipped": True, "provider": "disabled", "template_key": template_key}

    config = sms_config()
    if config["provider"] != "tencent":
        return {"ok": False, "error": f"unsupported provider: {config['provider']}"}

    template_id = os.getenv(TEMPLATE_ENV_KEYS.get(template_key, ""), "").strip()
    if not all([config["app_id"], config["app_key"], config["sign_name"], template_id]):
        return {"ok": False, "error": "missing sms env config", "template_key": template_key}

    return send_tencent_sms(phone, template_id, params, config)


def send_tencent_sms(phone: str, template_id: str, params: dict[str, Any], config: dict[str, str]) -> dict[str, Any]:
    # Minimal Tencent Cloud SMS v3 request. Kept dependency-free so SMS_ENABLED=0 local mode stays light.
    service = "sms"
    host = "sms.tencentcloudapi.com"
    action = "SendSms"
    version = "2021-01-11"
    timestamp = int(time.time())
    date = time.strftime("%Y-%m-%d", time.gmtime(timestamp))
    secret_id = config["app_id"]
    secret_key = config["app_key"]

    payload = {
        "PhoneNumberSet": [f"+86{phone}" if not str(phone).startswith("+") else str(phone)],
        "SmsSdkAppId": os.getenv("SMS_SDK_APP_ID", config["app_id"]).strip(),
        "SignName": config["sign_name"],
        "TemplateId": template_id,
        "TemplateParamSet": [str(value) for value in params.values()],
    }
    body = json.dumps(payload, separators=(",", ":"))
    canonical_headers = f"content-type:application/json; charset=utf-8\nhost:{host}\nx-tc-action:{action.lower()}\n"
    signed_headers = "content-type;host;x-tc-action"
    hashed_request_payload = hashlib.sha256(body.encode("utf-8")).hexdigest()
    canonical_request = "\n".join(["POST", "/", "", canonical_headers, signed_headers, hashed_request_payload])
    credential_scope = f"{date}/{service}/tc3_request"
    hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = "\n".join(["TC3-HMAC-SHA256", str(timestamp), credential_scope, hashed_canonical_request])

    def sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    secret_date = sign(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = sign(secret_date, service)
    secret_signing = sign(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        "TC3-HMAC-SHA256 "
        f"Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    req = request.Request(
        f"https://{host}",
        data=body.encode("utf-8"),
        headers={
            "Authorization": authorization,
            "Content-Type": "application/json; charset=utf-8",
            "Host": host,
            "X-TC-Action": action,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": version,
            "X-TC-Region": config["region"],
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
        return {"ok": True, "provider": "tencent", "response": data}
    except Exception as exc:
        return {"ok": False, "provider": "tencent", "error": str(exc)}
