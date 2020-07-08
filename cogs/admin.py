import discord
from discord.ext import commands, menus

import traceback
import psutil
import io
import time
from jishaku.codeblocks import codeblock_converter

from .utils.utils import TabularData, plural


class ErrorSource(menus.ListPageSource):
    def __init__(self, entries, error_id):
        super().__init__(entries, per_page=9)
        self.error_id = error_id

    def format_page(self, menu, entries):
        offset = menu.current_page * self.per_page
        message = f"**Page {menu.current_page + 1}/{self.get_max_pages()} \N{BULLET} Error {self.error_id}**```py\n"
        for i, line in enumerate(entries, start=offset):
            message += line
        message += "\n```"
        return message


class AllErrorsSource(menus.ListPageSource):
    def __init__(self, entries):
        super().__init__(entries, per_page=6)

    def format_page(self, menu, entries):
        offset = menu.current_page * self.per_page
        em = discord.Embed(
            title=f"{len(self.entries)} Errors Cached", color=discord.Color.blurple()
        )
        em.set_footer(text=f"Page {menu.current_page + 1}/{self.get_max_pages()}")

        description = []

        for i, error in enumerate(entries, start=offset):
            if str(error).startswith("Command raised an exception: "):
                e_formatted = str(error)[29:]
            else:
                e_formatted = str(error)
            description.append(f"`{len(self.entries) - 1 - i}.` {e_formatted}")

        em.description = "\n".join(description)

        return em


