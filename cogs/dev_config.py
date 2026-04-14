import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from config import logger
from database import get_meta, set_meta

DEV_USER_ID = 608531997849026609
DEBUG_META_KEY = "dev_debug_mirror"

_orig_messageable_send = discord.abc.Messageable.send
_orig_response_send = discord.InteractionResponse.send_message
_orig_webhook_send = discord.Webhook.send

_state = {"enabled": False, "bot": None, "patched": False}


def _describe_target(target) -> str:
    if isinstance(target, discord.DMChannel):
        recip = getattr(target, "recipient", None)
        return f"DM(@{recip.name if recip else '?'})"
    guild = getattr(target, "guild", None)
    name = getattr(target, "name", type(target).__name__)
    return f"#{name} in {guild.name}" if guild else f"#{name}"


def _summarize(content, kwargs) -> str:
    embeds = kwargs.get("embeds") or []
    if kwargs.get("embed"):
        embeds = [kwargs["embed"]]
    parts = []
    if content:
        parts.append(str(content))
    for e in embeds:
        title = getattr(e, "title", "") or ""
        desc = getattr(e, "description", "") or ""
        parts.append(f"[embed] {title}\n{desc}".strip())
    return "\n".join(parts) or "(no content)"


async def _mirror_to_dev(summary: str):
    bot = _state["bot"]
    if bot is None:
        return
    try:
        user = bot.get_user(DEV_USER_ID) or await bot.fetch_user(DEV_USER_ID)
        dm = user.dm_channel or await user.create_dm()
        body = summary if len(summary) <= 1900 else summary[:1900] + "…"
        await _orig_messageable_send(dm, content=body)
    except Exception:
        logger.exception("debug mirror: failed to DM developer")


def _is_dev_dm(target) -> bool:
    return (
        isinstance(target, discord.DMChannel)
        and getattr(target, "recipient", None) is not None
        and target.recipient.id == DEV_USER_ID
    )


async def _patched_messageable_send(self, content=None, **kwargs):
    result = await _orig_messageable_send(self, content=content, **kwargs)
    if _state["enabled"] and not _is_dev_dm(self):
        summary = f"[{_describe_target(self)}]\n{_summarize(content, kwargs)}"
        asyncio.create_task(_mirror_to_dev(summary))
    return result


async def _patched_response_send(self, content=None, **kwargs):
    result = await _orig_response_send(self, content=content, **kwargs)
    if _state["enabled"]:
        interaction = getattr(self, "_parent", None)
        where = "Interaction"
        if interaction is not None and interaction.channel is not None:
            where = f"Interaction in {_describe_target(interaction.channel)}"
        summary = f"[{where}]\n{_summarize(content, kwargs)}"
        asyncio.create_task(_mirror_to_dev(summary))
    return result


async def _patched_webhook_send(self, content=None, **kwargs):
    result = await _orig_webhook_send(self, content=content, **kwargs)
    if _state["enabled"]:
        summary = f"[Webhook]\n{_summarize(content, kwargs)}"
        asyncio.create_task(_mirror_to_dev(summary))
    return result


def _install_patches():
    if _state["patched"]:
        return
    discord.abc.Messageable.send = _patched_messageable_send
    discord.InteractionResponse.send_message = _patched_response_send
    discord.Webhook.send = _patched_webhook_send
    _state["patched"] = True


def _remove_patches():
    if not _state["patched"]:
        return
    discord.abc.Messageable.send = _orig_messageable_send
    discord.InteractionResponse.send_message = _orig_response_send
    discord.Webhook.send = _orig_webhook_send
    _state["patched"] = False


class DevConfigCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        _state["bot"] = self.bot
        if get_meta(DEBUG_META_KEY) == "1":
            _state["enabled"] = True
            _install_patches()
            logger.info("Dev debug mirror restored: ENABLED")

    async def cog_unload(self):
        _remove_patches()
        _state["enabled"] = False
        _state["bot"] = None

    config_group = app_commands.Group(
        name="config", description="Developer configuration (restricted)"
    )

    @config_group.command(
        name="debug",
        description="Mirror all bot output to the developer's DMs",
    )
    @app_commands.describe(debug="True to enable mirroring, false to disable")
    async def config_debug(self, interaction: discord.Interaction, debug: bool):
        if interaction.user.id != DEV_USER_ID:
            await interaction.response.send_message(
                "You don't have permission to use this command.", ephemeral=True
            )
            return

        if debug:
            _state["enabled"] = True
            _install_patches()
            set_meta(DEBUG_META_KEY, "1")
            logger.info("Dev debug mirror: ENABLED by %s", interaction.user)
            await interaction.response.send_message(
                "Debug mirroring **enabled** — bot output will be DMed to you.",
                ephemeral=True,
            )
        else:
            _state["enabled"] = False
            _remove_patches()
            set_meta(DEBUG_META_KEY, "0")
            logger.info("Dev debug mirror: DISABLED by %s", interaction.user)
            await interaction.response.send_message(
                "Debug mirroring **disabled**.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(DevConfigCog(bot))
