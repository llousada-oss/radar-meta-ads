import os
import re
import json
import asyncio
import urllib.parse
from playwright.async_api import async_playwright
try:
    from src.notifier import notify
except ModuleNotFoundError:
    from notifier import notify

# Termos sazonais e de alta conversão
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
    Minera os criativos mais escalados e com maior longevidade no leilão (até 180 dias).
    Filtra ruídos de interface e captura anúncio, data de início, duplicatas e hook real.
    """
    ads = []
    raw_blocks = re.split(r"(?:Identifica[çc][ãa]o da biblioteca|Library ID):\s*", page_text, flags=re.IGNORECASE)
    
    for block in raw_blocks[1:]:
        lines = [l.strip() for l in block.split("\n") if l.strip() and l.strip() != "\u200b"]
        if not lines:
            continue
        
        ad_id = lines[0]
        if not re.match(r"^\d+$", ad_id):
            id_match = re.search(r"^(\d+)", ad_id)
            if id_match:
                ad_id = id_match.group(1)
            else:
                continue

        # Extrai contagem de duplicatas/escala ("X anúncios usam esse criativo")
        dup_match = re.search(r"(\d+)\s+an[úu]ncios?\s+usam", block, re.IGNORECASE)
        duplicate_count = int(dup_match.group(1)) if dup_match else 1

        # Extrai data de veiculação
        date_match = re.search(r"(\d{1,2}\s+de\s+[a-zçã]+\s+de\s+\d{4})", block, re.IGNORECASE)
        date_str = date_match.group(1) if date_match else "Ativo de longa data"

        # Extrai o gancho inicial (primeira linha de texto real da copy)
        hook = "Sem gancho identificado"
        ignore_patterns = re.compile(
            r"^(veicula[çc][ãa]o|plataformas?|esse an[úu]ncio|\d+\s+an[úu]ncios?\s+usam|abrir menu|ver detalhes|ver resumo|"
            r"patrocinado|ativo|inativo|compartilhar|denunciar|\d+:\d+|\.com|\.br|"
            r"saiba mais|comprar agora|shop now|learn more|obter cota[çc][ãa]o)",
            re.IGNORECASE
        )
        
        # Pula as primeiras linhas técnicas (ID, data, plataformas, patrocinado)
        for line in lines[2:25]:
            if len(line) >= 15 and not ignore_patterns.search(line):
                hook = line
                break

        ads.append({
            "ad_id": ad_id,
            "duplicate_count": duplicate_count,
            "date_str": date_str,
            "hook": hook[:140]
        })

    # Ranquear puramente pelos mais pesados e escalados
    ads.sort(key=lambda x: x["duplicate_count"], reverse=True)
    return ads

async def scrape_keyword(page, keyword: str):
    encoded_kw = urllib.parse.quote(keyword)
    url = f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=BR&q={encoded_kw}&sort_data[direction]=desc&sort_data[mode]=total_impressions&media_type=all"
    print(f"[*] Rastreando campeões de escala (até 180 dias) para: {keyword}")

    await page.goto(url, wait_until="networkidle", timeout=60000)
    await page.wait_for_timeout(3000)

    # Rolagem para disparar o carregamento contínuo dos cards
    for _ in range(5):
        await page.mouse.wheel(0, 1800)
        await page.wait_for_timeout(1000)

    page_text = await page.inner_text("body")
    ads = extract_ads_from_page(page_text)
    print(f"[+] Total de criativos encontrados para '{keyword}': {len(ads)}")
    
    return ads

async def main():
    print("=== MINERAÇÃO DE ALTA ESCALA E LONGEVIDADE (ATÉ 180 DIAS) ===")
    db = load_database()
    top_winners = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Contexto completo com viewport, locale pt-BR e headers para hidratação correta do React
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="pt-BR",
            extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"}
        )
        page = await context.new_page()

        for kw in KEYWORDS:
            try:
                ads = await scrape_keyword(page, kw)
                if ads:
                    # Captura os 2 maiores escalados de cada nicho
                    for best_ad in ads[:2]:
                        best_ad["keyword"] = kw
                        top_winners.append(best_ad)
                        db[best_ad["ad_id"]] = best_ad
            except Exception as e:
                print(f"[-] Erro em '{kw}': {e}")

        await browser.close()

    save_database(db)

    # Ranquear do mais escalado para o menos escalado
    top_winners.sort(key=lambda x: x["duplicate_count"], reverse=True)

    if top_winners:
        msg = f"🏆 *OS CRIATIVOS MAIS ESCALADOS DA BIBLIOTECA*\n"
        msg += f"_(Campeões de escala e longevidade no leilão - até 180 dias)_\n"
        msg += "══════════════════════\n"
        
        for ad in top_winners[:6]:
            msg += f"\n🔥 *Escala:* `{ad['duplicate_count']} anúncios simultâneos`\n"
            msg += f"🗓 *Desde:* {ad['date_str']}\n"
            msg += f"📌 *Tema:* #{ad['keyword'].replace(' ', '_')}\n"
            msg += f"🪝 *Hook:* \"_{ad['hook']}_\"\n"
            msg += f"🔗 [Acessar Criativo Oficial](https://www.facebook.com/ads/library/?id={ad['ad_id']})\n"
            msg += "──────────────────────\n"
        
        notify(msg)
    else:
        notify(f"ℹ️ Nenhum anúncio escalado capturado para os temas: {', '.join(KEYWORDS)}.")

if __name__ == "__main__":
    asyncio.run(main())
