from src.config import get_settings


async def notify_owner(text: str) -> None:
    """DM the owner on every configured chat surface (Discord and/or Slack)."""
    settings = get_settings()
    errors: list[BaseException] = []
    sent = False

    if settings.discord_enabled:
        try:
            from src.discord.client import post_discord_dm

            await post_discord_dm(settings.DISCORD_USER_ID, text)
            sent = True
        except BaseException as err:
            errors.append(err)

    if settings.slack_enabled:
        try:
            from src.slack.client import post_dm_to_user

            await post_dm_to_user(settings.SLACK_USER_ID, text, mrkdwn=True)
            sent = True
        except BaseException as err:
            errors.append(err)

    if sent:
        return
    if errors:
        raise errors[0]
    raise RuntimeError("No chat surface configured for notify_owner")
