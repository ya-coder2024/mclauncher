# -*- coding: utf-8 -*-
"""账号认证：离线登录 / Yggdrasil 外置登录（LittleSkin 等皮肤站）/ 微软正版登录。

- 离线登录：本地生成玩家名与离线 UUID，无需联网。
- 外置登录：Yggdrasil 协议（authenticate / refresh / validate），
  默认皮肤站 LittleSkin，也支持任意自定义 apiRoot。
- 正版登录：微软设备码（Device Code）流程：
  Microsoft → Xbox Live → XSTS → Minecraft Services → 玩家资料。

账号持久化于 .minecraft/accounts.json。
"""

import json
import time
import uuid as uuidlib
from pathlib import Path

import requests

# ---------------- 常量 ----------------

LITTLESKIN_API = "https://littleskin.cn/api/yggdrasil"
SKIN_SITE_PRESETS = [
    ("LittleSkin", LITTLESKIN_API),
]

# 微软 OAuth：沿用 mcauth3 内置的公开客户端 ID（设备码流程，无客户端密钥）。
MS_CLIENT_ID = "4a07b708-b86d-4365-a55f-f4f23ecb85ab"
MS_SCOPE = "XboxLive.signin offline_access openid profile email"
DEVICE_CODE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
XBL_AUTH_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_AUTH_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_LOGIN_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"

TIMEOUT = 30

XSTS_ERROR_MESSAGES = {
    2148916233: "该微软账号没有 Xbox 档案，请先在 xbox.com 注册",
    2148916235: "该账号被 Xbox Live 封禁",
    2148916236: "该账号需要成人验证",
    2148916238: "该账号未满 18 岁，需要家长同意",
}


class AuthError(Exception):
    """认证失败（信息直接展示给用户）"""


# ---------------- 工具 ----------------

def _dashed(uuid32):
    try:
        return str(uuidlib.UUID(uuid32))
    except Exception:
        return uuid32


def offline_uuid(name):
    """离线 UUID：MD5("OfflinePlayer:" + name)，v3 格式"""
    import hashlib
    b = bytearray(hashlib.md5(("OfflinePlayer:" + name).encode("utf-8")).digest())
    b[6] = (b[6] & 0x0F) | 0x30
    b[8] = (b[8] & 0x3F) | 0x80
    return str(uuidlib.UUID(bytes=bytes(b)))


# ---------------- 离线登录 ----------------

def offline_login(name):
    name = (name or "").strip()
    if not name:
        raise AuthError("请输入玩家昵称")
    if len(name) > 16:
        raise AuthError("昵称不能超过 16 个字符")
    return {
        "type": "offline",
        "name": name,
        "uuid": offline_uuid(name),
        "access_token": "0",
    }


# ---------------- Yggdrasil 外置登录 ----------------

