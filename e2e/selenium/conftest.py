"""
Selenium E2E 配置。

环境变量：
- E2E_BASE_URL  默认 http://localhost:8080（生产 Compose 前端入口）
- E2E_ADMIN_USER / E2E_ADMIN_PASS  默认 admin / admin123
- E2E_USER_USER / E2E_USER_PASS    默认 user / user123
- E2E_HEADLESS                     默认 1
"""

from __future__ import annotations

import os
import time

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


def pytest_configure(config):
    config.addinivalue_line("markers", "smoke: login/navigation smoke")
    config.addinivalue_line("markers", "llm: requires live LLM backend")


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("E2E_BASE_URL", "http://localhost:8080").rstrip("/")


@pytest.fixture(scope="session")
def admin_creds():
    return (
        os.environ.get("E2E_ADMIN_USER", "admin"),
        os.environ.get("E2E_ADMIN_PASS", "admin123"),
    )


@pytest.fixture(scope="session")
def user_creds():
    return (
        os.environ.get("E2E_USER_USER", "user"),
        os.environ.get("E2E_USER_PASS", "user123"),
    )


@pytest.fixture
def driver():
    options = ChromeOptions()
    if os.environ.get("E2E_HEADLESS", "1") != "0":
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1440,900")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})

    service = ChromeService(ChromeDriverManager().install())
    browser = webdriver.Chrome(service=service, options=options)
    browser.set_page_load_timeout(60)
    yield browser
    browser.quit()


@pytest.fixture
def wait(driver):
    return WebDriverWait(driver, 20)


def collect_severe_console_errors(driver) -> list[str]:
    errors = []
    for entry in driver.get_log("browser"):
        if entry.get("level") == "SEVERE":
            message = entry.get("message", "")
            # 忽略第三方/favicon 噪音
            if "favicon" in message or "net::ERR_" in message:
                continue
            errors.append(message)
    return errors


def wait_url_contains(driver, fragment: str, timeout: float = 20):
    end = time.time() + timeout
    while time.time() < end:
        if fragment in driver.current_url:
            return
        time.sleep(0.2)
    raise AssertionError(f"URL 未包含 {fragment!r}，当前={driver.current_url}")
