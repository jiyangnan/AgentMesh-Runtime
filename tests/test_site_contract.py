from pathlib import Path


ROOT = Path(__file__).parents[1]
PAGES = ("index.html", "en/index.html", "ja/index.html", "ko/index.html")
PRICING_URL = "https://agentmesh360.com/app/#pricing"


def test_localized_sites_offer_an_optional_agentmesh360_pass() -> None:
    for relative in PAGES:
        page = (ROOT / "site" / relative).read_text(encoding="utf-8")
        assert PRICING_URL in page
        assert "data-purchase-cta" in page
        assert 'class="btn btn-primary" data-purchase-cta' in page
        assert (
            'href="https://github.com/jiyangnan/AgentMesh-Runtime" '
            'class="btn btn-ghost"'
        ) in page
        assert ".nav-cta{font-size:14px;background:transparent" in page
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


def test_runtime_site_links_and_indexes_memory_and_recovery_guides() -> None:
    routes = (
        "/guides/ai-agent-memory/",
        "/guides/agent-crash-recovery/",
    )
    landing = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
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
