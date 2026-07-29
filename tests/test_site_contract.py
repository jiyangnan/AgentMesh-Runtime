from pathlib import Path


ROOT = Path(__file__).parents[1]
PAGES = ("index.html", "en/index.html", "ja/index.html", "ko/index.html")
PRICING_URL = "https://agentmesh360.com/app/#pricing"


def test_localized_sites_offer_an_optional_agentmesh360_pass() -> None:
    for relative in PAGES:
        page = (ROOT / "site" / relative).read_text(encoding="utf-8")
        assert PRICING_URL in page
        assert "data-purchase-cta" in page
        assert "pass-note" in page


def test_pass_copy_preserves_the_local_free_runtime_boundary() -> None:
    localized_boundary_copy = (
        "Runtime 本地免费且无需账户",
        "Runtime stays free, local, and account-free",
        "Runtime はローカルで無料、アカウント不要",
        "Runtime은 로컬에서 무료로 실행되며 계정이 필요하지 않습니다",
    )
    for relative, expected in zip(PAGES, localized_boundary_copy, strict=True):
        page = (ROOT / "site" / relative).read_text(encoding="utf-8")
        assert expected in page
