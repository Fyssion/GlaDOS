from discord.ext import commands
import discord

import traceback
import sys


class HelpCommand(commands.HelpCommand):
    def get_base_embed(self):
        ctx = self.context
        bot = ctx.bot
        em = discord.Embed(
            title=f"You asked for help? Fine. Here you go.",
            color=discord.Color.blurple(),
        )
        em.set_thumbnail(url=ctx.bot.user.avatar_url)
        em.set_footer(text="I'm only displaying commands that you can use")
        return em

    async def send_bot_help(self, mapping):
        ctx = self.context
        bot = ctx.bot

        em = self.get_base_embed()
        em.description = (
            f"{bot.description}\n\n"
            f"If you want more info on a command, use `@{bot.user} help [command]`"
        )

        filtered = await self.filter_commands(bot.commands)

        formatted = []

        for command in filtered:
            cmd_formatted = f"**`{command.name}`**"

            if command.description:
                cmd_formatted += f" - {command.description}"

            formatted.append(cmd_formatted)

        cmds = "\n".join(formatted)
        em.description += f"\n\nCommands:\n{cmds}"

        await ctx.send(embed=em)

    async def send_command_help(self, command):
        ctx = self.context
        bot = ctx.bot

        em = self.get_base_embed()

        em.set_footer(text=em.Empty)

        em.description = f"**`@{bot.user} "
        em.description += f"{command.parent} " if command.parent is not None else ""
        em.description += command.name
        em.description += f" {command.usage}`**" if command.usage is not None else "`**"

        if command.description:
            em.description += f" - {command.description}"

        if command.help:
            em.description += "\n" + command.help + "\n"

        if command.aliases:
            formatted_aliases = []

            for alias in command.aliases:
                formatted_alias = f"`@{bot.user} "
                formatted_alias += (
                    f"{command.parent} " if command.parent is not None else ""
                )

                formatted_alias += alias + "`"
                formatted_aliases.append(formatted_alias)

            em.description += f"\nAliases: {', '.join(formatted_aliases)}"

        await ctx.send(embed=em)

    async def command_callback(self, ctx, *, command=None):
        # I am only overriding this because I want to add
        # case insensitivity for cogs

        await self.prepare_help_command(ctx, command)
        bot = ctx.bot

        if command is None:
            mapping = self.get_bot_mapping()
            return await self.send_bot_help(mapping)

        maybe_coro = discord.utils.maybe_coroutine

        # At this point, the command could either be a cog
        # or a command
        keys = command.split(" ")
        cmd = bot.all_commands.get(keys[0])
        if cmd is None:
            string = await maybe_coro(
                self.command_not_found, self.remove_mentions(keys[0])
            )

            # At this point, the command was not found
            # If the cog exists, send that

            return await self.send_error_message(string)

        for key in keys[1:]:
            try:
                found = cmd.all_commands.get(key)
            except AttributeError:
                string = await maybe_coro(
                    self.subcommand_not_found, cmd, self.remove_mentions(key)
                )
                return await self.send_error_message(string)
            else:
                if found is None:
                    string = await maybe_coro(
                        self.subcommand_not_found, cmd, self.remove_mentions(key)
                    )
                    return await self.send_error_message(string)
                cmd = found

        if isinstance(cmd, commands.Group):
            return await self.send_group_help(cmd)
        else:
            return await self.send_command_help(cmd)


class Meta(commands.Cog):
    """Everything to do with the bot itself."""

    def __init__(self, bot):
        self.bot = bot
        self.log = self.bot.log

        self._original_help_command = bot.help_command
        bot.help_command = HelpCommand()
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
            await message.channel.send(
                f"Hello and, again, welcome to the Aperture Science computer-aided enrichment center."
                "\nIf you're curious about me, type:"
                f" `@{self.bot.user} help`"
            )

    async def send_unexpected_error(self, ctx, error):
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

        if ctx.command.cog and ctx.command.cog.qualified_name in ["Config", "Scanner"]:
            self.bot.delete_timer(ctx.message)
            send = ctx.safe_send

        else:
            send = ctx.send

        if isinstance(error, commands.NoPrivateMessage):
            await send(
                f"{ctx.tick(False)} Sorry, this command can't be used in DMs."
            )

        elif isinstance(error, commands.ArgumentParsingError):
            await send(f"{ctx.tick(False)} {error}")

        elif isinstance(error, commands.CommandOnCooldown):
            await send(
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
                await send(f"{ctx.tick(False)} You must specify a number.")
            else:
                await send(f"{ctx.tick(False)} {error}")

        elif isinstance(error, commands.errors.MissingRequiredArgument):
            await send(
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

    @commands.command(description="Invite me to your server")
    async def invite(self, ctx):
        permissions = discord.Permissions(
            read_messages=True,
            send_messages=True,
            embed_links=True,
            add_reactions=True,
            manage_messages=True,
        )

        url = discord.utils.oauth_url(self.bot.user.id, permissions=permissions)

        await ctx.send(
            "Aww, how sweet of you to ask!\n"
            "You can invite me to your server with this link:"
            f"\n<{url}>"
        )


def setup(bot):
    bot.add_cog(Meta(bot))
