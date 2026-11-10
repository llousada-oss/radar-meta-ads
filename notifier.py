import os
import json
import requests

def send_telegram(message: str):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        return False
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"Erro ao enviar Telegram: {e}")
        return False

def send_discord(message: str):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return False
    
    payload = {"content": message}
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"Erro ao enviar Discord: {e}")
        return False

def notify(message: str):
    print(f"\n[NOTIFICACAO]\n{message}\n")
    sent_tg = send_telegram(message)
    sent_dc = send_discord(message)
    if sent_tg:
        print("[+] Enviado com sucesso para o Telegram.")
    if sent_dc:
        print("[+] Enviado com sucesso para o Discord.")
    if not sent_tg and not sent_dc:
        print("[-] Nenhuma integração de webhook ativa (TELEGRAM_BOT_TOKEN ou DISCORD_WEBHOOK_URL não definidos).")
