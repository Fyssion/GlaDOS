from discord.ext import commands
import discord

from .utils import db, human_time


class UserConfig(db.Table, table_name="user_config"):
    id = db.PrimaryKeyColumn()

    user_id = db.Column(db.Integer(big=True), index=True)
    blocked_users = db.Column(db.Array(db.Integer(big=True)))


class UserConfigHelper:
    @classmethod
    def from_record(cls, record):
        self = cls()

        self.id = record["id"]

        self.user_id = record["user_id"]
        self.blocked_users = record["blocked_users"]

        return self


class AlreadyBlocked(commands.CommandError):
    pass


class NotBlocked(commands.CommandError):
    pass


class Config(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.log = self.bot.log

        self.delete_timer = bot.delete_timer

    async def cog_command_error(self, ctx, error):
        if isinstance(error, AlreadyBlocked):
            await ctx.safe_send("That user is already blocked.")

        elif isinstance(error, NotBlocked):
            await ctx.safe_send("That user isn't blocked.")

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

    @commands.command(
        description="Block a user from notifiying you with your trigger words",
        aliases=["ignore"],
        usage="[user]",
    )
    async def block(self, ctx, *, user: discord.User):
        self.delete_timer(ctx.message)

        await self.block_user(ctx.author.id, user.id)

        await ctx.safe_send("Successfully updated your blocked list.")

    @commands.command(
        description="Unblock a user in your blocked list",
        aliases=["unignore"],
        usage="[user]",
    )
    async def unblock(self, ctx, *, user: discord.User):
        self.delete_timer(ctx.message)

        await self.unblock_user(ctx.author.id, user.id)

        await ctx.safe_send("Successfully updated your blocked list.")

    @commands.command(
        description="Temporarily block a user",
        aliases=["tempignore"],
        usage="[user and time]",
    )
    async def tempblock(
        self, ctx, *, when: human_time.UserFriendlyTime(commands.UserConverter)
    ):
        self.delete_timer(ctx.message)

        timers = self.bot.get_cog("Timers")

        if not timers:
            return await ctx.safe_send(
                "This functionality is not available right now. Please try again later."
            )

        user = when.arg
        time = when.dt

        await self.block_user(ctx.author.id, user.id)

        await timers.create_timer(time, "block", ctx.author.id, user.id)

        await ctx.safe_send(
            f"Temporarily blocked user for {human_time.human_timedelta(time)}"
        )

    @commands.Cog.listener()
    async def on_block_timer_complete(self, timer):
        author, user = timer.args

        try:
            await self.unblock_user(author, user)

        except NotBlocked:
            return

    @commands.command(description="Display your blocked list")
    async def blocked(self, ctx):
        self.delete_timer(ctx.message)

        query = """SELECT blocked_users
                   FROM user_config
                   WHERE user_id=$1;
                """

        record = await ctx.db.fetchrow(query, ctx.author.id)

        if not record or not record[0]:
            return await ctx.safe_send("You have no blocked users.")

        users = []

        for user_id in record[0]:
            user = self.bot.get_user(user_id)
            users.append(str(user) if user else str(user_id))

        em = discord.Embed(
            title="Your blocked users",
            description="\n".join(users),
            color=discord.Color.blurple(),
        )

        await ctx.safe_send(embed=em, delete_after=10.0)


def setup(bot):
    bot.add_cog(Config(bot))
