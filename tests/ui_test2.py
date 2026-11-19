import asyncio, subprocess, os, time
from playwright.async_api import async_playwright
URL="http://127.0.0.1:8765/"
def restart():
    subprocess.run(['bash', 'tests/srv.sh'])
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width":1600,"height":1000})
        errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(URL); await pg.wait_for_timeout(400)
        await pg.click("#w1"); await pg.click('.type[data-t="gmail"]')
        await pg.fill("#f_email","algu@gmail.com"); await pg.fill("#f_pw","secret")
        await pg.uncheck("#f_save"); await pg.screenshot(path="/tmp/shots/20_gmail_form.png")
        await pg.click("#save"); await pg.wait_for_timeout(2000)
        restart()
        await pg.reload(); await pg.wait_for_timeout(800)
        await pg.screenshot(path="/tmp/shots/21_pw_prompt.png")
        await pg.fill("#pw","secret"); await pg.click(".ov [data-ok]"); await pg.wait_for_timeout(2000)
        await pg.screenshot(path="/tmp/shots/22_after_pw.png")
        # move via picker with new folder
        await pg.locator(".row").first.locator('[data-a="move"]').click(); await pg.wait_for_timeout(300)
        await pg.screenshot(path="/tmp/shots/23_picker.png")
        await pg.fill("#nf","Ofertes"); await pg.click("#nfb"); await pg.wait_for_timeout(1200)
        await pg.click('.nav[data-p="carpetes"]'); await pg.wait_for_timeout(600)
        card = pg.locator(".mrow", has_text="Ofertes")
        await card.locator('[data-a="ren"]').click(); await pg.fill("#pv","Ofertes de feina"); await pg.click(".ov [data-ok]"); await pg.wait_for_timeout(800)
        await pg.click("#nf"); await pg.fill("#pv","Bancs"); await pg.select_option("#par","Feina"); await pg.click(".ov [data-ok]"); await pg.wait_for_timeout(800)
        await pg.screenshot(path="/tmp/shots/24_carpetes.png", full_page=True)
        await pg.click("#expall"); print(await pg.locator(".mrow .nm b").all_inner_texts())
        print("ERRORS:", errs)
        await b.close()
asyncio.run(main())
