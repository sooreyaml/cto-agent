"""Device-code login for ChatGPT / Codex OAuth.

Run locally: python -m src.agent.codex_login
On Coolify, prefer “connect openai” in Discord instead.
"""

from __future__ import annotations

import asyncio
import logging

from src.agent.codex_oauth import complete_device_login, connect_message_markdown, start_device_auth


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    pending = await start_device_auth()
    print(connect_message_markdown(pending))
    cred = await complete_device_login(pending)
    print(f"Saved Codex login for account {cred.account_id}.")


if __name__ == "__main__":
    asyncio.run(main())
