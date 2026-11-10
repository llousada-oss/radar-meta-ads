import os
import re
import json
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright
try:
    from src.notifier import notify
except ModuleNotFoundError:
    from notifier import notify

# Termos de alta demanda e sazonalidade
KEYWORDS = [
    "natal",
    "ano novo",
    "festas",
    "fim do ano",
    "final de ano"
]
DB_PATH = "database.json"

def load_database():
    if os.path.exists(DB_PATH):
        try:
            with open(DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_database(data):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def extract_ads_from_page(page_text: str):
    """
    Minera todos os anúncios presentes no DOM, priorizando os mais escalados:
    1. Duplicatas (X anúncios usam esse criativo)
    2. Tempo ativo / longevidade
    """
    ads = []
    
    # Divide o texto pelos blocos de identificação da biblioteca
    raw_blocks = re.split(r"Identifica[çc][ãa]o da biblioteca:\s*", page_text, flags=re.IGNORECASE)
    
    for block in raw_blocks[1:]:
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        if not lines:
            continue
        
        ad_id = lines[0]
        if not re.match(r"^\d+$", ad_id):
            id_match = re.search(r"^(\d+)", ad_id)
            if id_match:
                ad_id = id_match.group(1)
            else:
                continue

        # Extrai contagem de duplicatas (escala horizontal real do Facebook)
        dup_match = re.search(r"(\d+)\s+an[úu]ncios?\s+usam", block, re.IGNORECASE)
        duplicate_count = int(dup_match.group(1)) if dup_match else 1

        # Extrai datas de veiculação para medir longevidade
        date_match = re.search(r"(\d{1,2}\s+de\s+[a-zçã]+\s+de\s+\d{4})", block, re.IGNORECASE)
        date_str = date_match.group(1) if date_match else "Ativo"

        # Extrai o primeiro gancho (primeira frase com mais de 15 caracteres)
        hook = "Sem gancho identificado"
        for line in lines[1:10]:
            if len(line) > 15 and not re.search(r"(biblioteca|plataforma|ativo|inativo|patrocinado|transpar|facebook|instagram)", line, re.IGNORECASE):
                hook = line
                break

        ads.append({
            "ad_id": ad_id,
            "duplicate_count": duplicate_count,
            "date_str": date_str,
            "hook": hook[:120]
        })

    # Ordena pelo critério de MAIOR ESCALA (mais duplicatas primeiro)
    ads.sort(key=lambda x: x["duplicate_count"], reverse=True)
    return ads

async def scrape_keyword(page, keyword: str):
    # URL ordenada por maior volume de impressões
    url = f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=BR&q={keyword}&sort_data[direction]=desc&sort_data[mode]=total_impressions&media_type=all"
    print(f"[*] Minerando os maiores escalados para: {keyword}")

    await page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())

    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)

    # Rola profundamente 6 vezes para capturar os criativos que dominam o leilão
    for _ in range(6):
        await page.mouse.wheel(0, 2000)
        await page.wait_for_timeout(1200)

    page_text = await page.inner_text("body")
    ads = extract_ads_from_page(page_text)
    print(f"[+] Total de criativos mapeados para '{keyword}': {len(ads)}")
    
    return ads

async def main():
    print("=== MINERADOR DE CRIATIVOS ESCALADOS & MAIS LONGEVOS ===")
    db = load_database()
    top_winners = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        for kw in KEYWORDS:
            try:
                ads = await scrape_keyword(page, kw)
                if ads:
                    # Pega os 2 mais escalados de cada palavra-chave
                    for best_ad in ads[:2]:
                        best_ad["keyword"] = kw
                        top_winners.append(best_ad)
                        db[best_ad["ad_id"]] = best_ad
            except Exception as e:
                print(f"[-] Erro em '{kw}': {e}")

        await browser.close()

    save_database(db)

    # Ordena todos os vencedores pelo número de duplicatas/escala
    top_winners.sort(key=lambda x: x["duplicate_count"], reverse=True)

    if top_winners:
        msg = f"🏆 *TOP CRIATIVOS MAIS ESCALADOS (NATAL & ANO NOVO)*\n"
        msg += f"_Ordenados por maior volume e longevidade no leilão_\n"
        msg += "═══════════════════\n"
        
        # Envia os top 5 mais pesados do mercado
        for ad in top_winners[:5]:
            msg += f"\n🔥 *Escala:* `{ad['duplicate_count']} anúncios simultâneos`\n"
            msg += f"🗓 *Veiculação:* {ad['date_str']}\n"
            msg += f"📌 *Nicho:* #{ad['keyword'].replace(' ', '_')}\n"
            msg += f"🪝 *Hook:* \"_{ad['hook']}_\"\n"
            msg += f"🔗 [Ver Criativo Oficial](https://www.facebook.com/ads/library/?id={ad['ad_id']})\n"
            msg += "───────────────────\n"
        
        notify(msg)
    else:
        notify(f"ℹ️ Nenhum anúncio escalado capturado nos nichos: {', '.join(KEYWORDS)}.")

if __name__ == "__main__":
    asyncio.run(main())
