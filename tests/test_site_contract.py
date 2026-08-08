from pathlib import Path


ROOT = Path(__file__).parents[1]
PAGES = {
    "index.html": ("en", "https://agentmesh360.com/app/#pricing"),
    "zh/index.html": ("zh-CN", "https://agentmesh360.com/app/?lang=zh-CN#pricing"),
    "en/index.html": ("en", "https://agentmesh360.com/app/#pricing"),
    "ja/index.html": ("ja", "https://agentmesh360.com/app/?lang=ja#pricing"),
    "ko/index.html": ("ko", "https://agentmesh360.com/app/?lang=ko#pricing"),
}


def test_localized_sites_offer_an_optional_agentmesh360_pass() -> None:
    for relative, (language, pricing_url) in PAGES.items():
        page = (ROOT / "site" / relative).read_text(encoding="utf-8")
        assert f'<html lang="{language}"' in page
        assert pricing_url in page
        assert "data-purchase-cta" in page
        assert 'class="btn btn-primary" data-purchase-cta' in page
        assert (
            'href="https://github.com/jiyangnan/AgentMesh-Runtime" '
            'class="btn btn-ghost"'
        ) in page
        assert ".nav-cta{font-size:14px;background:transparent" in page
        assert "pass-note" in page


def test_pass_copy_preserves_the_local_free_runtime_boundary() -> None:
    localized_boundary_copy = {
        "index.html": "Runtime stays free, local, and account-free",
        "zh/index.html": "Runtime 本地免费且无需账户",
        "en/index.html": "Runtime stays free, local, and account-free",
        "ja/index.html": "Runtime はローカルで無料、アカウント不要",
        "ko/index.html": "Runtime은 로컬에서 무료로 실행되며 계정이 필요하지 않습니다",
    }
    for relative, expected in localized_boundary_copy.items():
        page = (ROOT / "site" / relative).read_text(encoding="utf-8")
        assert expected in page


def test_runtime_site_links_and_indexes_memory_and_recovery_guides() -> None:
    routes = (
        "/guides/ai-agent-memory/",
        "/guides/agent-crash-recovery/",
    )
    landing = (ROOT / "site" / "zh" / "index.html").read_text(encoding="utf-8")
    sitemap = (ROOT / "site" / "sitemap.xml").read_text(encoding="utf-8")

    for route in routes:
        source = (
            ROOT / "site" / route.strip("/") / "index.html"
        ).read_text(encoding="utf-8")
        canonical = f"https://runtime.agentmesh360.com{route}"
        assert f'href="{route}"' in landing
        assert f'rel="canonical" href="{canonical}"' in source
        assert 'type="application/ld+json"' in source
        assert f"<loc>{canonical}</loc>" in sitemap
