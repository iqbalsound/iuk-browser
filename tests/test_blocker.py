import json
import time

import pytest

from iuk_browser.core.blocker import Blocker, parse_rule, registrable
from iuk_browser.ui.web import ProfileManager, WebView
from iuk_browser.core.settings import Settings
from webhelpers import js, load, wait_until


def mk(text, **kw):
    b = Blocker(); b.load_text(text)
    for k, v in kw.items():
        setattr(b, k, v)
    return b


def test_rule_parsing_accepts_the_common_syntax_and_skips_the_rest():
    assert parse_rule("||ads.example.com^").pattern == "ads.example.com"
    r = parse_rule("@@||cdn.example.com^$script,third-party")
    assert r.exception and r.third_party is True and r.types == frozenset({"script"})
    assert parse_rule("||example.com/banners/").path == "/banners/"
    assert parse_rule("/banner/ad-").pattern == "/banner/ad-"
    for skipped in ["! comment", "[Adblock Plus 2.0]", "example.com##.ad-box", "example.com#@#.x", "||ads.example.com^$domain=a.com",
                    "||x.example.com^$redirect=noop.js", "/ads?id=\\d+/", "||a.com^*/b", "|http://x.com/", "ab", "", "||b.com^$popup"]:
        assert parse_rule(skipped) is None, skipped


def test_matching_domain_subdomain_options_and_exceptions():
    b = mk("||tracker.test^\n||ads.net^$third-party,script\n||cdn.test^\n@@||cdn.test/allowed/\n/promo/banner-")
    assert b.should_block("https://tracker.test/p.gif", "news.org", "image")
    assert b.should_block("https://sub.deep.tracker.test/p.gif", "news.org", "image")          # subdomains match
    assert not b.should_block("https://nottracker.test/p.gif", "news.org", "image")           # look-alike host does not
    assert b.should_block("https://ads.net/x.js", "news.org", "script")
    assert not b.should_block("https://ads.net/x.png", "news.org", "image")                   # type option
    assert not b.should_block("https://ads.net/x.js", "www.ads.net", "script")                # first-party use is fine
    assert b.should_block("https://cdn.test/other/x.js", "news.org", "script")
    assert not b.should_block("https://cdn.test/allowed/x.js", "news.org", "script")          # exception rule wins
    assert b.should_block("https://shop.org/promo/banner-1.png", "shop.org", "image")         # substring rule
    assert not b.should_block("https://shop.org/promo/other.png", "shop.org", "image")
    assert not b.should_block("data:image/png;base64,AAAA", "x.org", "image") and not b.should_block("not a url", "x.org")


def test_site_allowlist_disabled_state_and_empty_list():
    b = mk("||tracker.test^")
    b.allow_sites = {"news.org"}
    assert not b.should_block("https://tracker.test/p", "www.news.org", "image")             # allowed on news.org and subdomains
    assert b.should_block("https://tracker.test/p", "other.org", "image")
    b.enabled = False
    assert not b.should_block("https://tracker.test/p", "other.org", "image")
    assert not Blocker().should_block("https://tracker.test/p", "other.org", "image")


def test_registrable_domain_heuristic():
    assert registrable("a.b.example.com") == "example.com" and registrable("example.com") == "example.com"
    assert registrable("news.bbc.co.uk") == "bbc.co.uk" and registrable("x.example.com.au") == "example.com.au"


def test_large_lists_stay_fast():
    text = "\n".join(f"||host{i}.tracker{i % 50}.test^" for i in range(60000))
    b = Blocker(); t = time.time(); n = b.load_text(text); load_s = time.time() - t
    assert n == 60000 and load_s < 5
    t = time.time()
    hits = sum(b.should_block(f"https://host{i}.tracker{i % 50}.test/x", "news.org", "script") for i in range(2000))
    assert hits == 2000 and time.time() - t < 1.0