def _yg_post(api_root, path, body):
    url = api_root.rstrip("/") + path
    try:
        r = requests.post(url, json=body, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise AuthError(f"无法连接皮肤站：{e}")
    return r


def yggdrasil_login(api_root, username, password):
    api_root = (api_root or "").strip().rstrip("/")
    username = (username or "").strip()
    password = password or ""
    if not api_root.startswith("http"):
        raise AuthError("请填写皮肤站地址（http(s):// 开头）")
    if not username or not password:
        raise AuthError("请填写账号与密码")

    body = {
        "agent": {"name": "Minecraft", "version": 1},
        "username": username,
        "password": password,
        "requestUser": True,
    }
    r = _yg_post(api_root, "/authserver/authenticate", body)
    if r.status_code != 200:
        raise AuthError(_yg_error(r, "登录失败"))

    data = r.json()
    profile = data.get("selectedProfile")
    if not profile:
        raise AuthError("该账号下没有游戏角色，请先在皮肤站添加角色")
    return {
        "type": "yggdrasil",
        "name": profile["name"],
        "uuid": _dashed(profile["id"]),
        "access_token": data["accessToken"],
        "client_token": data.get("clientToken", ""),
        "api_root": api_root,
    }


def yggdrasil_refresh(account):
    """用 clientToken + accessToken 刷新外置登录"""
    r = _yg_post(account["api_root"], "/authserver/refresh", {
        "accessToken": account["access_token"],
        "clientToken": account.get("client_token", ""),
        "requestUser": True,
    })
    if r.status_code == 200:
        data = r.json()
        account["access_token"] = data["accessToken"]
        if data.get("clientToken"):
            account["client_token"] = data["clientToken"]
        profile = data.get("selectedProfile")
        if profile:
            account["name"] = profile["name"]
            account["uuid"] = _dashed(profile["id"])
        return account
    raise AuthError(_yg_error(r, "外置登录已失效，请重新登录"))


def yggdrasil_validate(account):
    """令牌是否仍有效（有效返回 True）"""
    r = _yg_post(account["api_root"], "/authserver/validate",
                 {"accessToken": account["access_token"]})
    return r.status_code == 204


def _yg_error(r, default):
    try:
        msg = r.json().get("errorMessage") or r.json().get("error")
    except Exception:
        msg = None
    return f"{default}（HTTP {r.status_code}）：{msg}" if msg else f"{default}（HTTP {r.status_code}）"


# ---------------- 微软正版登录（设备码流程） ----------------

def microsoft_start():
    """请求设备码，返回 {verification_uri, user_code, device_code, expires_in, interval}"""
    try:
        r = requests.post(DEVICE_CODE_URL, data={
            "client_id": MS_CLIENT_ID,
            "scope": MS_SCOPE,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise AuthError(f"无法连接微软：{e}")
    if r.status_code != 200:
        raise AuthError(f"获取设备码失败（HTTP {r.status_code}）")
    return r.json()


def microsoft_finish(device):
    """轮询等待用户授权，完成后返回账号。阻塞调用。"""
    device_code = device["device_code"]
    interval = max(int(device.get("interval", 5)), 5)
    expires_in = int(device.get("expires_in", 900))
    max_attempts = max(1, int(expires_in / interval))

    token_resp = None
    for _ in range(max_attempts):
        try:
            r = requests.post(TOKEN_URL, data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": MS_CLIENT_ID,
                "device_code": device_code,
            }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=TIMEOUT)
        except requests.RequestException:
            time.sleep(interval)
            continue

        if r.status_code == 200:
            token_resp = r.json()
            break
        err = {}
        try:
            err = r.json()
        except ValueError:
            pass
        code = err.get("error")
        if code in ("authorization_pending", "slow_down"):
            if code == "slow_down":
                interval += 5
            time.sleep(interval)
        else:
            raise AuthError(err.get("error_description") or code or "微软登录失败")
    else:
        raise AuthError("登录超时，请在 15 分钟内完成网页验证")

    return _ms_exchange(token_resp["access_token"],
                        token_resp.get("refresh_token"))


def _ms_exchange(ms_access_token, ms_refresh_token=None):
    """微软令牌 → Xbox Live → XSTS → Minecraft 令牌 → 玩家资料"""
    # 1) Xbox Live（设备码令牌偶尔需要 "d=" 前缀）
    xbl_resp = None
    last_http_err = None
    for ticket in (f"d={ms_access_token}", ms_access_token):
        try:
            r = requests.post(XBL_AUTH_URL, json={
                "Properties": {
                    "AuthMethod": "RPS",
                    "SiteName": "user.auth.xboxlive.com",
                    "RpsTicket": ticket,
                },
                "RelyingParty": "http://auth.xboxlive.com",
                "TokenType": "JWT",
            }, headers={"Accept": "application/json"}, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise AuthError(f"Xbox Live 连接失败：{e}")
        if r.status_code == 200:
            xbl_resp = r.json()
            break
        last_http_err = f"HTTP {r.status_code}"
    if xbl_resp is None:
        raise AuthError(f"Xbox Live 认证失败：{last_http_err}")

    xbl_token = xbl_resp["Token"]
    uhs = xbl_resp["DisplayClaims"]["xui"][0]["uhs"]

    # 2) XSTS
    try:
        r = requests.post(XSTS_AUTH_URL, json={
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
            "RelyingParty": "rp://api.minecraftservices.com/",
            "TokenType": "JWT",
        }, headers={"Accept": "application/json"}, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise AuthError(f"XSTS 连接失败：{e}")
    if r.status_code != 200:
        try:
            xerr = r.json().get("XErr")
        except ValueError:
            xerr = None
        hint = XSTS_ERROR_MESSAGES.get(xerr)
        raise AuthError(hint or f"XSTS 授权失败（{xerr or r.status_code}）")
    xsts_token = r.json()["Token"]

    # 3) Minecraft Services
    try:
        r = requests.post(MC_LOGIN_URL, json={
            "identityToken": f"XBL3.0 xhi={uhs};{xsts_token}"
        }, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise AuthError(f"Minecraft 服务连接失败：{e}")
    if r.status_code != 200:
        raise AuthError(f"Minecraft 登录失败（HTTP {r.status_code}）")
    mc_token = r.json()["access_token"]

    # 4) 玩家资料（404 = 账号未购买游戏）
    try:
        r = requests.get(PROFILE_URL, headers={"Authorization": f"Bearer {mc_token}"},
                         timeout=TIMEOUT)
    except requests.RequestException as e:
        raise AuthError(f"获取玩家资料失败：{e}")
    if r.status_code == 404:
        raise AuthError("该微软账号未拥有 Minecraft：Java 版，请先购买")
    if r.status_code != 200:
        raise AuthError(f"获取玩家资料失败（HTTP {r.status_code}）")
    profile = r.json()
    return {
        "type": "microsoft",
        "name": profile["name"],
        "uuid": _dashed(profile["id"]),
        "access_token": mc_token,
        "refresh_token": ms_refresh_token or "",
    }


def microsoft_refresh(refresh_token):
    """用微软 refresh_token 换新令牌（refresh_token 会轮换）"""
    if not refresh_token:
        raise AuthError("请重新使用正版登录")
    try:
        r = requests.post(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "client_id": MS_CLIENT_ID,
            "refresh_token": refresh_token,
            "scope": MS_SCOPE,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise AuthError(f"微软连接失败：{e}")
    if r.status_code != 200:
        raise AuthError("正版登录已过期，请重新登录")
    data = r.json()
    account = _ms_exchange(data["access_token"],
                           data.get("refresh_token", refresh_token))
    return account


# ---------------- 启动前统一刷新 ----------------

def prepare_account(account):
    """启动前确保令牌可用，返回（可能已更新的）账号。失败抛 AuthError。"""
    t = account["type"]
    if t == "offline":
        return account
    if t == "microsoft":
        return microsoft_refresh(account.get("refresh_token", ""))
    if t == "yggdrasil":
        try:
            if yggdrasil_validate(account):
                return account
        except AuthError:
            pass
        return yggdrasil_refresh(account)
    raise AuthError(f"未知账号类型：{t}")


# ---------------- 账号持久化 ----------------

class AccountStore:
    """accounts.json：账号列表 + 当前选中"""

    def __init__(self, game_dir):
        self._path = Path(game_dir) / "accounts.json"
        self._accounts = []
        self._selected = None
        self._load()

    def _load(self):
        if self._path.is_file():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._accounts = data.get("accounts", [])
                self._selected = data.get("selected")
            except Exception:
                self._accounts, self._selected = [], None

    def save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({
            "accounts": self._accounts,
            "selected": self._selected,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def accounts(self):
        return list(self._accounts)

    def current(self):
        for a in self._accounts:
            if self._key(a) == self._selected:
                return a
        return self._accounts[0] if self._accounts else None

    @staticmethod
    def _key(a):
        return f"{a['type']}:{a['uuid']}"

    def add(self, account, select=True):
        key = self._key(account)
        self._accounts = [a for a in self._accounts if self._key(a) != key]
        self._accounts.insert(0, account)
        if select or self._selected is None:
            self._selected = key
        self.save()

    def select(self, account):
        key = self._key(account)
        if any(self._key(a) == key for a in self._accounts):
            self._selected = key
            self.save()

    def remove(self, account):
        key = self._key(account)
        self._accounts = [a for a in self._accounts if self._key(a) != key]
        if self._selected == key:
            self._selected = self._key(self._accounts[0]) if self._accounts else None
        self.save()
