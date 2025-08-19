from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

class PlaywrightDriver:
    def __init__(self, headless: bool = True):
        self._headless = headless
        self._play = None
        self._browser = None
        self.page = None

    async def start(self):
        self._play = await async_playwright().start()
        self._browser = await self._play.chromium.launch(headless=self._headless)
        self.page = await self._browser.new_page()

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._play:
            await self._play.stop()

    async def snapshot(self):
        html = await self.page.content()
        soup = BeautifulSoup(html, "lxml")
        body = soup.body
        if body:
            for svg in body.find_all("svg"):
                svg.decompose()
            body_html = str(body)
        else:
            body_html = html
        return {"url": self.page.url, "title": await self.page.title(), "bodyHtml": body_html}
