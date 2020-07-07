from discord.ext import commands
import discord

import traceback
import sys


class Meta(commands.Cog):
    """Everything to do with the bot itself."""

    def __init__(self, bot):
        self.bot = bot
        self.log = self.bot.log

        self._original_help_command = bot.help_command
        bot.help_command = commands.MinimalHelpCommand()
        bot.help_command.cog = self

    def cog_unload(self):
        self.bot.help_command = self._original_help_command

    @commands.Cog.listener("on_message")
    async def on_mention_msg(self, message):
        if self.bot.debug:
            return
        content = message.content
        id = self.bot.user.id
        if content == f"<@{id}>" or content == f"<@!{id}>":
            dev = self.bot.get_user(224513210471022592)
            await message.channel.send(
                f"Hi there! :wave: I'm a bot made by {dev}."
                "\nTo find out more about me, type:"
                f" `@{self.bot.user} help`"
            )

    # @commands.Cog.listener("on_error")
    # async def _dm_dev(self, event):
    #     e = sys.exc_info()
    #     full =''.join(traceback.format_exception(type(e), e, e.__traceback__, 1))
    #     owner = self.bot.get_user(self.bot.owner_id)
    #     await owner.send(f"Error in {event}:```py\n{full}```")

    async def send_unexpected_error(self, ctx, error):
        formatted = "".join(
            traceback.format_exception(type(error), error, error.__traceback__, 1)
        )
        self.bot.error_cache.append(error)

        em = discord.Embed(
            title=":warning: Unexpected Error", color=discord.Color.gold(),
        )

        description = (
            "An unexpected error has occured:"
            f"```py\n{error}```\n"
            "The developer has been notified."
            "\nConfused? Join my [support server.](https://www.discord.gg/wfCGTrp)"
        )

        em.description = description
        em.set_footer(icon_url=self.bot.user.avatar_url)

        await ctx.send(embed=em)

        extra_info = f"Command name: `{ctx.command.name}`"
        extra_info += f"\nError cache position: `{len(self.bot.error_cache) - 1}`"

        if ctx.args:
            args = [str(a) for a in ctx.args]
            extra_info += f"\nArgs: `{', '.join(args)}`"

        if ctx.kwargs:
            kwargs = [str(a) for a in ctx.kwargs]
            extra_info += f"\nKwargs: `{', '.join(kwargs)}`"

        extra_info += f"\n\nAn unexpected error has occured: ```py\n{error}```\n"
        em.description = extra_info

        await ctx.console.send(embed=em)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        stats = self.bot.get_cog("Stats")
        if stats:
            await stats.register_command(ctx)

        if hasattr(ctx, "handled"):
            return

        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send(
                f"{ctx.tick(False)} Sorry, this command can't be used in DMs."
            )

        elif isinstance(error, commands.ArgumentParsingError):
            await ctx.send(f"{ctx.tick(False)} {error}")

        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"{ctx.tick(False)} **You are on cooldown.** Try again after {int(error.retry_after)} seconds."
            )

        elif isinstance(error, commands.errors.BotMissingPermissions):
            perms = ""

            for perm in error.missing_perms:
                formatted = (
                    str(perm).replace("_", " ").replace("guild", "server").capitalize()
                )
                perms += f"\n- `{formatted}`"

            await ctx.send(
                f"{ctx.tick(False)} I am missing some required permission(s):{perms}"
            )

        elif isinstance(error, commands.errors.BadArgument):
            if str(error).startswith('Converting to "int" failed for parameter '):
                # param = str(error).replace('Converting to "int" failed for parameter ', "")
                # param = param.replace(".", "")
                # param = param.replace('"', "").strip()
                # param = discord.utils.escape_mentions(param)
                # param = discord.utils.escape_markdown(param)
                await ctx.send(f"{ctx.tick(False)} You must specify a number.")
            else:
                await ctx.send(f"{ctx.tick(False)} {error}")

        elif isinstance(error, commands.errors.MissingRequiredArgument):
            await ctx.send(
                f"{ctx.tick(False)} Missing a required argument: `{error.param.name}`"
            )

        elif (
            isinstance(error, commands.CommandInvokeError)
            and str(ctx.command) == "help"
        ):
            pass

        elif isinstance(error, commands.CommandInvokeError):
            original = error.original
            # if True: # for debugging
            if not isinstance(original, discord.HTTPException):
                print(
                    "Ignoring exception in command {}:".format(ctx.command),
                    file=sys.stderr,
                )
                traceback.print_exception(
                    type(error), error, error.__traceback__, file=sys.stderr
                )

                await self.send_unexpected_error(ctx, error)


def setup(bot):
    bot.add_cog(Meta(bot))
