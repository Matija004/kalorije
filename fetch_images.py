"""Preuzima slike namirnica sa Wikipedije u images/ i upisuje ih u foods.json.

Pokretanje (jednom, uz internet):  python fetch_images.py
Može se pokrenuti više puta - preskače namirnice koje već imaju sliku.
Slike potiču sa Wikipedije/Wikimedia Commons (pogledaj licence ako ih objavljuješ).
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
FOODS_FILE = APP_DIR / "foods.json"
IMG_DIR = APP_DIR / "images"
API = "https://en.wikipedia.org/api/rest_v1/page/summary/"
HEADERS = {"User-Agent": "KalorijeApp/1.0 (studentski projekat)"}


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def main():
    IMG_DIR.mkdir(exist_ok=True)
    foods = json.loads(FOODS_FILE.read_text(encoding="utf-8"))
    done = failed = 0
    for i, food in enumerate(foods, 1):
        if food.get("image") and (APP_DIR / food["image"]).exists():
            continue
        title = food.get("wiki")
        if not title:
            continue
        try:
            data = json.loads(http_get(API + urllib.parse.quote(title, safe="")))
            src = (data.get("thumbnail") or {}).get("source")
            if not src:
                raise ValueError("nema slike")
            ext = Path(urllib.parse.urlparse(src).path).suffix.lower() or ".jpg"
            if ext == ".svg":
                raise ValueError("svg preskočen")
            dest = IMG_DIR / f"{food['id']}{ext}"
            dest.write_bytes(http_get(src))
            food["image"] = f"images/{dest.name}"
            done += 1
            print(f"[{i}/{len(foods)}] OK     {food['name']}")
        except Exception as exc:
            failed += 1
            print(f"[{i}/{len(foods)}] GREŠKA {food['name']}: {exc}")
        time.sleep(0.2)  # budi fin prema serveru
        if i % 10 == 0:  # povremeno sačuvaj napredak
            FOODS_FILE.write_text(json.dumps(foods, ensure_ascii=False, indent=2), encoding="utf-8")
    FOODS_FILE.write_text(json.dumps(foods, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGotovo. Preuzeto: {done}, neuspešno: {failed}")


if __name__ == "__main__":
    main()