class Admin(commands.Cog):
    """Admin commands and features"""

    def __init__(self, bot):
        self.bot = bot
        self.hidden = True
        self.log = self.bot.log

    async def cog_check(self, ctx):
        if not await commands.is_owner().predicate(ctx):
            raise commands.NotOwner("You do not own this bot.")
        return True

    # https://github.com/Rapptz/RoboDanny/blob/rewrite/cogs/admin.py#L353-L419
    @commands.command(hidden=True)
    async def sql(self, ctx, *, code: codeblock_converter):
        """Run some SQL."""
        # the imports are here because I imagine some people would want to use
        # this cog as a base for their other cog, and since this one is kinda
        # odd and unnecessary for most people, I will make it easy to remove
        # for those people.
        lang, query = code

        is_multistatement = query.count(";") > 1
        if is_multistatement:
            # fetch does not support multiple statements
            strategy = ctx.db.execute
        else:
            strategy = ctx.db.fetch

        try:
            start = time.perf_counter()
            results = await strategy(query)
            dt = (time.perf_counter() - start) * 1000.0
        except Exception:
            return await ctx.send(f"```py\n{traceback.format_exc()}\n```")

        rows = len(results)
        if is_multistatement or rows == 0:
            return await ctx.send(f"`{dt:.2f}ms: {results}`")

        headers = list(results[0].keys())
        table = TabularData()
        table.set_columns(headers)
        table.add_rows(list(r.values()) for r in results)
        render = table.render()

        fmt = f"```\n{render}\n```\n*Returned {plural(rows):row} in {dt:.2f}ms*"
        if len(fmt) > 2000:
            fp = io.BytesIO(fmt.encode("utf-8"))
            await ctx.send("Too many results...", file=discord.File(fp, "results.txt"))
        else:
            await ctx.send(fmt)

    @commands.command(hidden=True)
    async def sql_table(self, ctx, *, table_name: str):
        """Runs a query describing the table schema."""

        query = """SELECT column_name, data_type, column_default, is_nullable
                   FROM INFORMATION_SCHEMA.COLUMNS
                   WHERE table_name = $1
                """

        results = await ctx.db.fetch(query, table_name)

        headers = list(results[0].keys())
        table = TabularData()
        table.set_columns(headers)
        table.add_rows(list(r.values()) for r in results)
        render = table.render()

        fmt = f"```\n{render}\n```"
        if len(fmt) > 2000:
            fp = io.BytesIO(fmt.encode("utf-8"))
            await ctx.send("Too many results...", file=discord.File(fp, "results.txt"))
        else:
            await ctx.send(fmt)

    @commands.group(
        description="View the blacklist", hidden=True, invoke_without_command=True
    )
    async def blacklist(self, ctx):
        formatted = "\n".join(self.bot.blacklist)
        await ctx.send(f"Blacklisted Users:\n{formatted}")

    @blacklist.command(
        name="add",
        description="Add someone to the blacklist",
        hidden=True,
        invoke_without_command=True,
    )
    async def blacklist_add(self, ctx, *, user: discord.User):
        if str(user.id) in self.bot.blacklist:
            return await ctx.send("That user is already blacklisted.")

        self.bot.add_to_blacklist(user)

        await ctx.send(f"{ctx.tick(True)} Added **`{user}`** to the blacklist.")

    @blacklist.command(
        name="remove",
        description="Remove someone from the blacklist",
        hidden=True,
        invoke_without_command=True,
    )
    async def blacklist_remove(self, ctx, user: int):
        if str(user) not in self.bot.blacklist:
            return await ctx.send("That user isn't blacklisted.")

        self.bot.remove_from_blacklist(user)

        await ctx.send(f"{ctx.tick(True)} Removed **`{user}`** from the blacklist.")

    @commands.command(
        name="reload",
        description="Reload an extension",
        aliases=["load"],
        usage="[cog]",
        hidden=True,
    )
    @commands.is_owner()
    async def _reload(self, ctx, cog="all"):
        if cog == "all":
            msg = ""

            for ext in self.bot.cogs_to_load:
                try:
                    self.bot.reload_extension(ext)
                    msg += (
                        f"**<a:cool_ok_sign:699837382433701998> Reloaded** `{ext}`\n\n"
                    )
                    self.log.info(f"Extension '{cog.lower()}' successfully reloaded.")

                except Exception as e:
                    traceback_data = "".join(
                        traceback.format_exception(type(e), e, e.__traceback__, 1)
                    )
                    msg += (
                        f"**{ctx.tick(False)} Extension `{ext}` not loaded.**\n"
                        f"```py\n{traceback_data}```\n\n"
                    )
                    traceback.print_exception(type(e), e, e.__traceback__)
            return await ctx.send(msg)

        try:
            self.bot.reload_extension(cog.lower())
            await ctx.send(f"<a:cool_ok_sign:699837382433701998>")
            self.log.info(f"Extension '{cog.lower()}' successfully reloaded.")
        except Exception as e:
            traceback_data = "".join(
                traceback.format_exception(type(e), e, e.__traceback__, 1)
            )
            await ctx.send(
                f"**{ctx.tick(False)} Extension `{cog.lower()}` not loaded.**\n```py\n{traceback_data}```"
            )
            self.log.warning(
                f"Extension 'cogs.{cog.lower()}' not loaded.\n{traceback_data}"
            )

    @commands.group(name="cog")
    @commands.is_owner()
    async def _cog(self, ctx):
        pass

    @_cog.command(name="reload")
    @commands.is_owner()
    async def _add_cog(self, ctx, cog):
        self.bot.add_cog(cog)
        self.bot.cogs_to_load.append(cog)
        self.bot.ordered_cogs.append(self.bot.cogs.keys()[-1])
        return await ctx.send("Cog added.")

    def readable(self, value):
        gigs = round(value // 1000000000)
        if gigs <= 0:
            megs = round(value // 1000000)
            return f"{megs}mb"
        return f"{gigs}gb"

    @commands.group(
        name="process", hidden=True, aliases=["computer", "comp", "cpu", "ram"]
    )
    @commands.is_owner()
    async def _process(self, ctx):
        em = discord.Embed(title="Current Process Stats", color=discord.Color.teal(),)
        em.add_field(
            name="CPU",
            value=f"{psutil.cpu_percent()}% used with {psutil.cpu_count()} CPU(s)",
        )
        mem = psutil.virtual_memory()
        em.add_field(
            name="Virtual Memory",
            value=f"{mem.percent}% used\n{self.readable(mem.used)}/{self.readable(mem.total)}",
        )
        disk = psutil.disk_usage("/")
        em.add_field(
            name="Disk",
            value=f"{disk.percent}% used\n{self.readable(disk.used)}/{self.readable(disk.total)}",
        )

        await ctx.send(embed=em)

    @commands.group(
        name="error", hidden=True, aliases=["e"], invoke_without_command=True,
    )
    @commands.is_owner()
    async def _error(self, ctx):
        first_step = list(self.bot.error_cache)
        errors = first_step[::-1]
        pages = menus.MenuPages(source=AllErrorsSource(errors), clear_reactions_after=True,)
        await pages.start(ctx)

    @_error.command(aliases=["pre", "p", "prev"])
    @commands.is_owner()
    async def previous(self, ctx):
        try:
            e = self.bot.error_cache[len(self.bot.error_cache) - 1]
        except IndexError:
            return await ctx.send("No previous errors cached.")
        etype = type(e)
        trace = e.__traceback__
        verbosity = 4
        lines = traceback.format_exception(etype, e, trace, verbosity)
        pages = menus.MenuPages(
            source=ErrorSource(lines, len(self.bot.error_cache) - 1),
            clear_reactions_after=True,
        )
        await pages.start(ctx)

    @_error.command(aliases=["i", "find", "get", "search"], usage="[index]")
    @commands.is_owner()
    async def index(self, ctx, i: int):
        if len(self.bot.error_cache) == 0:
            return await ctx.send("No previous errors cached.")
        try:
            e = self.bot.error_cache[i]
        except IndexError:
            return await ctx.send(f"{ctx.tick(False)} There is no error at that index.")
        etype = type(e)
        trace = e.__traceback__
        verbosity = 4
        lines = traceback.format_exception(etype, e, trace, verbosity)
        pages = menus.MenuPages(source=ErrorSource(lines, i), clear_reactions_after=True,)
        await pages.start(ctx)

    @commands.command(
        name="logout", description="Logs out and shuts down bot", hidden=True
    )
    @commands.is_owner()
    async def logout_command(self, ctx):
        self.log.info("Logging out of Discord.")
        await ctx.send("Killing me again? Goodbye...")
        await self.bot.session.close()
        await self.bot.logout()


def setup(bot):
    bot.add_cog(Admin(bot))
