# SOURCE: https://github.com/Rapptz/RoboDanny/blob/rewrite/cogs/reminder.py

"""
The MIT License (MIT)

Copyright (c) 2017 Rapptz

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
"""


from discord.ext import commands, tasks
import discord

import asyncio
import asyncpg
import datetime

from .utils import db, human_time


class TimersTable(db.Table, table_name="timers"):
    id = db.PrimaryKeyColumn()

    expires = db.Column(db.Datetime, index=True)
    created = db.Column(db.Datetime, default="now() at time zone 'utc'")
    event = db.Column(db.String)
    extra = db.Column(db.JSON, default="'{}'::jsonb")


class Timer:
    __slots__ = ("args", "kwargs", "event", "id", "created_at", "expires")

    def __init__(self, *, record):
        self.id = record["id"]

        extra = record["extra"]
        self.args = extra.get("args", [])
        self.kwargs = extra.get("kwargs", {})
        self.event = record["event"]
        self.created_at = record["created"]
        self.expires = record["expires"]

    @classmethod
    def temporary(cls, *, expires, created, event, args, kwargs):
        pseudo = {
            "id": None,
            "extra": {"args": args, "kwargs": kwargs},
            "event": event,
            "created": created,
            "expires": expires,
        }
        return cls(record=pseudo)

    def __eq__(self, other):
        try:
            return self.id == other.id
        except AttributeError:
            return False

    def __hash__(self):
        return hash(self.id)

    @property
    def human_delta(self):
        return human_time.human_timedelta(self.created_at)

    def __repr__(self):
        return f"<Timer created={self.created_at} expires={self.expires} event={self.event}>"


class Timers(commands.Cog):
    """Timers helper cog"""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = ":alarm_clock:"

        self._have_data = asyncio.Event(loop=bot.loop)
        self._current_timer = None
        self.timer_task.add_exception_type(
            OSError, discord.ConnectionClosed, asyncpg.PostgresConnectionError
        )
        self.timer_task.start()

    def cog_unload(self):
        self.timer_task.cancel()

    async def get_active_timers(self, *, connection=None, seconds=30):
        query = "SELECT * FROM timers WHERE expires < (CURRENT_TIMESTAMP + $1::interval) ORDER BY expires;"
        con = connection or self.bot.pool

        records = await con.fetch(query, datetime.timedelta(seconds=seconds))

        if not records:
            return [None]

        timers = [Timer(record=r) if r else None for r in records]

        return timers

    async def call_timer(self, timer):
        # delete the timer
        query = "DELETE FROM timers WHERE id=$1;"
        await self.bot.pool.execute(query, timer.id)

        # dispatch the event
        event_name = f"{timer.event}_timer_complete"
        self.bot.dispatch(event_name, timer)

    async def dispatch_timer(self, timer):
        now = datetime.datetime.utcnow()

        if timer.expires >= now:
            to_sleep = (timer.expires - now).total_seconds()
            await asyncio.sleep(to_sleep)

        await self.call_timer(timer)

    @tasks.loop(seconds=30)
    async def timer_task(self):
        timers = await self.get_active_timers()

        for timer in timers:
            if timer is not None:
                self.bot.loop.create_task(self.dispatch_timer(timer))

    @timer_task.before_loop
    async def before_timer_task(self):
        await self.bot.wait_until_ready()
        # Wait for pool to connect
        while True:
            if self.bot.pool is None:
                await asyncio.sleep(1)
            else:
                break

    async def short_timer_optimisation(self, seconds, timer):
        await asyncio.sleep(seconds)
        event_name = f"{timer.event}_timer_complete"
        self.bot.dispatch(event_name, timer)

    async def create_timer(self, *args, **kwargs):
        """Creates a timer.
        Parameters
        -----------
        when: datetime.datetime
            When the timer should fire.
        event: str
            The name of the event to trigger.
            Will transform to 'on_{event}_timer_complete'.
        \*args
            Arguments to pass to the event
        \*\*kwargs
            Keyword arguments to pass to the event
        connection: asyncpg.Connection
            Special keyword-only argument to use a specific connection
            for the DB request.
        created: datetime.datetime
            Special keyword-only argument to use as the creation time.
            Should make the timedeltas a bit more consistent.
        Note
        ------
        Arguments and keyword arguments must be JSON serialisable.
        Returns
        --------
        :class:`Timer`
        """
        when, event, *args = args

        try:
            connection = kwargs.pop("connection")
        except KeyError:
            connection = self.bot.pool

        try:
            now = kwargs.pop("created")
        except KeyError:
            now = datetime.datetime.utcnow()

        timer = Timer.temporary(
            event=event, args=args, kwargs=kwargs, expires=when, created=now
        )
        delta = (when - now).total_seconds()
        if delta <= 60:
            # a shortcut for small timers
            self.bot.loop.create_task(self.short_timer_optimisation(delta, timer))
            return timer

        query = """INSERT INTO timers (event, extra, expires, created)
                   VALUES ($1, $2::jsonb, $3, $4)
                   RETURNING id;
                """

        row = await connection.fetchrow(
            query, event, {"args": args, "kwargs": kwargs}, when, now
        )
        timer.id = row[0]

        # only set the data check if it can be waited on
        if delta <= (86400 * 40):  # 40 days
            self._have_data.set()

        # # check if this timer is earlier than our currently run timer
        # if self._current_timer and when < self._current_timer.expires:
        #     # cancel the task and re-run it
        #     self._task.cancel()
        #     self._task = self.bot.loop.create_task(self.dispatch_timers())

        return timer


def setup(bot):
    bot.add_cog(Timers(bot))
