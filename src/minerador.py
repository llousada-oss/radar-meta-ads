import os
import re
import json
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright
from notifier import notify

# Configuração de busca (Pode personalizar palavras-chave ou anunciantes)
KEYWORDS = ["lancheira blindada", "aplv", "nutricao infantil"]
MIN_DAYS_ACTIVE = 14
DB_PATH = "src/database.json"

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

def parse_ad_card_text(text: str):
    """Extrai informações estruturadas do texto do card da Ad Library."""
    ad_id_match = re.search(r"Identifica[çc][ãa]o da biblioteca:\s*(\d+)", text)
    ad_id = ad_id_match.group(1) if ad_id_match else None

    # Verifica duplicatas (ex: "3 anúncios usam esse criativo e esse texto")
    duplicates_match = re.search(r"(\d+)\s+an[úu]ncios usam esse criativo", text, re.IGNORECASE)
    duplicate_count = int(duplicates_match.group(1)) if duplicates_match else 1

    # Extrai datas de veiculação
    dates_match = re.search(r"(\d+\s+de\s+[a-zA-Zç]+\s+de\s+\d{4})", text)
    date_str = dates_match.group(1) if dates_match else "Data não identificada"

    # Extrai o primeiro gancho (primeira linha ou primeiras palavras)
    lines = [line.strip() for line in text.split("\n") if line.strip() and not line.startswith("Identifica") and not line.startswith("Plataformas") and not line.startswith("Inativo") and not line.startswith("Ativo")]
    copy_sample = "\n".join(lines[:6]) if lines else "Sem texto disponível"
    hook = lines[0] if lines else "Sem gancho identificado"

    return {
        "ad_id": ad_id,
        "duplicate_count": duplicate_count,
        "start_date_str": date_str,
        "hook": hook[:150],
        "copy_sample": copy_sample[:400]
    }

async def scrape_keyword(page, keyword: str, db: dict):
    url = f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=BR&q={keyword}&media_type=all"
    print(f"[*] Acessando: {url}")

    # Bloqueia mídias pesadas para economizar CPU e tempo de execução
    await page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())

    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3000)

    # Rola 3 vezes para carregar os cards sob demanda
    for _ in range(3):
        await page.mouse.wheel(0, 1500)
        await page.wait_for_timeout(1500)

    # Extrai o texto dos blocos de anúncios
    card_elements = await page.query_selector_all("div[role='dialog'], div[class*='xh8yej3']")
    print(f"[+] Elementos encontrados para '{keyword}': {len(card_elements)}")

    new_winners = []

    for card in card_elements:
        try:
            text = await card.inner_text()
            if "Identificação da biblioteca:" not in text:
                continue

            parsed = parse_ad_card_text(text)
            ad_id = parsed["ad_id"]

            if not ad_id:
                continue

            # Critério de Escala: Duplicatas >= 2 ou já persistente
            is_winner = parsed["duplicate_count"] >= 2 or "ativo" in text.lower()

            if is_winner:
                if ad_id not in db:
                    db[ad_id] = {
                        "keyword": keyword,
                        "first_seen": datetime.now().isoformat(),
                        "duplicates": parsed["duplicate_count"],
                        "hook": parsed["hook"]
                    }
                    new_winners.append(parsed)
                    print(f"[!] NOVO VENCEDOR DETECTADO: ID {ad_id} | Duplicatas: {parsed['duplicate_count']}")
        except Exception as e:
            continue

    return new_winners

async def main():
    db = load_database()
    winners_found = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        for kw in KEYWORDS:
            try:
                winners = await scrape_keyword(page, kw, db)
                winners_found.extend(winners)
            except Exception as e:
                print(f"[-] Erro ao processar '{kw}': {e}")

        await browser.close()

    save_database(db)

    # Dispara alerta se houver anúncios novos
    if winners_found:
        msg = f"🚨 *NOVO(S) ANÚNCIO(S) ESCALADO(S) DETECTADO(S)*\nTotal: {len(winners_found)}\n"
        for w in winners_found[:5]:
            msg += f"\n🆔 *ID:* `{w['ad_id']}`\n"
            msg += f"🔥 *Escala:* {w['duplicate_count']} anúncio(s) simultâneos\n"
            msg += f"🪝 *Gancho:* _{w['hook']}_\n"
            msg += f"🔗 [Ver Anúncio Oficial](https://www.facebook.com/ads/library/?id={w['ad_id']})\n"
            msg += "───────────────────\n"
        notify(msg)
    else:
        print("[*] Nenhum novo criativo escalado detectado nesta execução.")

if __name__ == "__main__":
    asyncio.run(main())
