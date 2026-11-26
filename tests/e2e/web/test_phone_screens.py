"""The website at phone size, on WebKit (iPhone) and Chromium (Android): right to left, nothing
wider than the screen, the main paths work, and what a guest may and may not use.

The app is web-only for now (people add it to the home screen), so these stand in for phone tests.

    docker compose up -d db redis                              # the local database, loaded
    cd mobile && npm run build:web && cd ..                    # the website, into mobile/dist
    PHARMAVIQUE_WEB_DIR=mobile/dist uv run uvicorn pharmavique.bootstrap.api:create_app --factory
    uv run --extra scraper playwright install webkit chromium  # once
    PHARMAVIQUE_E2E_URL=http://127.0.0.1:8000 uv run --extra scraper pytest tests/e2e/web

The tests only read: they never sign in, register or write anything, so they may also point at the
live site. Without `PHARMAVIQUE_E2E_URL`, or without Playwright installed, they are skipped.
"""

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest

BASE_URL = os.environ.get("PHARMAVIQUE_E2E_URL", "").rstrip("/")
ROLE_KEY = "pharmavique.role.v1"  # mobile/src/state/role.ts

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not BASE_URL, reason="set PHARMAVIQUE_E2E_URL to run the phone-size browser tests"
    ),
]


@dataclass(frozen=True)
class Phone:
    name: str
    engine: str  # Playwright browser type
    device: str  # Playwright device descriptor name


PHONES = [
    Phone("iphone", "webkit", "iPhone 13"),
    Phone("android", "chromium", "Pixel 5"),
]


@pytest.fixture(scope="session")
def playwright() -> Iterator[Any]:
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        yield p


@dataclass
class PhoneBrowser:
    phone: Phone
    browser: Any
    descriptor: dict[str, Any]


@pytest.fixture(scope="session", params=PHONES, ids=lambda phone: phone.name)
def phone_browser(request: pytest.FixtureRequest, playwright: Any) -> Iterator[PhoneBrowser]:
    phone: Phone = request.param
    descriptor = dict(playwright.devices[phone.device])
    descriptor.pop("default_browser_type", None)
    browser = getattr(playwright, phone.engine).launch()
    yield PhoneBrowser(phone, browser, descriptor)
    browser.close()


def _new_page(phone_browser: PhoneBrowser, role: str | None) -> tuple[Any, Any, list[str]]:
    context = phone_browser.browser.new_context(
        **phone_browser.descriptor, locale="ar-SA", base_url=BASE_URL
    )
    if role is not None:
        context.add_init_script(f"localStorage.setItem('{ROLE_KEY}', '{role}')")
    page = context.new_page()
    page.set_default_timeout(20_000)
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    return context, page, errors


@pytest.fixture
def page(phone_browser: PhoneBrowser) -> Iterator[Any]:
    """A fresh phone page as a returning patient: the role is chosen, nobody is signed in."""
    context, page, errors = _new_page(phone_browser, "patient")
    yield page
    context.close()
    assert not errors, f"script errors on the page: {errors}"


@pytest.fixture
def first_visit(phone_browser: PhoneBrowser) -> Iterator[Any]:
    """A fresh phone page with nothing stored: the very first visit."""
    context, page, errors = _new_page(phone_browser, None)
    yield page
    context.close()
    assert not errors, f"script errors on the page: {errors}"


DISCLAIMER = "معلومات للاطلاع فقط وليست نصيحة طبية"  # mobile/src/theme.ts
TABS = ["الرئيسية", "بحث", "المسح الضوئي", "أدويتي", "حسابي"]  # mobile/src/components/TabBar.tsx

