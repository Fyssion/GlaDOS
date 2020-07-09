from discord.ext import commands
import discord

import asyncpg
import asyncio
import logging

from .utils import db


log = logging.getLogger("glados.scanner")


class TriggerWords(db.Table, table_name="trigger_words"):
    id = db.PrimaryKeyColumn()

    word = db.Column(db.String, index=True)
    user_id = db.Column(db.Integer(big=True), index=True)
    guild_id = db.Column(db.Integer(big=True), index=True)
    created_at = db.Column(db.Datetime, default="now() at time zone 'utc'")

    @classmethod
    def create_table(cls, *, exists_ok=True):
        statement = super().create_table(exists_ok=exists_ok)
        sql = "CREATE UNIQUE INDEX IF NOT EXISTS words_uniq_idx ON trigger_words (LOWER(word), user_id, guild_id);"
        return statement + "\n" + sql


class TriggerWord:
    @classmethod
    def from_record(cls, record):
        self = cls()

        self.id = record["id"]
        self.word = record["word"]
        self.user_id = record["user_id"]
        self.guild_id = record["guild_id"]
        self.created_at = record["created_at"]

        return self


class Scanner(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.delete_timer = bot.delete_timer

    def format_message(self, message, *, highlight=None):
        time_formatting = "%H:%M "

        content = message.content if not highlight else discord.utils.escape_markdown(message.content)

        if highlight:
            # Bold the word in the highlighted message
            position = 0
            start_index = None
            content = list(discord.utils.escape_markdown(message.content))

            for i, letter in enumerate(content):
                if letter.lower() == highlight[position]:
                    if position == 0:
                        start_index = i

                    if position == len(highlight) - 1:
                        content.insert(start_index, "**")
                        content.insert(i + 2, "**")

                        position = 0
                        start_index = None

                    position += 1

                else:
                    position = 0
                    start_index = None

            content = "".join(content)

        sent = message.created_at.strftime(time_formatting)
        timezone = message.created_at.strftime("%Z")
        sent += timezone or "UTC"

        if not highlight and len(content) > 50:
            content = content[:50] + "..."

        else:
            content = content

        formatted = f"`{sent}` {message.author}: {content}"

        if highlight:
            formatted = f"> {formatted}"

        return formatted

    async def send_notification(self, message, word, record):
        trigger_word = TriggerWord.from_record(record)
        user = self.bot.get_user(trigger_word.user_id)

        log.info(
            f"Recieved highlight with word {word} for user {trigger_word.user_id}"
        )

        if not user:
            log.info(f"User {trigger_word.user_id} not found in cache, aborting")
            return

        if user == message.author:
            log.info(f"User {user} is the message author, aborting")
            return

        guild = message.guild
        channel = message.channel

        # Fetch user config to see if the author is blocked
        config = self.bot.get_cog("Config")

        if config:
            log.info(f"Fetching user config for {user}")
            user_config = await config.get_config(user.id)

            if user_config:
                log.info(f"User config found for {user}")

                if message.author.id in user_config.blocked_users:
                    log.info(f"{message.author} is in {user}'s blocked list, aborting")
                    return

                if message.channel.id in user_config.blocked_channels:
                    log.info(f"{message.channel} is in {user}'s blocked list, aborting")
                    return

        self.bot.dispatch("trigger", message, trigger_word)

        log.info(f"Building notification for message {message.id}")

        log.info(f"Getting list of previous messages for message {message.id}")
        # Get a list of messages that meet certain requirements
        matching_messages = [
            m
            for m in reversed(self.bot.cached_messages)
            if m.channel == channel
            and m.created_at <= message.created_at
            and m.id != message.id
        ]

        # Get the first three messages in that list
        previous_messages = matching_messages[:3]

        messages = []

        for msg in reversed(previous_messages):
            messages.append(self.format_message(msg))

        messages.append(self.format_message(message, highlight=word))

        # See if there are any messages after

        log.info(f"Getting list of next messages for message {message.id}")
        # First, see if there are any messages after that have already been sent
        next_messages = []

        matching_messages = [
            m
            for m in reversed(self.bot.cached_messages)
            if m.channel == channel
            and m.created_at >= message.created_at
            and m.id != message.id
        ]

        # If there are messages already sent, append those and continue
        if len(matching_messages) > 2:
            log.info(f"Found 2+ cached messages for message {message.id}")
            next_messages.append(matching_messages[0])
            next_messages.append(matching_messages[1])

        # Otherwise, add the cached message(s)
        # and/or wait for the remaining message(s)
        else:
            log.info(f"Found {len(matching_messages)} cached messages for message {message.id}")
            for msg in matching_messages:
                next_messages.append(msg)

            def check(ms):
                return ms.channel == channel and ms.id != message.id and ms.created_at > message.created_at

            # Waiting for next messages
            for i in range(2 - len(matching_messages)):
                log.info(f"Waiting for message {i+1}/{2-len(matching_messages)} for message {message.id}")
                try:
                    msg = await self.bot.wait_for("message", timeout=5.0, check=check)
                    log.info(f"Found message {i+1}/{2-len(matching_messages)} (ID: {msg.id}) for message {message.id}")
                    next_messages.append(msg)

                except asyncio.TimeoutError:
                    log.info(f"Timed out while waiting for message {i+1}/{2-len(matching_messages)} for message {message.id}")

        # Add the next messages to the formatted list
        for msg in next_messages:
            messages.append(self.format_message(msg))

        em = discord.Embed(
            title=f"Trigger word: {word}",
            description="\n".join(messages),
            color=discord.Color.blurple(),
            timestamp=message.created_at,
        )

        em.add_field(
            name="Jump To Message", value=f"[Jump]({message.jump_url})", inline=False
        )
        em.set_footer(text="Message sent")

        msg = (
            f"I found a trigger word: **{word}**\n"
            f"Channel: {channel.mention}\n"
            f"Server: {guild}"
        )

        log.info(f"Sending notification to user {user} for message {message.id}")

        await user.send(msg, embed=em)

    async def get_trigger_words(self, message, word):
        query = """SELECT * FROM trigger_words
                   WHERE word=$1 AND guild_id=$2;
                """

        records = await self.bot.pool.fetch(query, word, message.guild.id)

        for record in records:
            self.bot.loop.create_task(self.send_notification(message, word, record))

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # Check if the word is in the trigger words cache
        # Create a task so I can run the queries and send the messages concurrently
        # and not one at a time
        for word in self.bot.trigger_words:
            if word in message.content.lower():
                self.bot.loop.create_task(self.get_trigger_words(message, word))

    @commands.command(
        name="add",
        description="Add a word to your triggers",
        usage="[word]",
    )
    async def _add(self, ctx, *word):
        self.delete_timer(ctx.message)

        if len(word) > 1:
            raise commands.BadArgument("You can only add single words to your triggers.")

        word = word[0].lower().strip()

        query = """INSERT INTO trigger_words (word, user_id, guild_id)
                   VALUES ($1, $2, $3);
                """

        query = """INSERT INTO trigger_words (word, user_id, guild_id)
                   VALUES ($1, $2, $3);
                """

        async with ctx.db.acquire() as con:
            tr = con.transaction()
            await tr.start()

            try:
                await ctx.db.execute(query, word, ctx.author.id, ctx.guild.id)

            except asyncpg.UniqueViolationError:
                await tr.rollback()
                await ctx.safe_send(f"You already have this trigger registered.")

            except Exception:
                await tr.rollback()
                await ctx.safe_send(f"Could not add that word to your list. Sorry.")

            else:
                await tr.commit()

                if word not in self.bot.trigger_words:
                    self.bot.trigger_words.append(word)

                await ctx.safe_send(f"Successfully updated your triggers.")

    @commands.command(
        name="remove",
        description="Remove a word from your triggers",
        usage="[word]",
    )
    async def _remove(self, ctx, word):
        self.delete_timer(ctx.message)

        query = """DELETE FROM trigger_words
                   WHERE word=$1 AND user_id=$2 AND guild_id=$3
                   RETURNING id;
                """
        deleted = await ctx.db.fetchrow(
            query, word.lower(), ctx.author.id, ctx.guild.id
        )

        if deleted is None:
            await ctx.safe_send(f"That word isn't in your triggers.")

        else:
            await ctx.safe_send("Successfully updated your triggers.")

    @commands.command(
        name="all",
        description="View all your triggers for this server",
        aliases=["list", "show"],
    )
    async def _all(self, ctx):
        self.delete_timer(ctx.message)

        query = """SELECT word FROM trigger_words
                   WHERE user_id=$1 AND guild_id=$2;
                """

        records = await ctx.db.fetch(query, ctx.author.id, ctx.guild.id)

        if not records:
            return await ctx.safe_send("You have no triggers for this server.")

        words = "\n".join([r[0] for r in records])

        em = discord.Embed(title="Your Triggers", description=words, color=discord.Color.blurple())

        em.set_footer(text=f"Total triggers: {len(records)}")

        await ctx.safe_send(embed=em, delete_after=10.0)


def setup(bot):
    bot.add_cog(Scanner(bot))
