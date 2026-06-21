from scripts.update_data import build_selected_universe, filter_regions_for_market


def test_selected_market_universe_excludes_empty_markets():
    regions = {"us": ["aapl"], "cn": ["000001"], "hk": ["00700.HK"]}

    filtered = filter_regions_for_market(regions, "us")

    assert build_selected_universe(filtered) == {"us": ["AAPL"]}