# Visible elements that stick out of the screen sideways, outside any sideways-scrolling list.
_OVERFLOW_JS = """() => {
  const width = window.innerWidth;
  const scrollsSideways = (el) => {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const s = getComputedStyle(p);
      if ((s.overflowX === 'auto' || s.overflowX === 'scroll') && p.scrollWidth > p.clientWidth) {
        return true;
      }
    }
    return false;
  };
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el.children.length > 0 && !el.matches('input, textarea, button, [role=button]')) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || Number(s.opacity) === 0) continue;
    if ((r.right > width + 1 || r.left < -1) && !scrollsSideways(el)) {
      const text = (el.textContent || '').trim().slice(0, 40);
      out.push(`${el.tagName} "${text}" ${Math.round(r.left)}..${Math.round(r.right)}`);
    }
  }
  return {pageWidth: document.documentElement.scrollWidth, width, out: out.slice(0, 10)};
}"""


def assert_fits_the_screen(page: Any) -> None:
    result = page.evaluate(_OVERFLOW_JS)
    assert result["pageWidth"] <= result["width"], f"page scrolls sideways: {result}"
    assert not result["out"], f"elements wider than the screen: {result['out']}"


def assert_right_to_left(page: Any, *starts: Any) -> None:
    """Arabic, laid out from the right: the tabs run from the right edge (home first) and each of
    `starts` (a heading or the first item of a row) ends at the right edge of the screen. Checked on
    the drawn boxes, not on `dir`: a `dir="rtl"` page mirrored the app's rows back to the left."""
    assert page.locator("html").get_attribute("lang") == "ar"
    width = page.viewport_size["width"]
    tabs = [page.get_by_role("tab", name=name).filter(visible=True) for name in TABS]
    if all(tab.count() for tab in tabs):
        lefts = [tab.first.bounding_box()["x"] for tab in tabs]
        assert lefts == sorted(lefts, reverse=True), f"tabs do not start from the right: {lefts}"
    for start in starts:
        box = start.bounding_box()
        assert box is not None
        gap = width - (box["x"] + box["width"])
        assert 0 <= gap <= 40, f"{start} ends {gap:.0f} px from the right edge"


def test_first_visit_asks_who_uses_the_app(first_visit: Any) -> None:
    first_visit.goto("/")

    heading = first_visit.get_by_text("من يستخدم التطبيق؟")
    heading.wait_for()
    assert_right_to_left(first_visit, heading)
    assert_fits_the_screen(first_visit)
    for role in ("مريض", "صيدلي", "صاحب شركة أو مخزن أدوية"):
        # a screen reader must read each choice: the button has the role's name
        assert first_visit.get_by_role("button", name=re.compile(role)).count() == 1


def test_choosing_patient_opens_the_home_screen(first_visit: Any) -> None:
    first_visit.goto("/")
    first_visit.get_by_text("مريض", exact=True).click()

    first_visit.get_by_role("tab", name="الرئيسية").filter(visible=True).first.wait_for()
    first_visit.get_by_text(DISCLAIMER, exact=False).filter(visible=True).first.wait_for()
    assert_fits_the_screen(first_visit)


def test_every_tab_opens_and_fits_the_screen(page: Any) -> None:
    page.goto("/")
    viewport = page.viewport_size
    for name in TABS:
        page.get_by_role("tab", name=name).filter(visible=True).first.click()
        page.wait_for_load_state("networkidle")
        # the screen that opened has its own tab bar: measure the tab there, once it is shown
        tab = page.get_by_role("tab", name=name, selected=True).filter(visible=True).first
        tab.wait_for()
        box = tab.bounding_box()
        assert box is not None, f"{name} tab is not on the screen"
        # the tab bar sits on the screen and each tab is big enough for a thumb
        assert box["y"] + box["height"] <= viewport["height"] + 1, name
        assert box["height"] >= 44, f"{name} tab is {box['height']} px tall"
        assert_right_to_left(page)
        assert_fits_the_screen(page)


