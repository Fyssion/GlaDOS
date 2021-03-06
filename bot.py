import discord
from discord.ext import commands

import logging
from datetime import datetime as d
import aiohttp
import json
import collections
import os
import asyncio

from config import Config
from cogs.utils import db
from cogs.utils.context import Context


formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

file_logger = logging.getLogger("discord")
file_logger.setLevel(logging.DEBUG)
file_handler = logging.FileHandler(
    filename="glados.log", encoding="utf-8", mode="w"
)
file_handler.setFormatter(formatter)
file_logger.addHandler(file_handler)

logger = logging.getLogger("discord")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger.addHandler(handler)

log = logging.getLogger("glados")
log.setLevel(logging.INFO)
log.addHandler(handler)
log.addHandler(file_handler)


initial_extensions = [
    "cogs.admin",
    "cogs.config",
    "cogs.scan",
    "cogs.meta",
    "cogs.stats",
    "cogs.timers",
]


class GlaDOS(commands.Bot):
    def __init__(self):
        self.config = Config("config.yml")

        self.debug = self.config.debug

        self.log = log

        if self.debug:
            self.log.info("Starting bot in debug mode...")
            command_prefix = "debug "

        else:
            self.log.info("Starting bot...")
            command_prefix = commands.when_mentioned

        super().__init__(
            command_prefix=command_prefix,
            description="I'll watch chat for your trigger words and notify you if I see one",
            owner_id=224513210471022592,
            case_insensitive=True,
            activity=discord.Activity(name="over you", type=discord.ActivityType.watching)
        )

        if not os.path.isfile("blacklist.json"):
            with open("blacklist.json", "w") as f:
                json.dump([], f)

        with open("blacklist.json", "r") as f:
            self.blacklist = json.load(f)

        self.error_cache = collections.deque(maxlen=100)
        self.console = None
        self.uptime = None
        self.session = None
        self.trigger_words = []
        self.loop.create_task(self.prepare_bot())

        # user_id: spam_amount
        self.spammers = {}
        self._cd = commands.CooldownMapping.from_cooldown(
            10.0, 15.0, commands.BucketType.user
        )

        self.cogs_to_load = initial_extensions

        self.load_extension("jishaku")
        self.load_extension("statsme")

        for cog in initial_extensions:
            self.load_extension(cog)

    async def prepare_bot(self):
        self.pool = await db.Table.create_pool(self.config.database_uri)
        self.session = aiohttp.ClientSession(loop=self.loop)

        # Cache a list of trigger words for lookup
        query = "SELECT word FROM trigger_words;"

        records = await self.pool.fetch(query)

        self.trigger_words = [r[0] for r in records]

        # Remove duplicates
        self.trigger_words = list(dict.fromkeys(self.trigger_words))

    async def delete_message_in(self, message, seconds=5.0):
        await asyncio.sleep(seconds)
        await message.delete()

    def delete_timer(self, message, seconds=5.0):
        self.loop.create_task(self.delete_message_in(message, seconds))

    def add_to_blacklist(self, user):
        self.blacklist.append(str(user.id))

        with open("blacklist.json", "w") as f:
            json.dump(self.blacklist, f)

        self.log.info(f"Added {user} to the blacklist.")

    def remove_from_blacklist(self, user_id):
        try:
            self.blacklist.pop(self.blacklist.index(str(user_id)))
        except ValueError:
            pass

        with open("blacklist.json", "w") as f:
            json.dump(self.blacklist, f)

        self.log.info(f"Removed {user_id} from the blacklist.")

    async def get_context(self, message, *, cls=None):
        return await super().get_context(message, cls=cls or Context)

    async def process_commands(self, message):
        if message.author.bot:
            return

        ctx = await self.get_context(message)

        if ctx.command is None:
            return

        if str(ctx.author.id) in self.blacklist:
            return

        bucket = self._cd.get_bucket(ctx.message)
        retry_after = bucket.update_rate_limit()
        spammers = self.spammers
        if retry_after and ctx.author.id != self.owner_id:
            if ctx.author.id in spammers:
                spammers[ctx.author.id] += 1
            else:
                spammers[ctx.author.id] = 1
            if spammers[ctx.author.id] > 10:
                self.add_to_blacklist(ctx.author)
                del spammers[ctx.author.id]
                return
            return await ctx.send(
                f"**You are on cooldown.** Try again after {int(retry_after)} seconds."
            )
        else:
            try:
                del spammers[ctx.author.id]
            except KeyError:
                pass

        await self.invoke(ctx)

    async def on_ready(self):
        if self.uptime is None:
            self.uptime = d.now()
        if self.console is None:
            self.console = self.get_channel(711952122132037722)

        self.log.info(f"Logged in as {self.user.name} - {self.user.id}")

    async def logout(self):
        await super().logout()
        await self.pool.close()

    def run(self):
        super().run(self.config.bot_token)


if __name__ == "__main__":
    bot = GlaDOS()
    bot.run()
