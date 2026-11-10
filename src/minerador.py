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

# Configuração de busca - Nichos sazonais e de alta conversão para o final de ano
KEYWORDS = [
    "natal",
    "ano novo",
    "festas",
    "fim do ano",
    "final de ano",
    "lancheira blindada",
    "aplv"
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

def parse_ad_card_text(text: str):
    """Extrai informações estruturadas do texto do card da Ad Library."""
    ad_id_match = re.search(r"da biblioteca:\s*(\d+)", text, re.IGNORECASE)
    if not ad_id_match:
        ad_id_match = re.search(r"id=(\d+)", text, re.IGNORECASE)
    ad_id = ad_id_match.group(1) if ad_id_match else None

    duplicates_match = re.search(r"(\d+)\s+an[uú]ncios?\s+usam", text, re.IGNORECASE)
    duplicate_count = int(duplicates_match.group(1)) if duplicates_match else 1

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    cleaned_lines = [
        l for l in lines 
        if not re.search(r"(biblioteca|plataforma|inativo|ativo|patrocinado|cadastrado)", l, re.IGNORECASE)
        and len(l) > 10
    ]
    hook = cleaned_lines[0] if cleaned_lines else (lines[0] if lines else "Sem gancho identificado")

    return {
        "ad_id": ad_id,
        "duplicate_count": duplicate_count,
        "hook": hook[:140],
        "full_text": "\n".join(cleaned_lines[:4])
    }

async def scrape_keyword(page, keyword: str, db: dict):
    url = f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=BR&q={keyword}&media_type=all"
    print(f"[*] Acessando: {url}")

    await page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())

    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)

    # Rola a página para disparar o carregamento dos cards
    for _ in range(4):
        await page.mouse.wheel(0, 1500)
        await page.wait_for_timeout(1500)

    full_body_text = await page.inner_text("body")
    print(f"[+] Texto carregado para '{keyword}': {len(full_body_text)} caracteres")

    found_ids = list(set(re.findall(r"da biblioteca:\s*(\d+)", full_body_text, re.IGNORECASE)))
    print(f"[+] IDs detectados para '{keyword}': {len(found_ids)}")

    new_winners = []
    card_elements = await page.query_selector_all("div[class*='xh8yej3'], div[role='dialog'], div[class*='_7jyr']")
    
    for card in card_elements:
        try:
            text = await card.inner_text()
            if "biblioteca:" not in text.lower():
                continue

            parsed = parse_ad_card_text(text)
            ad_id = parsed["ad_id"]
            if not ad_id:
                continue

            if ad_id not in db:
                db[ad_id] = {
                    "keyword": keyword,
                    "first_seen": datetime.now().isoformat(),
                    "duplicates": parsed["duplicate_count"],
                    "hook": parsed["hook"]
                }
                new_winners.append(parsed)
                print(f"[!] NOVO ANÚNCIO COLETADO: ID {ad_id} | Duplicatas: {parsed['duplicate_count']}")
        except Exception:
            continue

    # Fallback por IDs extraídos do texto
    if not new_winners and found_ids:
        for fid in found_ids[:5]:
            if fid not in db:
                db[fid] = {
                    "keyword": keyword,
                    "first_seen": datetime.now().isoformat(),
                    "duplicates": 1,
                    "hook": f"Anúncio identificado no nicho {keyword}"
                }
                new_winners.append({
                    "ad_id": fid,
                    "duplicate_count": 1,
                    "hook": f"Anúncio ativo em {keyword}",
                    "full_text": ""
                })

    return new_winners

async def main():
    print("=== INICIANDO RADAR META ADS ===")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    print(f"Config Telegram: Token={'OK' if token else 'FALTANDO'} | ChatID={'OK' if chat_id else 'FALTANDO'}")

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

    # Disparo de Notificação
    if winners_found:
        msg = f"🎄 *RADAR META ADS: ANÚNCIOS ESCALADOS ENCONTRADOS*\nTotal detectados: {len(winners_found)}\n"
        for w in winners_found[:6]:
            msg += f"\n🆔 *ID:* `{w['ad_id']}`\n"
            msg += f"🔥 *Escala:* {w['duplicate_count']} conjunto(s)\n"
            msg += f"🪝 *Gancho:* _{w['hook']}_\n"
            msg += f"🔗 [Ver na Biblioteca da Meta](https://www.facebook.com/ads/library/?id={w['ad_id']})\n"
            msg += "───────────────────\n"
        notify(msg)
    else:
        print("[*] Nenhum criativo novo para alertar. Enviando status de radar ativo.")
        notify(f"✅ *Radar Meta Ads Ativo*\nVarredura concluída para os termos: {', '.join(KEYWORDS)}.\nNenhum anúncio novo escalado nas últimas 24h.")

if __name__ == "__main__":
    asyncio.run(main())