def test_search_finds_a_drug_and_opens_its_page(page: Any) -> None:
    page.goto("/search")
    box = page.get_by_placeholder("ابحث بالاسم أو المادة الفعالة")
    box.fill("panadol")
    box.press("Enter")

    page.get_by_text(re.compile(r"\d+ نتيجة")).wait_for()
    hit = page.get_by_text(re.compile("^بانادول")).filter(visible=True).first
    hit.wait_for()
    assert_fits_the_screen(page)
    hit.click()

    page.wait_for_url(re.compile(r"/drug/\w+"))
    page.get_by_text(DISCLAIMER, exact=False).filter(visible=True).first.wait_for()
    # the SFDA trust grade on the drug page (mobile/src/app/drug/[register].tsx)
    grade = page.get_by_text("بيانات رسمية من هيئة الغذاء والدواء").filter(visible=True)
    grade.wait_for()
    name = page.get_by_text(re.compile("^بانادول")).filter(visible=True).first
    register = page.get_by_text("رقم التسجيل:").filter(visible=True).first
    assert_right_to_left(page, name, register)
    # the main button ("save to my list") is the right-most of the bottom buttons
    save = page.get_by_role("button", name=re.compile("حفظ")).filter(visible=True).first
    share = page.get_by_role("button", name="مشاركة").filter(visible=True).first
    assert save.bounding_box()["x"] > share.bounding_box()["x"]
    assert_fits_the_screen(page)


def test_typing_in_search_does_not_zoom_the_iphone(page: Any) -> None:
    """iOS Safari zooms into any text box whose font is under 16 px and leaves the page zoomed."""
    page.goto("/search")
    box = page.get_by_placeholder("ابحث بالاسم أو المادة الفعالة")
    box.wait_for()

    size = box.evaluate("el => parseFloat(getComputedStyle(el).fontSize)")
    assert size >= 16, f"search box font is {size} px"


@pytest.mark.parametrize("path", ["/assistant", "/scan", "/voice"])
def test_a_guest_is_asked_to_sign_in_for_the_model_screens(page: Any, path: str) -> None:
    page.goto(path)

    page.get_by_text("سجّل دخولك أول").filter(visible=True).wait_for()
    page.get_by_role("button", name="تسجيل الدخول").filter(visible=True).wait_for()
    assert_fits_the_screen(page)


def test_the_sources_page_shows_the_trust_grades(page: Any) -> None:
    page.goto("/sources")

    page.get_by_text("رسمي سعودي").filter(visible=True).first.wait_for()
    assert page.get_by_text("مرجع رسمي أجنبي").count() >= 1
    assert_right_to_left(page)
    assert_fits_the_screen(page)


def test_a_dead_share_link_says_the_conversation_is_gone(first_visit: Any) -> None:
    """A shared conversation opens for anyone, with no role chosen and nobody signed in; one that
    was deleted or no longer shared says so instead of an error."""
    first_visit.goto("/shared/no-such-link")

    first_visit.get_by_text("هالمحادثة ما عادت موجودة").filter(visible=True).wait_for()
    assert "/role" not in first_visit.url  # not sent to the role screen first
    first_visit.get_by_text(DISCLAIMER, exact=False).filter(visible=True).first.wait_for()
    assert_fits_the_screen(first_visit)


def test_the_forgot_password_screen_opens_from_sign_in_and_fits_the_phone(page: Any) -> None:
    """Reading only: the link is there, the screen asks for the email and nothing is sent."""
    page.goto("/sign-in")

    page.get_by_text("نسيت كلمة المرور؟").filter(visible=True).click()

    intro = page.get_by_text("اكتب إيميل حسابك").filter(visible=True)
    intro.wait_for()
    email = page.get_by_placeholder("الإيميل").filter(visible=True)
    email.wait_for()
    page.get_by_role("button", name="أرسل الرمز").filter(visible=True).wait_for()
    size = email.evaluate("el => parseFloat(getComputedStyle(el).fontSize)")
    assert size >= 16, f"email box font is {size} px, so an iPhone would zoom into it"
    assert_right_to_left(page, intro)
    assert_fits_the_screen(page)
