"""
set_webhook.py — Register (or inspect / delete) the Telegram webhook
=====================================================================

Run this ONCE after every Vercel deployment to point Telegram at your
new serverless URL.

Usage:
  python set_webhook.py set    https://your-project.vercel.app/api/webhook
  python set_webhook.py info
  python set_webhook.py delete
"""

import sys
from telegram_client import set_webhook, delete_webhook, get_webhook_info


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1].lower()

    if action == "set":
        if len(sys.argv) < 3:
            print("Usage: python set_webhook.py set <URL>")
            sys.exit(1)
        url    = sys.argv[2]
        result = set_webhook(url)
        print("setWebhook response:", result)

    elif action == "info":
        result = get_webhook_info()
        import json
        print(json.dumps(result, indent=2))

    elif action == "delete":
        result = delete_webhook()
        print("deleteWebhook response:", result)

    else:
        print(f"Unknown action '{action}'. Use: set | info | delete")
        sys.exit(1)


if __name__ == "__main__":
    main()
