from utils.ifdata_cache.availability import (
    api_period_to_display,
    describe_support_window,
    display_period_to_api,
    filter_supported_periods,
    is_period_supported,
)


def test_display_period_to_api_supports_quarters():
    assert display_period_to_api("1/2025") == "202503"
    assert display_period_to_api("2/2025") == "202506"
    assert display_period_to_api("3/2025") == "202509"
    assert display_period_to_api("4/2025") == "202512"


def test_filter_supported_periods_respects_carteira_floor():
    suportados, ignorados = filter_supported_periods(
        "carteira_pf",
        ["201503", "202412", "202503", "202506"],
    )
    assert suportados == ["202503", "202506"]
    assert ignorados == ["201503", "202412"]
    assert is_period_supported("carteira_pf", "1/2025")
    assert not is_period_supported("carteira_pf", "202412")


def test_support_window_description_is_human_readable():
    assert api_period_to_display("202503") == "1/2025"
    assert describe_support_window("carteira_instrumentos") == "disponível a partir de 1/2025 (202503)"
