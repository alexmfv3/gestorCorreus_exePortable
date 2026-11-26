import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width":1600,"height":1100})
        errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto("http://127.0.0.1:8765/"); await pg.wait_for_timeout(400)
        await pg.click("#w1"); await pg.fill("#f_email","jo@empresa.cat"); await pg.wait_for_timeout(100)
        print("roundcube desa enviats:", await pg.input_value("#f_sv"))
        await pg.fill("#f_email","algu@gmail.com"); await pg.wait_for_timeout(100)
        print("gmail desa enviats:", await pg.input_value("#f_sv"), "|", await pg.locator("#svhint").inner_text())
        await pg.screenshot(path="/tmp/shots/64_accform.png")
        await pg.fill("#f_pw","secret"); await pg.click("#save"); await pg.wait_for_timeout(2000)
        await pg.locator(".row", has_text="Reunió").first.locator(".t2").click() if await pg.locator(".row", has_text="Reunió").count() else None
        await pg.click("#compose") if await pg.locator("#compose").count() else None
        await pg.wait_for_timeout(400)
        print("redacta obert:", await pg.locator(".composer").count())
        await pg.keyboard.press("Escape"); await pg.wait_for_timeout(300)
        print("ERRORS:", errs); await b.close()
asyncio.run(main())
