"""Build the public browser demo without changing the local SQLite app."""
from pathlib import Path
import shutil
import re

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "public"
OUTPUT.mkdir(exist_ok=True)
static = ROOT / "src" / "workbench" / "static"
for item in static.iterdir():
    if item.is_file():
        shutil.copyfile(item, OUTPUT / item.name)
page = (static / "index.html").read_text()
page = page.replace('<script src="/app.js" defer></script>', '<script src="/browser-store.js" defer></script>\n    <script src="/app.js" defer></script>')
page = page.replace('Local workspace', 'Public demo')
page = re.sub(r'Synthetic customers\.\s+Real\s+validation\.', 'Synthetic customers. Plans stay in this browser.', page)
page = page.replace('A local, synthetic customer onboarding demonstration', 'An interactive synthetic customer onboarding demonstration')
page = page.replace('synthetic data · saved locally', 'synthetic data · saved in this browser')
(OUTPUT / "index.html").write_text(page)
(OUTPUT / "invoice").mkdir(exist_ok=True)
shutil.copyfile(ROOT / "index.html", OUTPUT / "invoice" / "index.html")
print("Built onboarding demo and preserved invoice demo at /invoice/.")
