#
# SchoolTool - common information systems platform for school administration
# Copyright (c) 2005 Shuttleworth Foundation
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
"""
Recurrent calendar events.

$Id$
"""

import datetime
import calendar
from sets import Set

from zope.interface import implements
from schoolbell.calendar.icalendar import ical_weekdays
from schoolbell.calendar.icalendar import ical_date, ical_datetime
from schoolbell.calendar.mixins import CalendarEventMixin
from schoolbell.calendar.simple import SimpleCalendarEvent
from schoolbell.calendar.interfaces import Unchanged
from schoolbell.calendar.interfaces import IExpandedCalendarEvent, \
    IDailyRecurrenceRule, IWeeklyRecurrenceRule, IMonthlyRecurrenceRule, \
    IYearlyRecurrenceRule, IRecurrenceRule


class ExpandedCalendarEvent(CalendarEventMixin):
    """A single occurrence of a recurring calendar event.

    When creating an expanded event, you must specify the original recurrent
    event.

        >>> dtstart = datetime.datetime(2005, 2, 10, 1, 2)
        >>> duration = datetime.timedelta(hours=3)
        >>> recurrence = DailyRecurrenceRule()
        >>> original = SimpleCalendarEvent(dtstart, duration, "An event",
        ...                                description="Some description",
        ...                                unique_id="some unique id",
        ...                                location="Out in the open",
        ...                                recurrence=recurrence)

        >>> dtstart2 = datetime.datetime(2005, 2, 11, 1, 2)
        >>> evt = ExpandedCalendarEvent(original, dtstart2)

        >>> from zope.interface.verify import verifyObject
        >>> verifyObject(IExpandedCalendarEvent, evt)
        True

    The start date of the event will be the specified one:

        >>> evt.dtstart
        datetime.datetime(2005, 2, 11, 1, 2)

    Other attributes will be the same as in the original event:

        >>> evt.duration
        datetime.timedelta(0, 10800)

        >>> evt.title
        'An event'

        >>> evt.description
        'Some description'

        >>> evt.location
        'Out in the open'

        >>> evt.recurrence
        DailyRecurrenceRule(1, None, None, ())

    Attribute values may not be modified:

        >>> evt.dtstart = 'b0rk'
        Traceback (most recent call last):
        ...
        AttributeError: can't set attribute

        >>> evt.location = 'b0rk'
        Traceback (most recent call last):
        ...
        AttributeError: can't set attribute

    """

    implements(IExpandedCalendarEvent)

    dtstart = property(lambda self: self._dtstart)

    # Syntactic sugar.
    _getter = lambda attr: property(lambda self: getattr(self.original, attr))

    unique_id = _getter('unique_id')
    duration = _getter('duration')
    title = _getter('title')
    description = _getter('description')
    location = _getter('location')
    recurrence = _getter('recurrence')

    def __init__(self, event, dtstart):
        self.original = event
        self._dtstart = dtstart


