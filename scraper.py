"""YouTube search scraper (Selenium). Pure logic - no input()/print() and no UI code."""
from __future__ import annotations

from dataclasses import astuple, dataclass
from threading import Event
from typing import Callable, Optional
from urllib.parse import quote_plus

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import subprocess
import sys
from selenium.webdriver.chrome.service import Service

# --- CSS selectors live in one place: if YouTube changes its layout, fix them here ---
SEL_ITEM = "ytd-video-renderer"
SEL_TITLE = "a#video-title"
SEL_CHANNEL = "ytd-channel-name a, ytd-channel-name #text"
SEL_META = "#metadata-line span"
SEL_DURATION = "ytd-thumbnail-overlay-time-status-renderer"

CONSENT_XPATH = (
    "//button[contains(@aria-label, 'Accept')]"
    " | //button[.//span[contains(text(), 'Accept all')]]"
)

FIELDS = ("Keyword", "Title", "Channel", "Views", "Published", "Duration", "Link")

LogFn = Callable[[str], None]
VideoFn = Callable[["Video", int], None]


@dataclass
class Video:
    keyword: str
    title: str
    channel: str
    views: str
    published: str
    duration: str
    link: str

    def as_row(self) -> tuple:
        return astuple(self)


@dataclass
class ScrapeConfig:
    keyword: str
    target: int = 20
    filter_word: str = ""
    headless: bool = False
    max_idle_scrolls: int = 4   # stop after N scrolls that load nothing new
    scroll_pause: float = 1.5   # seconds to wait for new results after scrolling


def _build_driver(headless: bool) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--lang=en-US")
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])

    service = Service()
    if sys.platform == "win32":
        service.creation_flags = subprocess.CREATE_NO_WINDOW
    return webdriver.Chrome(service=service, options=opts)


def _dismiss_consent(driver: webdriver.Chrome, log: LogFn) -> None:
    """Best-effort click on the cookie-consent dialog (common in the EU)."""
    try:
        WebDriverWait(driver, 4).until(
            EC.element_to_be_clickable((By.XPATH, CONSENT_XPATH))
        ).click()
        log("Cookie consent dismissed.")
    except TimeoutException:
        pass


def _text(parent: WebElement, css: str) -> str:
    try:
        value = parent.find_element(By.CSS_SELECTOR, css).get_attribute("textContent")
    except (NoSuchElementException, StaleElementReferenceException):
        return "N/A"
    return (value or "").strip() or "N/A"


def _parse(item: WebElement, keyword: str) -> Optional[Video]:
    anchor = item.find_element(By.CSS_SELECTOR, SEL_TITLE)
    title = (anchor.get_attribute("title") or anchor.text or "").strip()
    link = (anchor.get_attribute("href") or "").split("&")[0]
    if not title or not link:
        return None

    meta = [
        (s.get_attribute("textContent") or "").strip()
        for s in item.find_elements(By.CSS_SELECTOR, SEL_META)
    ]
    return Video(
        keyword=keyword,
        title=title,
        channel=_text(item, SEL_CHANNEL),
        views=meta[0] if meta else "N/A",
        published=meta[1] if len(meta) > 1 else "N/A",
        duration=_text(item, SEL_DURATION),
        link=link,
    )


def scrape(
    config: ScrapeConfig,
    on_log: LogFn = print,
    on_video: Optional[VideoFn] = None,
    stop_event: Optional[Event] = None,
) -> list[Video]:
    """Collect up to config.target videos. Call stop_event.set() to stop early."""
    stop = stop_event or Event()
    keyword = config.keyword.strip()
    filter_word = config.filter_word.strip().lower()
    results: list[Video] = []
    seen: set[str] = set()

    on_log("Starting Chrome...")
    driver = _build_driver(config.headless)
    try:
        on_log(f"Searching: {keyword}")
        driver.get(f"https://www.youtube.com/results?search_query={quote_plus(keyword)}")
        _dismiss_consent(driver, on_log)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, SEL_ITEM))
        )

        processed = 0  # how many result elements we already looked at
        idle = 0
        while len(results) < config.target and not stop.is_set():
            items = driver.find_elements(By.CSS_SELECTOR, SEL_ITEM)
            fresh = items[processed:]
            processed = len(items)

            for item in fresh:
                if stop.is_set() or len(results) >= config.target:
                    break
                try:
                    video = _parse(item, keyword)
                except (StaleElementReferenceException, NoSuchElementException):
                    continue
                if video is None or video.link in seen:
                    continue
                if filter_word and filter_word not in video.title.lower():
                    continue
                seen.add(video.link)
                results.append(video)
                if on_video:
                    on_video(video, len(results))

            if len(results) >= config.target:
                break

            idle = 0 if fresh else idle + 1
            if idle >= config.max_idle_scrolls:
                on_log("No more results to load.")
                break

            driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
            stop.wait(config.scroll_pause)
    finally:
        driver.quit()

    return results
