from discord.ext import commands
import discord

from .utils import db, human_time


class UserConfig(db.Table, table_name="user_config"):
    id = db.PrimaryKeyColumn()

    user_id = db.Column(db.Integer(big=True), index=True)
    blocked_users = db.Column(db.Array(db.Integer(big=True)))
    blocked_channels = db.Column(db.Array(db.Integer(big=True)))


class UserConfigHelper:
    @classmethod
    def from_record(cls, record):
        self = cls()

        self.id = record["id"]

        self.user_id = record["user_id"]
        self.blocked_users = record["blocked_users"]
        self.blocked_channels = record["blocked_channels"]

        return self


class AlreadyBlocked(commands.CommandError):
    pass


class NotBlocked(commands.CommandError):
    pass


class BlockConverter(commands.Converter):
    async def convert(self, ctx, arg):
        try:
            user = await commands.UserConverter().convert(ctx, arg)
            return user

        except commands.BadArgument:
            pass

        channel = await commands.TextChannelConverter().convert(ctx, arg)
        return channel


class Config(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.log = self.bot.log

        self.delete_timer = bot.delete_timer

    async def cog_command_error(self, ctx, error):
        if isinstance(error, AlreadyBlocked):
            await ctx.safe_send("That user or channel is already blocked.")

        elif isinstance(error, NotBlocked):
            await ctx.safe_send("That user or channel isn't blocked.")

    async def get_config(self, user):
        query = """SELECT *
                   FROM user_config
                   WHERE user_id=$1;
                """

        record = await self.bot.pool.fetchrow(query, user)

        if not record:
            return None

        return UserConfigHelper.from_record(record)

    async def block_user(self, author, user):
        query = """SELECT *
                   FROM user_config
                   WHERE user_id=$1;
                """

        record = await self.bot.pool.fetchrow(query, author)

        if not record:
            query = """INSERT INTO user_config (user_id, blocked_users)
                       VALUES ($1, $2);
                    """

            await self.bot.pool.execute(query, author, [user])

        else:
            blocked_users = record["blocked_users"]

            if user in blocked_users:
                raise AlreadyBlocked()

            blocked_users.append(user)

            query = """UPDATE user_config
                       SET blocked_users=$2
                       WHERE user_id=$1;
                    """

            await self.bot.pool.execute(query, author, blocked_users)

    async def unblock_user(self, author, user):
        query = """SELECT *
                   FROM user_config
                   WHERE user_id=$1;
                """

        record = await self.bot.pool.fetchrow(query, author)

        if not record:
            raise NotBlocked()

        else:
            blocked_users = record["blocked_users"]

            if user not in blocked_users:
                raise NotBlocked()

            blocked_users.pop(blocked_users.index(user))

            query = """UPDATE user_config
                       SET blocked_users=$2
                       WHERE user_id=$1;
                    """

            await self.bot.pool.execute(query, author, blocked_users)

    async def block_channel(self, author, channel):
        query = """SELECT *
                   FROM user_config
                   WHERE user_id=$1;
                """

        record = await self.bot.pool.fetchrow(query, author)

        if not record:
            query = """INSERT INTO user_config (user_id, blocked_channels)
                       VALUES ($1, $2);
                    """

            await self.bot.pool.execute(query, author, [channel])

        else:
            blocked_channels = record["blocked_channels"]

            if not blocked_channels:
                blocked_channels = [channel]

            else:
                if channel in blocked_channels:
                    raise AlreadyBlocked()

                blocked_channels.append(channel)

            query = """UPDATE user_config
                       SET blocked_channels=$2
                       WHERE user_id=$1;
                    """

            await self.bot.pool.execute(query, author, blocked_channels)

    async def unblock_channel(self, author, channel):
        query = """SELECT *
                   FROM user_config
                   WHERE user_id=$1;
                """

        record = await self.bot.pool.fetchrow(query, author)

        if not record:
            raise NotBlocked()

        else:
            blocked_channels = record["blocked_channels"]

            if not blocked_channels or channel not in blocked_channels:
                raise NotBlocked()

            blocked_channels.pop(blocked_channels.index(channel))

            query = """UPDATE user_config
                       SET blocked_channels=$2
                       WHERE user_id=$1;
                    """

            await self.bot.pool.execute(query, author, blocked_channels)

    @commands.command(
        description="Block a user or channel from notifiying you with your trigger words",
        aliases=["ignore"],
        usage="<user or channel>",
    )
    async def block(self, ctx, *, entity: BlockConverter = None):
        self.delete_timer(ctx.message)

        entity = entity or ctx.channel

        if isinstance(entity, discord.User):
            await self.block_user(ctx.author.id, entity.id)

        elif isinstance(entity, discord.TextChannel):
            await self.block_channel(ctx.author.id, entity.id)

        await ctx.safe_send("Successfully updated your blocked list.")

    @commands.command(
        description="Unblock a user or channel in your blocked list",
        aliases=["unignore"],
        usage="<user or channel>",
    )
    async def unblock(self, ctx, *, entity: BlockConverter = None):
        self.delete_timer(ctx.message)

        entity = entity or ctx.channel

        if isinstance(entity, discord.User):
            await self.unblock_user(ctx.author.id, entity.id)

        elif isinstance(entity, discord.TextChannel):
            await self.unblock_channel(ctx.author.id, entity.id)

        await ctx.safe_send("Successfully updated your blocked list.")

    @commands.command(
        description="Temporarily block a user",
        aliases=["tempignore"],
        usage="<user/channel and time>",
    )
    async def tempblock(
        self, ctx, *, when: human_time.UserFriendlyTime(BlockConverter, default="")
    ):
        self.delete_timer(ctx.message)

        timers = self.bot.get_cog("Timers")

        if not timers:
            return await ctx.safe_send(
                "This functionality is not available right now. Please try again later."
            )

        entity = when.arg or ctx.channel
        time = when.dt

        if isinstance(entity, discord.User):
            await self.block_user(ctx.author.id, entity.id)
            await timers.create_timer(time, "user_block", ctx.author.id, entity.id)
            friendly = "user"

        elif isinstance(entity, discord.TextChannel):
            await self.block_channel(ctx.author.id, entity.id)
            await timers.create_timer(time, "channel_block", ctx.author.id, entity.id)
            friendly = "channel"

        await ctx.safe_send(
            f"Temporarily blocked {friendly} for {human_time.human_timedelta(time)}"
        )

    @commands.Cog.listener()
    async def on_user_block_timer_complete(self, timer):
        author, user = timer.args

        try:
            await self.unblock_user(author, user)

        except NotBlocked:
            return

    @commands.Cog.listener()
    async def on_channel_block_timer_complete(self, timer):
        author, channel = timer.args

        try:
            await self.unblock_channel(author, channel)

        except NotBlocked:
            return

    @commands.command(description="Display your blocked list")
    async def blocked(self, ctx):
        self.delete_timer(ctx.message)

        em = discord.Embed(
            title="Your blocked list",
            color=discord.Color.blurple(),
        )

        query = """SELECT blocked_users
                   FROM user_config
                   WHERE user_id=$1;
                """

        record = await ctx.db.fetchrow(query, ctx.author.id)

        users = []

        if not record or not record[0]:
            pass

        else:
            for user_id in record[0]:
                user = self.bot.get_user(user_id)
                users.append(str(user) if user else str(user_id))

        em.add_field(name="Users", value="\n".join(users) or "No blocked users")

        query = """SELECT blocked_channels
                   FROM user_config
                   WHERE user_id=$1;
                """

        record = await ctx.db.fetchrow(query, ctx.author.id)

        channels = []

        if not record or not record[0]:
            pass

        else:
            for channel_id in record[0]:
                channel = self.bot.get_channel(channel_id)
                channels.append(channel.mention if channel else str(channel_id))

        em.add_field(name="Channels", value="\n".join(channels) or "No blocked channels")

        await ctx.safe_send(embed=em, delete_after=10.0)


def setup(bot):
    bot.add_cog(Config(bot))