class RecurrenceRule(object):

    implements(IRecurrenceRule)

    interval = property(lambda self: self._interval)
    count = property(lambda self: self._count)
    until = property(lambda self: self._until)
    exceptions = property(lambda self: self._exceptions)

    # A string that represents the recurrence frequency in iCalendar.
    # Must be overridden by subclasses.
    ical_freq = None

    def __init__(self, interval=1, count=None, until=None, exceptions=()):
        self._interval = interval
        self._count = count
        self._until = until
        self._exceptions = tuple(exceptions)
        self._validate()

    def _validate(self):
        if self.count is not None and self.until is not None:
            raise ValueError("count and until cannot be both set (%s, %s)"
                             % (self.count, self.until))
        if not self.interval >= 1:
            raise ValueError("interval must be a positive integer (got %r)"
                             % (self.interval, ))
        for ex in self.exceptions:
            if not isinstance(ex, datetime.date):
                raise ValueError("Exceptions must be a sequence of"
                                 " datetime.dates (got %r in exceptions)"
                                 % (ex, ))

    def replace(self, interval=Unchanged, count=Unchanged, until=Unchanged,
                exceptions=Unchanged):
        if interval is Unchanged:
            interval = self.interval
        if count is Unchanged:
            count = self.count
        if until is Unchanged:
            until = self.until
        if exceptions is Unchanged:
            exceptions = self.exceptions
        return self.__class__(interval, count, until, exceptions)

    def __repr__(self):
        return '%s(%r, %r, %r, %r)' % (self.__class__.__name__, self.interval,
                                       self.count, self.until,
                                       self.exceptions)

    def _tupleForComparison(self):
        return (self.__class__.__name__, self.interval, self.count,
                self.until, tuple(self.exceptions))

    def __eq__(self, other):
        """See if self == other."""
        if isinstance(other, RecurrenceRule):
            return self._tupleForComparison() == other._tupleForComparison()
        else:
            return False

    def __ne__(self, other):
        """See if self != other."""
        return not self == other

    def __hash__(self):
        """Return the hash value of this recurrence rule.

        It is guaranteed that if recurrence rules compare equal, hash will
        return the same value.
        """
        return hash(self._tupleForComparison())

    def apply(self, event, enddate=None):
        """Generator that generates dates of recurrences"""
        cur = event.dtstart.date()
        count = 0
        while True:
            if ((enddate and cur > enddate) or
                (self.count is not None and count >= self.count) or
                (self.until and cur > self.until)):
                break
            if cur not in self.exceptions:
                yield cur
            count += 1
            cur = self._nextRecurrence(cur)

    def _nextRecurrence(self, date):
        """Add the basic step of recurrence to the date."""
        return date + self.interval * date.resolution

    def iCalRepresentation(self, dtstart):
        """See IRecurrenceRule"""
        assert self.ical_freq, 'RecurrenceRule.ical_freq must be overridden'

        if self.count:
            args = 'COUNT=%d;' % self.count
        elif self.until:
            args = 'UNTIL=%s;' % ical_datetime(self.until)
        else:
            args = ''
        extra_args = self._iCalArgs(dtstart)
        if extra_args is not None:
            args += extra_args + ';'

        result = ['RRULE:FREQ=%s;%sINTERVAL=%d'
                  % (self.ical_freq, args, self.interval)]

        if self.exceptions:
            # Exceptions should include the exact time portion as well
            # (this was implemented in revision 1860), however,
            # Mozilla Calendar refuses to work with such exceptions.
            dates = ','.join([ical_date(d) for d in self.exceptions])
            result.append('EXDATE;VALUE=DATE:' + dates)
        return result

    def _iCalArgs(self, dtstart):
        """Return extra iCal arguments as a string.

        Should be overridden by child classes that have specific arguments.
        The returned string must not include the semicolon separator.
        If None is returned, no arguments are inserted.
        """
        pass


class DailyRecurrenceRule(RecurrenceRule):
    """Daily recurrence rule.

    Immutable hashable object.
    """
    implements(IDailyRecurrenceRule)

    ical_freq = 'DAILY'


class YearlyRecurrenceRule(RecurrenceRule):
    """Yearly recurrence rule.

    Immutable hashable object.
    """
    implements(IYearlyRecurrenceRule)

    ical_freq = 'YEARLY'

    def _nextRecurrence(self, date):
        """Adds the basic step of recurrence to the date"""
        nextyear = date.year + self.interval
        return date.replace(year=nextyear)

    def _iCalArgs(self, dtstart):
        """Return iCalendar parameters specific to monthly reccurence."""
        # KOrganizer wants explicit BYMONTH and BYMONTHDAY arguments.
        # Maybe it is a good idea to add them for the sake of explicitness.


