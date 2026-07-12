"""Detecção conservadora de dispositivo a partir de headers do Streamlit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class DeviceProfile:
    """Perfil leve do cliente inferido sem depender de JavaScript."""

    is_mobile: bool
    device_type: str
    browser: str
    os: str
    confidence: str
    user_agent: str

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "is_mobile": self.is_mobile,
            "device_type": self.device_type,
            "browser": self.browser,
            "os": self.os,
            "confidence": self.confidence,
            "user_agent": self.user_agent,
        }


def _header_get(headers: Mapping[str, str] | None, key: str) -> str:
    if not headers:
        return ""
    try:
        value = headers.get(key)  # type: ignore[attr-defined]
        if value is not None:
            return str(value)
    except Exception:
        pass

    key_lower = key.lower()
    try:
        items = headers.items()
    except Exception:
        return ""
    for item_key, item_value in items:
        if str(item_key).lower() == key_lower:
            return str(item_value)
    return ""


def _detect_browser(ua: str) -> str:
    ua_lower = ua.lower()
    if "edgios/" in ua_lower:
        return "edge_ios"
    if "edga/" in ua_lower:
        return "edge_android"
    if "edg/" in ua_lower:
        return "edge"
    if "crios/" in ua_lower:
        return "chrome_ios"
    if "chrome/" in ua_lower or "chromium/" in ua_lower:
        return "chrome"
    if "fxios/" in ua_lower:
        return "firefox_ios"
    if "firefox/" in ua_lower:
        return "firefox"
    if "safari/" in ua_lower and "version/" in ua_lower:
        return "safari"
    if "android" in ua_lower and "version/" in ua_lower and "mobile safari/" in ua_lower:
        return "android_browser"
    return "unknown"


def _detect_os(ua: str) -> str:
    ua_lower = ua.lower()
    if "iphone" in ua_lower or "ipad" in ua_lower or "ipod" in ua_lower:
        return "ios"
    if "android" in ua_lower:
        return "android"
    if "windows phone" in ua_lower:
        return "windows_phone"
    if "mac os x" in ua_lower or "macintosh" in ua_lower:
        return "macos"
    if "windows nt" in ua_lower:
        return "windows"
    if "linux" in ua_lower:
        return "linux"
    return "unknown"


def detect_device_from_headers(headers: Mapping[str, str] | None) -> DeviceProfile:
    """Infere mobile/tablet/desktop a partir dos headers disponíveis.

    A detecção é intencionalmente conservadora: quando o user-agent é ambíguo
    (caso clássico do Safari em iPadOS anunciando macOS), retornamos desktop
    com baixa confiança em vez de forçar um roteamento incorreto.
    """

    ua = _header_get(headers, "user-agent").strip()
    sec_ch_mobile = _header_get(headers, "sec-ch-ua-mobile").strip().lower()
    ua_lower = ua.lower()

    browser = _detect_browser(ua)
    os_name = _detect_os(ua)

    explicit_tablet = "ipad" in ua_lower or "tablet" in ua_lower
    explicit_phone = any(
        marker in ua_lower
        for marker in (
            "iphone",
            "ipod",
            "windows phone",
            "mobile safari",
            "mobile/",
            "opera mini",
            "opera mobi",
        )
    )
    android = "android" in ua_lower
    android_mobile = android and ("mobile" in ua_lower or sec_ch_mobile == "?1")
    android_tablet = android and not android_mobile

    if explicit_tablet or android_tablet:
        return DeviceProfile(
            is_mobile=True,
            device_type="tablet",
            browser=browser,
            os=os_name,
            confidence="high",
            user_agent=ua,
        )

    if explicit_phone or android_mobile or sec_ch_mobile == "?1":
        return DeviceProfile(
            is_mobile=True,
            device_type="phone",
            browser=browser,
            os=os_name,
            confidence="high" if ua else "medium",
            user_agent=ua,
        )

    if not ua:
        return DeviceProfile(
            is_mobile=False,
            device_type="unknown",
            browser="unknown",
            os="unknown",
            confidence="unknown",
            user_agent="",
        )

    confidence = "low" if ("macintosh" in ua_lower and "safari/" in ua_lower) else "medium"
    return DeviceProfile(
        is_mobile=False,
        device_type="desktop",
        browser=browser,
        os=os_name,
        confidence=confidence,
        user_agent=ua,
    )
