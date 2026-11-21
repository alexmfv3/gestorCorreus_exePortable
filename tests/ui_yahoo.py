import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width":1600,"height":1000})
        errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto("http://127.0.0.1:8765/"); await pg.wait_for_timeout(400)
        await pg.click("#w1"); await pg.fill("#f_email","algu@yahoo.es"); await pg.wait_for_timeout(150)
        print("tipus detectat:", await pg.locator(".type.on").get_attribute("data-t"),
              "| servidor visible:", await pg.locator("#srv").is_visible(), "| nota:", await pg.locator("#gnote").inner_text())
        await pg.fill("#f_pw","sec ret"); await pg.click("#test"); await pg.wait_for_timeout(600)
        print("prova:", await pg.locator("#res").inner_text())
        await pg.screenshot(path="/tmp/shots/40_yahoo_form.png")
        await pg.click("#save"); await pg.wait_for_timeout(2500)
        await pg.screenshot(path="/tmp/shots/41_yahoo.png")
        print("arbre:", [t.split("\n")[0] for t in await pg.locator(".tn").all_inner_texts()])
        await pg.click('.nav[data-p="ajuda"]'); await pg.wait_for_timeout(300)
        print("ajuda yahoo:", await pg.locator("h3", has_text="Yahoo").count())
        print("ERRORS:", errs); await b.close()
asyncio.run(main())
