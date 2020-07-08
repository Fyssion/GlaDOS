from discord.ext import commands
import discord

import asyncpg
import asyncio
import logging

from .utils import db


log = logging.getLogger("glados.highlight")


class HighlightWords(db.Table, table_name="highlight_words"):
    id = db.PrimaryKeyColumn()

    word = db.Column(db.String, index=True)
    user_id = db.Column(db.Integer(big=True), index=True)
    guild_id = db.Column(db.Integer(big=True), index=True)
    created_at = db.Column(db.Datetime, default="now() at time zone 'utc'")

    @classmethod
    def create_table(cls, *, exists_ok=True):
        statement = super().create_table(exists_ok=exists_ok)
        sql = "CREATE UNIQUE INDEX IF NOT EXISTS words_uniq_idx ON highlight_words (LOWER(word), user_id, guild_id);"
        return statement + "\n" + sql


class HighlightWord:
    @classmethod
    def from_record(cls, record):
        self = cls()

        self.id = record["id"]
        self.word = record["word"]
        self.user_id = record["user_id"]
        self.guild_id = record["guild_id"]
        self.created_at = record["created_at"]

        return self


class Highlight(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.delete_timer = bot.delete_timer

    async def send_highlight(self, message, word, record):
        highlight_word = HighlightWord.from_record(record)
        user = self.bot.get_user(highlight_word.user_id)

        log.info(
            f"Recieved highlight with word {word} for user {highlight_word.user_id}"
        )

        if not user:
            log.info(f"User {highlight_word.user_id} not found in cache, aborting")
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

        self.bot.dispatch("highlight", message, highlight_word)

        log.info(f"Building message list for message {message.id}")
        # Get a list of messages that meet certain requirements
        matching_messages = [
            m
            for m in reversed(self.bot.cached_messages)
            if m.channel == channel
            and m.created_at <= message.created_at
            and m.id != message.id
        ]

        time_formatting = "%H:%M "

        # Get the first three messages in that list
        previous_messages = matching_messages[:3]

        messages = []

        for msg in reversed(previous_messages):
            sent = msg.created_at.strftime(time_formatting)
            timezone = msg.created_at.strftime("%Z")
            sent += timezone or "UTC"

            if len(msg.content) > 25:
                content = msg.content[:25] + "..."

            else:
                content = msg.content

            messages.append(f"`{sent}` {msg.author}: {content}")

        # Bold the word in the highlighted message
        position = 0
        start_index = None
        content = list(message.content)

        for i, letter in enumerate(content):
            if letter.lower() == word[position]:
                if position == 0:
                    start_index = i

                if position == len(word) - 1:
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

        messages.append(f"> `{sent}` {message.author}: {content}")

        # See if there are any messages after

        # First, see if there are any messages after that have already been sent

        next_messages = []

        matching_messages = [
            m
            for m in reversed(self.bot.cached_messages)
            if m.channel == channel
            and m.created_at >= message.created_at
            and m.id != message.id
        ]

        if len(matching_messages) > 2:
            next_messages.append(matching_messages[0])
            next_messages.append(matching_messages[1])

        else:
            for msg in matching_messages:
                next_messages.append(msg)

            def check(ms):
                return ms.channel == channel

            # Waiting for next messages
            for i in range(2 - len(matching_messages)):
                try:
                    msg = await self.bot.wait_for("message", timeout=5.0, check=check)
                    next_messages.append(msg)

                except asyncio.TimeoutError:
                    pass

        for msg in next_messages:
            sent = msg.created_at.strftime(time_formatting)
            timezone = msg.created_at.strftime("%Z")
            sent += timezone or "UTC"

            if len(msg.content) > 25:
                content = msg.content[:25] + "..."

            else:
                content = msg.content

            messages.append(f"`{sent}` {msg.author}: {content}")

        em = discord.Embed(
            title=f"Highlighted word: {word}",
            description="\n".join(messages),
            color=discord.Color.blurple(),
            timestamp=message.created_at,
        )

        em.add_field(
            name="Jump To Message", value=f"[Jump]({message.jump_url})", inline=False
        )
        em.set_footer(text="Message sent")

        msg = (
            f"I found a highlight word: **{word}**!\n"
            f"Channel: {channel.mention}\n"
            f"Server: {guild}"
        )

        await user.send(msg, embed=em)

    async def get_highlight_words(self, message, word):
        query = """SELECT * FROM highlight_words
                   WHERE word=$1 AND guild_id=$2;
                """

        records = await self.bot.pool.fetch(query, word, message.guild.id)

        for record in records:
            self.bot.loop.create_task(self.send_highlight(message, word, record))

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # Check if the word is in the highlight words cache
        # Create a task so I can run the queries and send the messages concurrently
        # and not one at a time
        for word in self.bot.highlight_words:
            if word in message.content.lower():
                self.bot.loop.create_task(self.get_highlight_words(message, word))

    @commands.command(
        name="add",
        description="Add a word to your highlighted words list",
        usage="[word]",
    )
    async def _add(self, ctx, *word):
        self.delete_timer(ctx.message)

        if len(word) > 1:
            raise commands.BadArgument("You can only add single words to your list.")

        word = word[0].lower().strip()

        query = """INSERT INTO highlight_words (word, user_id, guild_id)
                   VALUES ($1, $2, $3);
                """

        query = """INSERT INTO highlight_words (word, user_id, guild_id)
                   VALUES ($1, $2, $3);
                """

        async with ctx.db.acquire() as con:
            tr = con.transaction()
            await tr.start()

            try:
                await ctx.db.execute(query, word, ctx.author.id, ctx.guild.id)

            except asyncpg.UniqueViolationError:
                await tr.rollback()
                await ctx.safe_send(f"You already have this highlight word registered.")

            except Exception:
                await tr.rollback()
                await ctx.safe_send(f"Could not add that word to your list. Sorry.")

            else:
                await tr.commit()

                if word not in self.bot.highlight_words:
                    self.bot.highlight_words.append(word)

                await ctx.safe_send(f"Successfully updated your highlight words list.")

    @commands.command(
        name="remove",
        description="Remove a word from your highlighted words list",
        usage="[word]",
    )
    async def _remove(self, ctx, word):
        self.delete_timer(ctx.message)

        query = """DELETE FROM highlight_words
                   WHERE word=$1 AND user_id=$2 AND guild_id=$3
                   RETURNING id;
                """
        deleted = await ctx.db.fetchrow(
            query, word.lower(), ctx.author.id, ctx.guild.id
        )

        if deleted is None:
            await ctx.safe_send(f"That word isn't in your highlighted words list.")

        else:
            await ctx.safe_send("Successfully updated your highlighted words list.")

    @commands.command(
        name="all",
        description="View all your highlighted words for this server",
        aliases=["list", "show"],
    )
    async def _all(self, ctx):
        self.delete_timer(ctx.message)

        query = """SELECT word FROM highlight_words
                   WHERE user_id=$1 AND guild_id=$2;
                """

        records = await ctx.db.fetch(query, ctx.author.id, ctx.guild.id)

        if not records:
            return await ctx.safe_send("You have no highlighted words for this server.")

        words = "\n".join([r[0] for r in records])

        em = discord.Embed(title="Your Highlight Words", description=words, color=discord.Color.blurple())

        em.set_footer(text=f"Total words: {len(records)}")

        await ctx.safe_send(embed=em, delete_after=10.0)


def setup(bot):
    bot.add_cog(Highlight(bot))