class WeeklyRecurrenceRule(RecurrenceRule):
    """Weekly recurrence rule."""

    implements(IWeeklyRecurrenceRule)

    weekdays = property(lambda self: self._weekdays)

    ical_freq = 'WEEKLY'

    def __init__(self, interval=1, count=None, until=None, exceptions=(),
                 weekdays=()):
        self._interval = interval
        self._count = count
        self._until = until
        self._exceptions = tuple(exceptions)
        self._weekdays = tuple(weekdays)
        self._validate()

    def __repr__(self):
        return '%s(%r, %r, %r, %r, %r)' % (
            self.__class__.__name__, self.interval,
            self.count, self.until, self.exceptions, self.weekdays)

    def _validate(self):
        RecurrenceRule._validate(self)
        for dow in self.weekdays:
            if not isinstance(dow, int) or not 0 <= dow <= 6:
                raise ValueError("Day of week must be an integer 0..6 (got %r)"
                                 % (dow, ))

    def replace(self, interval=Unchanged, count=Unchanged, until=Unchanged,
                exceptions=Unchanged, weekdays=Unchanged, monthly=Unchanged):
        if interval is Unchanged:
            interval = self.interval
        if count is Unchanged:
            count = self.count
        if until is Unchanged:
            until = self.until
        if exceptions is Unchanged:
            exceptions = self.exceptions
        if weekdays is Unchanged:
            weekdays = self.weekdays
        return self.__class__(interval, count, until, exceptions, weekdays)

    def _tupleForComparison(self):
        return (self.__class__.__name__, self.interval, self.count,
                self.until, self.exceptions, self.weekdays)

    def apply(self, event, enddate=None):
        """Generate dates of recurrences."""
        cur = start = event.dtstart.date()
        count = 0
        weekdays = Set(self.weekdays)
        weekdays.add(event.dtstart.weekday())
        while True:
            if ((enddate and cur > enddate) or
                (self.count is not None and count >= self.count) or
                (self.until and cur > self.until)):
                break
            # Check that this is the correct week and
            # the desired weekday
            if (weekspan(start, cur) % self.interval == 0 and
                cur.weekday() in weekdays):
                if cur not in self.exceptions:
                    yield cur
                count += 1
            cur = self._nextRecurrence(cur)

    def _nextRecurrence(self, date):
        """Add the basic step of recurrence to the date."""
        return date + date.resolution

    def _iCalArgs(self, dtstart):
        """Return iCalendar parameters specific to monthly reccurence."""
        if self.weekdays:
            return 'BYDAY=' + ','.join([ical_weekdays[weekday]
                                        for weekday in self.weekdays])


