"""Selenium 全业务主路径（S-01 ~ S-10）。"""

from __future__ import annotations

import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC

from conftest import collect_severe_console_errors, wait_url_contains
from pages.login import AppShell, LoginPage


@pytest.mark.smoke
def test_s01_unauthenticated_redirect_and_empty_validation(driver, wait, base_url):
    driver.get(f"{base_url}/chat")
    wait_url_contains(driver, "/login")
    page = LoginPage(driver, wait, base_url)
    page.submit_empty()
    time.sleep(0.5)
    messages = page.validation_messages()
    assert any("用户名" in m for m in messages)
    assert any("密码" in m for m in messages)


@pytest.mark.smoke
def test_s02_login_logout(driver, wait, base_url, admin_creds):
    page = LoginPage(driver, wait, base_url).open()
    page.login(*admin_creds)
    wait_url_contains(driver, "/chat")
    shell = AppShell(driver, wait, base_url)
    assert shell.has_nav("chat")
    shell.logout()
    wait_url_contains(driver, "/login")


@pytest.mark.llm
def test_s03_chat_send_message(driver, wait, base_url, admin_creds):
    LoginPage(driver, wait, base_url).open().login(*admin_creds)
    wait_url_contains(driver, "/chat")
    # 找输入框（ChatInput textarea）
    textarea = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "textarea")))
    textarea.send_keys("用一句话介绍你自己")
    textarea.send_keys(Keys.ENTER)
    # 等待出现助手消息气泡
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, ".message-bubble, .msg-ai, .ai-message, .chat-msg")) >= 1 or "流" in d.page_source or "助手" in d.page_source)
    time.sleep(2)


@pytest.mark.llm
def test_s04_knowledge_page_loads(driver, wait, base_url, admin_creds):
    LoginPage(driver, wait, base_url).open().login(*admin_creds)
    wait_url_contains(driver, "/chat")
    AppShell(driver, wait, base_url).click_nav("knowledge")
    wait_url_contains(driver, "/knowledge")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".knowledge-view, .rag-chat, main, .page")))


@pytest.mark.llm
def test_s05_agent_page_loads(driver, wait, base_url, admin_creds):
    LoginPage(driver, wait, base_url).open().login(*admin_creds)
    AppShell(driver, wait, base_url).click_nav("agent")
    wait_url_contains(driver, "/agent")


@pytest.mark.llm
def test_s06_workflow_page_loads(driver, wait, base_url, admin_creds):
    LoginPage(driver, wait, base_url).open().login(*admin_creds)
    AppShell(driver, wait, base_url).click_nav("workflow")
    wait_url_contains(driver, "/workflow")


@pytest.mark.llm
def test_s07_erp_page_loads(driver, wait, base_url, admin_creds):
    LoginPage(driver, wait, base_url).open().login(*admin_creds)
    AppShell(driver, wait, base_url).click_nav("erp")
    wait_url_contains(driver, "/erp")


@pytest.mark.smoke
def test_s08_admin_vs_user_nav(driver, wait, base_url, admin_creds, user_creds):
    LoginPage(driver, wait, base_url).open().login(*admin_creds)
    wait_url_contains(driver, "/chat")
    shell = AppShell(driver, wait, base_url)
    assert shell.has_nav("prompt")
    assert shell.has_nav("monitor")
    shell.logout()
    wait_url_contains(driver, "/login")

    LoginPage(driver, wait, base_url).open().login(*user_creds)
    wait_url_contains(driver, "/chat")
    shell = AppShell(driver, wait, base_url)
    assert not shell.has_nav("prompt")
    assert not shell.has_nav("monitor")
    shell.goto("/prompt")
    # 非 admin 应被拦回业务页
    time.sleep(1)
    assert "/prompt" not in driver.current_url or "/login" in driver.current_url or "/chat" in driver.current_url


@pytest.mark.smoke
def test_s09_navigate_during_idle_no_crash(driver, wait, base_url, admin_creds):
    LoginPage(driver, wait, base_url).open().login(*admin_creds)
    shell = AppShell(driver, wait, base_url)
    for name in ("chat", "knowledge", "agent", "workflow", "erp"):
        shell.click_nav(name)
        wait_url_contains(driver, f"/{name}")
        time.sleep(0.3)


@pytest.mark.smoke
def test_s10_no_severe_console_errors_on_login(driver, wait, base_url, admin_creds):
    LoginPage(driver, wait, base_url).open().login(*admin_creds)
    wait_url_contains(driver, "/chat")
    time.sleep(1)
    severe = collect_severe_console_errors(driver)
    assert severe == [], severe
