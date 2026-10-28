"""Take README screenshots and a demo GIF from a running app with the demo account (`make demo`, then run it).

For the AI screens, run the app with a provider, for example:
    AI_PROVIDER=ollama OLLAMA_URL=http://localhost:11434 python manage.py runserver 8005
Needs Playwright with a Chrome/Chromium install:  pip install playwright pillow
Usage: python scripts/screenshots.py [--url http://localhost:8005] [--out docs/screenshots]
"""

import argparse
import io
import tempfile
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

VIEWPORT = {"width": 1440, "height": 900}
BAD_CSV = (
    "date,title,amount,category\n2026-10-01,Bread,2.5,Groceries\n2026-13-40,Bus,-3,Transport\n,Taxi,abc,Transport\n"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8005")
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    frames = []

    def shot(page, name: str, full: bool = False, frame: bool = True) -> None:
        page.mouse.move(5, 890)
        page.evaluate("document.activeElement && document.activeElement.blur()")
        png = page.screenshot(full_page=full)
        (args.out / f"{name}.png").write_bytes(png)
        if frame:
            image = Image.open(io.BytesIO(png)).convert("RGB")
            frames.append(image.crop((0, 0, VIEWPORT["width"], VIEWPORT["height"])))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
        page.set_default_timeout(400_000)
        page.goto(f"{args.url}/login/")
        page.fill("input[name=email]", "demo@smartspend.app")
        page.fill("input[name=password]", "demo1234")
        page.click("button[type=submit]")
        page.wait_for_url("**/dashboard/")
        page.wait_for_timeout(1200)  # charts animate in
        shot(page, "01_dashboard")

        page.fill("#quick-add-input", "Paid 18.50 for shawarma with friends yesterday")
        page.click("text=Add with AI")
        page.wait_for_url("**/dashboard/")
        page.wait_for_selector(".toast")
        page.wait_for_timeout(600)
        page.evaluate("document.querySelector('table.data').scrollIntoView({block: 'center'})")
        page.wait_for_timeout(300)
        shot(page, "02_ai_quick_add")

        page.goto(f"{args.url}/dashboard/")
        page.fill("#chat-input", "What are my top 3 spending categories this month?")
        page.click("text=Send")
        page.wait_for_function("!document.querySelector('#chat-log').innerText.includes('Thinking…')")
        page.evaluate("document.querySelector('#chat-log').scrollIntoView({block: 'center'})")
        page.wait_for_timeout(300)
        shot(page, "03_chat")

        page.goto(f"{args.url}/insights/")
        page.wait_for_timeout(500)
        shot(page, "04_insights")

        page.goto(f"{args.url}/transactions/?q=&category=&start=&end=")
        page.select_option("select[name=category]", label="Dining")
        page.click("text=Filter")
        page.wait_for_timeout(500)
        shot(page, "05_transactions_filtered")

        page.goto(f"{args.url}/report/")
        page.wait_for_timeout(500)
        shot(page, "06_monthly_report")

        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(BAD_CSV)
        page.goto(f"{args.url}/import/")
        page.set_input_files("input[name=csv_file]", f.name)
        page.click("button:has-text('Import')")
        page.wait_for_selector(".import-errors")
        shot(page, "07_import_validation", frame=False)
        Path(f.name).unlink()
        browser.close()

    gif = args.out / "demo.gif"
    small = [f.resize((960, 600), Image.Resampling.LANCZOS) for f in frames]
    small[0].save(gif, save_all=True, append_images=small[1:], duration=[3000, 3500, 4500, 3500, 3000, 3000], loop=0)
    print(f"{len(frames)} frames -> {gif}; screenshots in {args.out}")


if __name__ == "__main__":
    main()