class MonthlyRecurrenceRule(RecurrenceRule):
    """Monthly recurrence rule.

    Immutable hashable object.
    """
    implements(IMonthlyRecurrenceRule)

    monthly = property(lambda self: self._monthly)

    ical_freq = 'MONTHLY'

    def __init__(self, interval=1, count=None, until=None, exceptions=(),
                 monthly="monthday"):
        self._interval = interval
        self._count = count
        self._until = until
        self._exceptions = tuple(exceptions)
        self._monthly = monthly
        self._validate()

    def __repr__(self):
        return '%s(%r, %r, %r, %r, %r)' % (
            self.__class__.__name__, self.interval,
            self.count, self.until, self.exceptions, self.monthly)

    def _validate(self):
        RecurrenceRule._validate(self)
        if self.monthly not in ("monthday", "weekday", "lastweekday"):
            raise ValueError("monthly must be one of 'monthday', 'weekday',"
                             " 'lastweekday'. Got %r" % (self.monthly, ))

    def replace(self, interval=Unchanged, count=Unchanged, until=Unchanged,
                exceptions=Unchanged, weekdays=Unchanged, monthly=Unchanged):
        if interval is Unchanged:
            interval = self.interval
        if count is Unchanged:
            count = self.count
        if until is Unchanged:
            until = self.until
        if exceptions is Unchanged:
            exceptions = tuple(self.exceptions)
        if monthly is Unchanged:
            monthly = self.monthly
        return self.__class__(interval, count, until, exceptions, monthly)

    def _tupleForComparison(self):
        return (self.__class__.__name__, self.interval, self.count,
                self.until, self.exceptions, self.monthly)

    def _nextRecurrence(self, date):
        """Add basic step of recurrence to the date."""
        year = date.year
        month = date.month
        while True:
            year, month = divmod(year * 12 + month - 1 + self.interval, 12)
            month += 1 # convert 0..11 to 1..12
            try:
                return date.replace(year=year, month=month)
            except ValueError:
                continue

    def apply(self, event, enddate=None):
        if self.monthly == 'monthday':
            for date in  RecurrenceRule.apply(self, event, enddate):
                yield date
        elif self.monthly == 'weekday':
            for date in self._applyWeekday(event, enddate):
                yield date
        elif self.monthly == 'lastweekday':
            for date in self._applyLastWeekday(event, enddate):
                yield date

    def _applyWeekday(self, event, enddate=None):
        """Generator that generates dates of recurrences."""
        cur = start = event.dtstart.date()
        count = 0
        year = start.year
        month = start.month
        weekday = start.weekday()
        index = start.day / 7 + 1

        while True:
            cur = monthindex(year, month, index, weekday)
            if ((enddate and cur > enddate) or
                (self.count is not None and count >= self.count) or
                (self.until and cur > self.until)):
                break
            if cur not in self.exceptions:
                yield cur
            count += 1
            # Next month, please.
            year, month = divmod(year * 12 + month + self.interval - 1, 12)
            month += 1

    def _applyLastWeekday(self, event, enddate=None):
        """Generator that generates dates of recurrences."""
        cur = start = event.dtstart.date()
        count = 0
        year = start.year
        month = start.month
        weekday = start.weekday()
        daysinmonth = calendar.monthrange(year, month)[1]
        index = (start.day - daysinmonth - 1) / 7

        while True:
            cur = monthindex(year, month, index, weekday)
            if ((enddate and cur > enddate) or
                (self.count is not None and count >= self.count) or
                (self.until and cur > self.until)):
                break
            if cur not in self.exceptions:
                yield cur
            count += 1
            # Next month, please.
            year, month = divmod(year * 12 + month + self.interval - 1, 12)
            month += 1

    def _iCalArgs(self, dtstart):
        """Return iCalendar parameters specific to monthly reccurence."""
        if self.monthly == 'monthday':
            return 'BYMONTHDAY=%d' % dtstart.day
        elif self.monthly == 'weekday':
            week = dtstart.day / 7 + 1
            return 'BYDAY=%d%s' % (week, ical_weekdays[dtstart.weekday()])
        elif self.monthly == 'lastweekday':
            return 'BYDAY=-1%s' % ical_weekdays[dtstart.weekday()]
        else:
            raise NotImplementedError(self.monthly)


#
# Calendaring functions
#


def weekspan(first, second):
    """Return the distance in weeks between dates.

    For days in the same ISO week, the result is 0.
    For days in adjacent weeks, it is 1, etc.
    """
    firstmonday = first - datetime.timedelta(first.weekday())
    secondmonday = second - datetime.timedelta(second.weekday())
    return (secondmonday - firstmonday).days / 7


def monthindex(year, month, index, weekday):
    """Return the (index)th weekday of the month in a year.

    May return a date beyond month if index is too big.
    """
    # make corrections for the negative index
    # if index is negative, we're really interested in the next month's
    # first weekday, minus n weeks
    if index < 0:
        yeardelta, month = divmod(month, 12)
        year += yeardelta
        month += 1
        index += 1

    # find first weekday
    for day in range(1, 8):
        if datetime.date(year, month, day).weekday() == weekday:
            break

    # calculate the timedelta to the index-th
    shift = (index - 1) * datetime.timedelta(7)

    # return the result
    return datetime.date(year, month, day) + shift
