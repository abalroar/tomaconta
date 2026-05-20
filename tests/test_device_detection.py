from utils.device_detection import detect_device_from_headers


def test_detects_iphone_safari_as_mobile():
    profile = detect_device_from_headers(
        {
            "user-agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
                "Mobile/15E148 Safari/604.1"
            )
        }
    )

    assert profile.is_mobile is True
    assert profile.device_type == "phone"
    assert profile.browser == "safari"
    assert profile.os == "ios"


def test_detects_android_edge_as_mobile():
    profile = detect_device_from_headers(
        {
            "user-agent": (
                "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36 EdgA/124.0.0.0"
            )
        }
    )

    assert profile.is_mobile is True
    assert profile.device_type == "phone"
    assert profile.browser == "edge_android"
    assert profile.os == "android"


def test_keeps_ipados_desktop_user_agent_conservative():
    profile = detect_device_from_headers(
        {
            "user-agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
            )
        }
    )

    assert profile.is_mobile is False
    assert profile.confidence == "low"
    assert profile.browser == "safari"