def test_the_bundled_starter_list_loads_and_blocks_known_trackers():
    from iuk_browser.ui.web import BLOCKLIST_DIR
    b = Blocker(); assert b.load_file(BLOCKLIST_DIR / "iuk-basic.txt") > 40
    assert b.should_block("https://www.googletagmanager.com/gtm.js", "news.org", "script")
    assert b.should_block("https://securepubads.g.doubleclick.net/x", "news.org", "script")
    assert not b.should_block("https://www.wikipedia.org/", "news.org", "subdocument")


# ------------------------------------------------------------------ real WebEngine
@pytest.fixture
def pm(qapp, tmp_path):
    return ProfileManager(tmp_path / "data", Settings(tmp_path / "s.json"), qapp)


def loaded_flags(v):
    return json.loads(js(v, "JSON.stringify([document.getElementById('t').complete ? document.getElementById('t').naturalWidth : -1, document.getElementById('own').naturalWidth])"))


def test_third_party_images_are_blocked_but_the_sites_own_resources_and_navigation_are_not(pm, site, qtbot, tmp_path):
    lst = tmp_path / "extra.txt"; lst.write_text("||localhost^$third-party,image\n")
    pm.reload_blocker({"enabled": True, "allow_sites": [], "extra_lists": [str(lst)]})
    v = WebView(pm.normal); qtbot.addWidget(v)
    load(v, site.base + "/tracked")
    assert wait_until(lambda: js(v, "document.getElementById('own').complete && document.getElementById('t').complete"), 12000)
    assert loaded_flags(v) == [0, 1]                                                    # tracker image blocked, own image loaded
    assert pm.blocker.blocked.get("127.0.0.1") == 1
    v2 = WebView(pm.normal); qtbot.addWidget(v2)
    load(v2, site.base.replace("127.0.0.1", "localhost") + "/plain")                   # the same host as a PAGE is never blocked
    assert js(v2, "document.title") == "Plain"


def test_disabling_and_per_site_allow_take_effect(pm, site, qtbot, tmp_path):
    lst = tmp_path / "extra.txt"; lst.write_text("||localhost^$third-party,image\n")
    for cfg, expect in [({"enabled": False, "allow_sites": [], "extra_lists": [str(lst)]}, 1),
                        ({"enabled": True, "allow_sites": ["127.0.0.1"], "extra_lists": [str(lst)]}, 1),
                        ({"enabled": True, "allow_sites": [], "extra_lists": [str(lst)]}, 0)]:
        pm.reload_blocker(cfg)
        v = WebView(pm.normal); qtbot.addWidget(v)
        load(v, site.base + "/tracked")
        assert wait_until(lambda: js(v, "document.getElementById('own').complete && document.getElementById('t').complete"), 12000)
        assert loaded_flags(v)[0] == expect, cfg


def test_menu_toggles_and_counter_in_a_real_window(qapp, tmp_path, site, qtbot):
    from iuk_browser.app import AppContext
    ctx = AppContext(qapp, tmp_path / "p")
    lst = tmp_path / "extra.txt"; lst.write_text("||localhost^$third-party,image\n")
    ctx.apply_settings({"blocker": {"enabled": True, "allow_sites": [], "extra_lists": [str(lst)]}})
    w = ctx.new_window(urls=[site.base + "/tracked"]); qtbot.addWidget(w)
    assert wait_until(lambda: w.current().title() == "Tracked", 15000)
    assert wait_until(lambda: "1 blocked" in (w._update_block_label() or w.block_label.text()), 8000)
    assert w.a_block.isChecked()
    w.a_block.trigger()                                                                 # menu: turn blocking off
    assert ctx.settings["blocker"]["enabled"] is False and not ctx.profiles.blocker.enabled
    w.a_block.trigger()
    w.a_allow_site.trigger()                                                            # menu: allow on this site (reloads)
    assert ctx.settings["blocker"]["allow_sites"] == ["127.0.0.1"]
    assert wait_until(lambda: loaded_flags(w.current())[0] == 1, 10000)
    ctx.clipboard.clear_now()
