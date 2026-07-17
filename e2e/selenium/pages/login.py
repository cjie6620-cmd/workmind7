from __future__ import annotations

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC


class LoginPage:
    def __init__(self, driver, wait, base_url: str):
        self.driver = driver
        self.wait = wait
        self.base_url = base_url

    def open(self):
        self.driver.get(f"{self.base_url}/login")
        self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='login-username']")))
        return self

    def submit_empty(self):
        self.driver.find_element(By.CSS_SELECTOR, "[data-testid='login-submit']").click()
        return self

    def login(self, username: str, password: str):
        user_el = self.driver.find_element(By.CSS_SELECTOR, "[data-testid='login-username'] input")
        pass_el = self.driver.find_element(By.CSS_SELECTOR, "[data-testid='login-password'] input")
        user_el.clear()
        user_el.send_keys(username)
        pass_el.clear()
        pass_el.send_keys(password)
        self.driver.find_element(By.CSS_SELECTOR, "[data-testid='login-submit']").click()
        return self

    def validation_messages(self) -> list[str]:
        return [el.text for el in self.driver.find_elements(By.CSS_SELECTOR, ".el-form-item__error") if el.text]


class AppShell:
    def __init__(self, driver, wait, base_url: str):
        self.driver = driver
        self.wait = wait
        self.base_url = base_url

    def goto(self, path: str):
        self.driver.get(f"{self.base_url}{path}")
        return self

    def click_nav(self, name: str):
        self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, f"[data-testid='nav-{name}']"))).click()
        return self

    def logout(self):
        self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "[data-testid='logout-btn']"))).click()
        return self

    def has_nav(self, name: str) -> bool:
        return len(self.driver.find_elements(By.CSS_SELECTOR, f"[data-testid='nav-{name}']")) > 0
