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
SchoolTool application views.

$Id$
"""

import urllib
import base64
import calendar
from datetime import datetime, date, time, timedelta
from sets import Set

import transaction
from pytz import timezone, utc
from zope.component import queryMultiAdapter, adapts
from zope.component import subscribers
from zope.event import notify
from zope.interface import implements, Interface
from zope.i18n import translate
from zope.publisher.interfaces.browser import IBrowserPublisher
from zope.publisher.interfaces import NotFound
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy
from zope.security.checker import canAccess
from zope.schema import Date, TextLine, Choice, Int, Bool, List, Text
from zope.schema.interfaces import RequiredMissing, ConstraintNotSatisfied
from zope.app import zapi
from zope.annotation.interfaces import IAnnotations
from zope.lifecycleevent import ObjectModifiedEvent
from zope.app.form.browser.add import AddView
from zope.app.form.browser.editview import EditView
from zope.app.form.utility import setUpWidgets
from zope.app.form.interfaces import ConversionError
from zope.app.form.interfaces import IWidgetInputError, IInputWidget
from zope.app.form.interfaces import WidgetInputError, WidgetsError
from zope.app.form.utility import getWidgetsData
from zope.publisher.browser import BrowserView
from zope.traversing.browser.absoluteurl import absoluteURL
from zope.filerepresentation.interfaces import IWriteFile, IReadFile
from zope.app.session.interfaces import ISession
from zope.traversing.api import getPath
from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile
from zope.html.field import HtmlFragment
from zc.table.column import GetterColumn
from zc.table import table


from schooltool import SchoolToolMessage as _

from schooltool.skin.interfaces import IBreadcrumbInfo
from schooltool.skin import breadcrumbs
from schooltool.skin.table import LabelColumn, CheckboxColumn
from schooltool.skin.interfaces import IFilterWidget
from schooltool.app.browser import ViewPreferences, same
from schooltool.app.browser import pdfcal
from schooltool.app.browser.overlay import CalendarOverlayView
from schooltool.app.browser.interfaces import ICalendarProvider
from schooltool.app.browser.interfaces import IEventForDisplay
from schooltool.app.interfaces import ISchoolToolCalendarEvent
from schooltool.app.app import getSchoolToolApplication
from schooltool.app.interfaces import ISchoolToolCalendar
from schooltool.app.interfaces import IHaveCalendar, IShowTimetables
from schooltool.batching import Batch
from schooltool.calendar.interfaces import ICalendar
from schooltool.calendar.interfaces import IEditCalendar
from schooltool.calendar.recurrent import DailyRecurrenceRule
from schooltool.calendar.recurrent import YearlyRecurrenceRule
from schooltool.calendar.recurrent import MonthlyRecurrenceRule
from schooltool.calendar.recurrent import WeeklyRecurrenceRule
from schooltool.calendar.interfaces import IDailyRecurrenceRule
from schooltool.calendar.interfaces import IYearlyRecurrenceRule
from schooltool.calendar.interfaces import IMonthlyRecurrenceRule
from schooltool.calendar.interfaces import IWeeklyRecurrenceRule
from schooltool.calendar.utils import parse_date, parse_datetimetz
from schooltool.calendar.utils import parse_time, weeknum_bounds
from schooltool.calendar.utils import week_start, prev_month, next_month
from schooltool.course.interfaces import ISection
from schooltool.person.interfaces import IPerson, IPersonPreferences
from schooltool.person.interfaces import vocabulary
from schooltool.resource.interfaces import IResource
from schooltool.timetable.interfaces import ICompositeTimetables
from schooltool.term.term import getTermForDate
from schooltool.app.interfaces import ISchoolToolApplication


#
# Constants
#

month_names = {
    1: _("January"), 2: _("February"), 3: _("March"),
    4: _("April"), 5: _("May"), 6: _("June"),
    7: _("July"), 8: _("August"), 9: _("September"),
    10: _("October"), 11: _("November"), 12: _("December")}

day_of_week_names = {
    0: _("Monday"), 1: _("Tuesday"), 2: _("Wednesday"), 3: _("Thursday"),
    4: _("Friday"), 5: _("Saturday"), 6: _("Sunday")}

short_day_of_week_names = {
    0: _("Mon"), 1: _("Tue"), 2: _("Wed"), 3: _("Thu"),
    4: _("Fri"), 5: _("Sat"), 6: _("Sun"),
}


#
# Traversal
#

class ToCalendarTraverser(object):
    """A traverser that allows to traverse to a calendar owner's calendar."""

    adapts(IHaveCalendar)
    implements(IBrowserPublisher)

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def publishTraverse(self, request, name):
        if name == 'calendar':
            return ISchoolToolCalendar(self.context)
        elif name in ('calendar.ics', 'calendar.vfb'):
            calendar = ISchoolToolCalendar(self.context)
            view = queryMultiAdapter((calendar, request), name=name)
            if view is not None:
                return view

        raise NotFound(self.context, name, request)

    def browserDefault(self, request):
        return self.context, ('index.html', )


class CalendarTraverser(object):
    """A smart calendar traverser that can handle dates in the URL."""

    adapts(ICalendar)
    implements(IBrowserPublisher)

    queryMultiAdapter = staticmethod(queryMultiAdapter)

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def browserDefault(self, request):
        return self.context, ('daily.html', )

    def publishTraverse(self, request, name):
        view_name = self.getHTMLViewByDate(request, name)
        if not view_name:
            view_name = self.getPDFViewByDate(request, name)
        if view_name:
            return self.queryMultiAdapter((self.context, request),
                                          name=view_name)

        view = queryMultiAdapter((self.context, request), name=name)
        if view is not None:
            return view

        try:
            event_id = base64.decodestring(name)
        except:
            raise NotFound(self.context, name, request)

        try:
            return self.context.find(event_id)
        except KeyError:
            raise NotFound(self.context, event_id, request)

    def getHTMLViewByDate(self, request, name):
        """Get HTML view name from URL component."""
        return self.getViewByDate(request, name, 'html')

    def getPDFViewByDate(self, request, name):
        """Get PDF view name from URL component."""
        if not name.endswith('.pdf'):
            return None
        name = name[:-4] # strip off the .pdf
        view_name = self.getViewByDate(request, name, 'pdf')
        if view_name == 'yearly.pdf':
            return None # the yearly PDF view is not available
        else:
            return view_name

    def getViewByDate(self, request, name, suffix):
        """Get view name from URL component."""
        parts = name.split('-')

        if len(parts) == 2 and parts[1].startswith('w'): # a week was given
            try:
                year = int(parts[0])
                week = int(parts[1][1:])
            except ValueError:
                return
            request.form['date'] = self.getWeek(year, week).isoformat()
            return 'weekly.%s' % suffix

        # a year, month or day might have been given
        try:
            parts = [int(part) for part in parts]
        except ValueError:
            return
        if not parts:
            return
        parts = tuple(parts)

        if not (1900 < parts[0] < 2100):
            return

        if len(parts) == 1:
            request.form['date'] = "%d-01-01" % parts
            return 'yearly.%s' % suffix
        elif len(parts) == 2:
            request.form['date'] = "%d-%02d-01" % parts
            return 'monthly.%s' % suffix
        elif len(parts) == 3:
            request.form['date'] = "%d-%02d-%02d" % parts
            return 'daily.%s' % suffix

    def getWeek(self, year, week):
        """Get the start of a week by week number.

        The Monday of the given week is returned as a datetime.date.

            >>> traverser = CalendarTraverser(None, None)
            >>> traverser.getWeek(2002, 11)
            datetime.date(2002, 3, 11)
            >>> traverser.getWeek(2005, 1)
            datetime.date(2005, 1, 3)
            >>> traverser.getWeek(2005, 52)
            datetime.date(2005, 12, 26)

        """
        return weeknum_bounds(year, week)[0]


#
# Calendar displaying backend
#

class EventForDisplay(object):
    """A decorated calendar event."""

    implements(IEventForDisplay)

    cssClass = 'event'  # at the moment no other classes are used

    def __init__(self, event, request, color1, color2, source_calendar,
                 timezone):
        self.request = request
        self.source_calendar = source_calendar
        if canAccess(source_calendar, '__iter__'):
            # Due to limitations in the default Zope 3 security
            # policy, a calendar event inherits permissions from the
            # calendar of its __parent__.  However if there's an event
            # that books a resource, and the authenticated user has
            # schooltool.view access for the resource's calendar, she
            # should be able to view this event when it comes from the
            # resource's calendar.  For this reason we have to remove
            # the security proxy and check the permission manually.
            event = removeSecurityProxy(event)
        self.context = event
        self.dtend = event.dtstart + event.duration
        self.color1 = color1
        self.color2 = color2
        self.shortTitle = self.title
        if len(self.title) > 16:
            self.shortTitle = self.title[:15] + '...'
        self.dtstarttz = event.dtstart.astimezone(timezone)
        self.dtendtz = self.dtend.astimezone(timezone)

    def __cmp__(self, other):
        return cmp(self.context.dtstart, other.context.dtstart)

    def __getattr__(self, name):
        return getattr(self.context, name)

    def getBooker(self):
        """Return the booker."""
        event = ISchoolToolCalendarEvent(self.context, None)
        if event:
            return event.owner

    def getBookedResources(self):
        """Return the list of booked resources."""
        booker = ISchoolToolCalendarEvent(self.context, None)
        if booker:
            return booker.resources
        else:
            return ()

    def viewLink(self):
        """Return the URL where you can view this event.

        Returns None if the event is not viewable (e.g. it is a timetable
        event).
        """
        if self.context.__parent__ is None:
            return None

        if IEditCalendar.providedBy(self.source_calendar):
            # display the link of the source calendar (the event is a
            # booking event)
            return '%s/%s' % (zapi.absoluteURL(self.source_calendar, self.request),
                              urllib.quote(self.__name__))

        # if event is comming from an immutable (readonly) calendar,
        # display the absolute url of the event itself
        return zapi.absoluteURL(self, self.request)


    def editLink(self):
        """Return the URL where you can edit this event.

        Returns None if the event is not editable (e.g. it is a timetable
        event).
        """
        if self.context.__parent__ is None:
            return None
        return '%s/edit.html?date=%s' % (
                        zapi.absoluteURL(self.context, self.request),
                        self.dtstarttz.strftime('%Y-%m-%d'))

    def deleteLink(self):
        """Return the URL where you can delete this event.

        Returns None if the event is not deletable (e.g. it is a timetable
        event).
        """
        if self.context.__parent__ is None:
            return None
        return '%s/delete.html?event_id=%s&date=%s' % (
                        zapi.absoluteURL(self.source_calendar, self.request),
                        self.unique_id,
                        self.dtstarttz.strftime('%Y-%m-%d'))

    def bookingLink(self):
        """Return the URL where you can book resources for this event.

        Returns None if you can't do that.
        """
        if self.context.__parent__ is None:
            return None
        return '%s/booking.html?date=%s' % (
                        zapi.absoluteURL(self.context, self.request),
                        self.dtstarttz.strftime('%Y-%m-%d'))

    def renderShort(self):
        """Short representation of the event for the monthly view."""
        if self.dtstarttz.date() == self.dtendtz.date():
            fmt = '%H:%M'
        else:
            fmt = '%b&nbsp;%d'
        return "%s (%s&ndash;%s)" % (self.shortTitle,
                                     self.dtstarttz.strftime(fmt),
                                     self.dtendtz.strftime(fmt))


class CalendarDay(object):
    """A single day in a calendar.

    Attributes:
       'date'   -- date of the day (a datetime.date instance)
       'title'  -- day title, including weekday and date.
       'events' -- list of events that took place that day, sorted by start
                   time (in ascending order).
    """

    def __init__(self, date, events=None):
        if events is None:
            events = []
        self.date = date
        self.events = events
        day_of_week = day_of_week_names[date.weekday()]

    def __cmp__(self, other):
        return cmp(self.date, other.date)

    def today(self):
        """Return 'today' if self.date is today, otherwise return ''."""
        # XXX shouldn't use date.today; it depends on the server's timezone
        # which may not match user expectations
        return self.date == date.today() and 'today' or ''


#
# Calendar display views
#

class CalendarViewBase(BrowserView):
    """A base class for the calendar views.

    This class provides functionality that is useful to several calendar views.
    """

    __used_for__ = ISchoolToolCalendar

    # Which day is considered to be the first day of the week (0 = Monday,
    # 6 = Sunday).  Based on authenticated user preference, defaults to Monday

    def __init__(self, context, request):
        self.context = context
        self.request = request

        # XXX Clean this up (use self.preferences in this and subclasses)
        prefs = ViewPreferences(request)
        self.first_day_of_week = prefs.first_day_of_week
        self.time_fmt = prefs.timeformat
        self.dateformat = prefs.dateformat
        self.timezone = prefs.timezone

        self._days_cache = None

    def pdfURL(self):
        if pdfcal.disabled:
            return None
        else:
            assert self.cal_type != 'yearly'
            url = self.calURL(self.cal_type, cursor=self.cursor)
            return url + '.pdf'

    def dayTitle(self, day):
        formatter = zapi.getMultiAdapter((day, self.request), name='fullDate')
        return formatter()

    __url = None

    def calURL(self, cal_type, cursor=None):
        """Construct a URL to a calendar at cursor."""
        if cursor is None:
            session = ISession(self.request)['calendar']
            dt = session.get('last_visited_day')
            if dt and self.inCurrentPeriod(dt):
                cursor = dt
            else:
                cursor = self.cursor

        if self.__url is None:
            self.__url = absoluteURL(self.context, self.request)

        if cal_type == 'daily':
            dt = cursor.isoformat()
        elif cal_type == 'weekly':
            dt = '%04d-w%02d' % cursor.isocalendar()[:2]
        elif cal_type == 'monthly':
            dt = cursor.strftime('%Y-%m')
        elif cal_type == 'yearly':
            dt = str(cursor.year)
        else:
            raise ValueError(cal_type)

        return '%s/%s' % (self.__url, dt)

    def _initDaysCache(self):
        """Initialize the _days_cache attribute.

        When ``update`` figures out which time period will be displayed to the
        user, it calls ``_initDaysCache`` to give the view a chance to
        precompute the calendar events for the time interval.

        The base implementation designates three months around self.cursor as
        the time interval for caching.
        """
        # The calendar portlet will always want three months around self.cursor
        start_of_prev_month = prev_month(self.cursor)
        first = week_start(start_of_prev_month, self.first_day_of_week)
        end_of_next_month = next_month(next_month(self.cursor)) - timedelta(1)
        last = week_start(end_of_next_month,
                          self.first_day_of_week) + timedelta(7)
        self._days_cache = DaysCache(self._getDays, first, last)

    def update(self):
        """Figure out which date we're supposed to be showing.

        Can extract date from the request or the session.  Defaults on today.
        """
        session = ISession(self.request)['calendar']
        dt = session.get('last_visited_day')

        if 'date' not in self.request:
            # XXX shouldn't use date.today; it depends on the server's timezone
            # which may not match user expectations
            self.cursor = dt or date.today()
        else:
            # TODO: It would be nice not to b0rk when the date is invalid but
            # fall back to the current date, as if the date had not been
            # specified.
            self.cursor = parse_date(self.request['date'])

        if not (dt and self.inCurrentPeriod(dt)):
            session['last_visited_day'] = self.cursor

        self._initDaysCache()

    def inCurrentPeriod(self, dt):
        """Return True if dt is in the period currently being shown."""
        raise NotImplementedError("override in subclasses")

    def pigeonhole(self, intervals, days):
        """Sort CalendarDay objects into date intervals.

        Can be used to sort a list of CalendarDay objects into weeks,
        months, quarters etc.

        `intervals` is a list of date pairs that define half-open time
        intervals (the start date is inclusive, and the end date is
        exclusive).  Intervals can overlap.

        Returns a list of CalendarDay object lists -- one list for
        each interval.
        """
        results = []
        for start, end in intervals:
            results.append([day for day in days if start <= day.date < end])
        return results

    def getWeek(self, dt):
        """Return the week that contains the day dt.

        Returns a list of CalendarDay objects.
        """
        start = week_start(dt, self.first_day_of_week)
        end = start + timedelta(7)
        return self.getDays(start, end)

    def getMonth(self, dt, days=None):
        """Return a nested list of days in the month that contains dt.

        Returns a list of lists of date objects.  Days in neighbouring
        months are included if they fall into a week that contains days in
        the current month.
        """
        start_of_next_month = next_month(dt)
        start_of_week = week_start(dt.replace(day=1), self.first_day_of_week)
        start_of_display_month = start_of_week

        week_intervals = []
        while start_of_week < start_of_next_month:
            start_of_next_week = start_of_week + timedelta(7)
            week_intervals.append((start_of_week, start_of_next_week))
            start_of_week = start_of_next_week

        end_of_display_month = start_of_week
        if not days:
            days = self.getDays(start_of_display_month, end_of_display_month)
        # Make sure the cache contains all the days we're interested in
        assert days[0].date <= start_of_display_month, 'not enough days'
        assert days[-1].date >= end_of_display_month - timedelta(1), 'not enough days'
        weeks = self.pigeonhole(week_intervals, days)
        return weeks

    def getYear(self, dt):
        """Return the current year.

        This returns a list of quarters, each quarter is a list of months,
        each month is a list of weeks, and each week is a list of CalendarDays.
        """
        first_day_of_year = date(dt.year, 1, 1)
        year_start_day_padded_weeks = week_start(first_day_of_year,
                                                 self.first_day_of_week)
        last_day_of_year = date(dt.year, 12, 31)
        year_end_day_padded_weeks = week_start(last_day_of_year,
                                               self.first_day_of_week) + timedelta(7)

        day_cache = self.getDays(year_start_day_padded_weeks,
                                 year_end_day_padded_weeks)

        quarters = []
        for q in range(4):
            quarter = [self.getMonth(date(dt.year, month + (q * 3), 1),
                                     day_cache)
                       for month in range(1, 4)]
            quarters.append(quarter)
        return quarters

    _day_events = None # cache

    def dayEvents(self, date):
        """Return events for a day sorted by start time.

        Events spanning several days and overlapping with this day
        are included.
        """
        if self._day_events is None:
            self._day_events = {}

        if date in self._day_events:
            day = self._day_events[date]
        else:
            day = self.getDays(date, date + timedelta(1))[0]
            self._day_events[date] = day
        return day.events

    _calendars = None # cache

    def getCalendars(self):
        providers = subscribers((self.context, self.request), ICalendarProvider)

        if self._calendars is None:
            result = []
            for provider in providers:
                result += provider.getCalendars()
            self._calendars = result
        return self._calendars

    def getEvents(self, start_dt, end_dt):
        """Get a list of EventForDisplay objects for a selected time interval.

        `start_dt` and `end_dt` (datetime objects) are bounds (half-open) for
        the result.
        """
        for calendar, color1, color2 in self.getCalendars():
            for event in calendar.expand(start_dt, end_dt):
                if (same(event.__parent__, self.context) and
                    calendar is not self.context):
                    # Skip resource booking events (coming from
                    # overlaid calendars) if they were booked by the
                    # person whose calendar we are viewing.
                    # removeSecurityProxy(event.__parent__) and
                    # removeSecurityProxy(self.context) are needed so we
                    # could compare them.
                    continue
                yield EventForDisplay(event, self.request, color1, color2,
                                      calendar, self.timezone)

    def getDays(self, start, end):
        """Get a list of CalendarDay objects for a selected period of time.

        Uses the _days_cache.

        `start` and `end` (date objects) are bounds (half-open) for the result.

        Events spanning more than one day get included in all days they
        overlap.
        """
        if self._days_cache is None:
            return self._getDays(start, end)
        else:
            return self._days_cache.getDays(start, end)

    def _getDays(self, start, end):
        """Get a list of CalendarDay objects for a selected period of time.

        No caching.

        `start` and `end` (date objects) are bounds (half-open) for the result.

        Events spanning more than one day get included in all days they
        overlap.
        """
        events = {}
        day = start
        while day < end:
            events[day] = []
            day += timedelta(1)

        # We have date objects, but ICalendar.expand needs datetime objects
        start_dt = self.timezone.localize(datetime.combine(start, time()))
        end_dt = self.timezone.localize(datetime.combine(end, time()))
        for event in self.getEvents(start_dt, end_dt):
            #  day1  day2  day3  day4  day5
            # |.....|.....|.....|.....|.....|
            # |     |  [-- event --)  |     |
            # |     |  ^  |     |  ^  |     |
            # |     |  `dtstart |  `dtend   |
            #        ^^^^^       ^^^^^
            #      first_day   last_day
            #
            # dtstart and dtend are datetime.datetime instances and point to
            # time instants.  first_day and last_day are datetime.date
            # instances and point to whole days.  Also note that [dtstart,
            # dtend) is a half-open interval, therefore
            #   last_day == dtend.date() - 1 day   when dtend.time() is 00:00
            #                                      and duration > 0
            #               dtend.date()           otherwise
            dtend = event.dtend
            if event.allday:
                first_day = event.dtstart.date()
                last_day = max(first_day, (dtend - dtend.resolution).date())
            else:
                first_day = event.dtstart.astimezone(self.timezone).date()
                last_day = max(first_day, (dtend.astimezone(self.timezone) -
                                           dtend.resolution).date())
            # Loop through the intersection of two day ranges:
            #    [start, end) intersect [first_day, last_day]
            # Note that the first interval is half-open, but the second one is
            # closed.  Since we're dealing with whole days,
            #    [first_day, last_day] == [first_day, last_day + 1 day)
            day = max(start, first_day)
            limit = min(end, last_day + timedelta(1))
            while day < limit:
                events[day].append(event)
                day += timedelta(1)

        days = []
        day = start
        while day < end:
            events[day].sort()
            days.append(CalendarDay(day, events[day]))
            day += timedelta(1)
        return days

    def prevMonth(self):
        """Return the first day of the previous month."""
        return prev_month(self.cursor)

    def nextMonth(self):
        """Return the first day of the next month."""
        return next_month(self.cursor)

    def prevDay(self):
        return self.cursor - timedelta(1)

    def nextDay(self):
        return self.cursor + timedelta(1)

    def getJumpToYears(self):
        """Return jump targets for five years centered on the current year."""
        this_year = datetime.today().year
        return [{'label': year,
                 'href': self.calURL('yearly', date(year, 1, 1))}
                for year in range(this_year - 2, this_year + 3)]

    def getJumpToMonths(self):
        """Return a list of months for the drop down in the jump portlet."""
        year = self.cursor.year
        return [{'label': v,
                 'href': self.calURL('monthly', date(year, k, 1))}
                for k, v in month_names.items()]

    def monthTitle(self, date):
        return month_names[date.month]

    def renderRow(self, week, month):
        """Do some HTML rendering in Python for performance.

        This gains us 0.4 seconds out of 0.6 on my machine.
        Here is the original piece of ZPT:

         <td class="cal_yearly_day" tal:repeat="day week">
          <a tal:condition="python:day.date.month == month[1][0].date.month"
             tal:content="day/date/day"
             tal:attributes="href python:view.calURL('daily', day.date);
                             class python:(len(day.events) > 0
                                           and 'cal_yearly_day_busy'
                                           or  'cal_yearly_day')
                                        + (day.today() and ' today' or '')"/>
         </td>
        """
        result = []

        for day in week:
            result.append('<td class="cal_yearly_day">')
            if day.date.month == month:
                if len(day.events):
                    cssClass = 'cal_yearly_day_busy'
                else:
                    cssClass = 'cal_yearly_day'
                if day.today():
                    cssClass += ' today'
                # Let us hope that URLs will not contain < > & or "
                # This is somewhat related to
                #   http://issues.schooltool.org/issue96
                result.append('<a href="%s" class="%s">%s</a>' %
                              (self.calURL('daily', day.date), cssClass,
                               day.date.day))
            result.append('</td>')
        return "\n".join(result)

    def canAddEvents(self):
        """Return True if current viewer can add events to this calendar."""
        return canAccess(self.context, "addEvent")

    def canRemoveEvents(self):
        """Return True if current viewer can remove events to this calendar."""
        return canAccess(self.context, "removeEvent")


class DaysCache(object):
    """A cache of calendar days.

    Since the expansion of recurrent calendar events, and the pigeonholing of
    calendar events into days is an expensive task, it is better to compute
    the calendar days of a single larger period of time, and then refer
    to subsets of the result.

    DaysCache provides an object that is able to do so.  The goal here is that
    any view will need perform the expensive computation only once or twice.
    """

    def __init__(self, expensive_getDays, cache_first, cache_last):
        """Create a cache.

        ``expensive_getDays`` is a function that takes a half-open date range
        and returns a list of CalendarDay objects.

        ``cache_first`` and ``cache_last`` provide the initial approximation
        of the date range that will be needed in the future.  You may later
        extend the cache interval by calling ``extend``.
        """
        self.expensive_getDays = expensive_getDays
        self.cache_first = cache_first
        self.cache_last = cache_last
        self._cache = None

    def extend(self, first, last):
        """Extend the cache.

        You should call ``extend`` before any calls to ``getDays``, and not
        after.
        """
        self.cache_first = min(self.cache_first, first)
        self.cache_last = max(self.cache_last, last)

    def getDays(self, first, last):
        """Return a list of calendar days from ``first`` to ``last``.

        If the interval from ``first`` to ``last`` falls into the cached
        range, and the cache is already computed, this operation becomes
        fast.

        If the interval is not in cache, delegates to the expensive_getDays
        computation.
        """
        assert first <= last, 'invalid date range: %s..%s' % (first, last)
        if first >= self.cache_first and last <= self.cache_last:
            if self._cache is None:
                self._cache = self.expensive_getDays(self.cache_first,
                                                     self.cache_last)
            first_idx = (first - self.cache_first).days
            last_idx = (last - self.cache_first).days
            return self._cache[first_idx:last_idx]
        else:
            return self.expensive_getDays(first, last)


class WeeklyCalendarView(CalendarViewBase):
    """A view that shows one week of the calendar."""

    __used_for__ = ISchoolToolCalendar

    cal_type = 'weekly'

    next_title = _("Next week")
    current_title = _("Current week")
    prev_title = _("Previous week")

    def inCurrentPeriod(self, dt):
        # XXX wrong if week starts on Sunday.
        return dt.isocalendar()[:2] == self.cursor.isocalendar()[:2]

    def title(self):
        month_name_msgid = month_names[self.cursor.month]
        month_name = translate(month_name_msgid, context=self.request)
        msg = _('${month}, ${year} (week ${week})',
                mapping = {'month': month_name,
                           'year': self.cursor.year,
                           'week': self.cursor.isocalendar()[1]})
        return msg

    def prev(self):
        """Return the link for the previous week."""
        return self.calURL('weekly', self.cursor - timedelta(weeks=1))

    def current(self):
        """Return the link for the current week."""
        # XXX shouldn't use date.today; it depends on the server's timezone
        # which may not match user expectations
        return self.calURL('weekly', date.today())

    def next(self):
        """Return the link for the next week."""
        return self.calURL('weekly', self.cursor + timedelta(weeks=1))

    def getCurrentWeek(self):
        """Return the current week as a list of CalendarDay objects."""
        return self.getWeek(self.cursor)


class AtomCalendarView(WeeklyCalendarView):
    """View the upcoming week's events in Atom formatted xml."""

    def getCurrentWeek(self):
        """Return the current week as a list of CalendarDay objects."""
        # XXX shouldn't use date.today; it depends on the server's timezone
        # which may not match user expectations
        return self.getWeek(date.today())

    def w3cdtf_datetime(self, dt):
        # XXX: shouldn't assume the datetime is in UTC
        assert dt.tzname() == 'UTC'
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def w3cdtf_datetime_now(self):
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


class MonthlyCalendarView(CalendarViewBase):
    """Monthly calendar view."""

    __used_for__ = ISchoolToolCalendar

    cal_type = 'monthly'

    next_title = _("Next month")
    current_title = _("Current month")
    prev_title = _("Previous month")

    def inCurrentPeriod(self, dt):
        return (dt.year, dt.month) == (self.cursor.year, self.cursor.month)

    def title(self):
        month_name_msgid = month_names[self.cursor.month]
        month_name = translate(month_name_msgid, context=self.request)
        msg = _('${month}, ${year}',
                mapping={'month': month_name, 'year': self.cursor.year})
        return msg

    def prev(self):
        """Return the link for the previous month."""
        return self.calURL('monthly', self.prevMonth())

    def current(self):
        """Return the link for the current month."""
        # XXX shouldn't use date.today; it depends on the server's timezone
        # which may not match user expectations
        return self.calURL('monthly', date.today())

    def next(self):
        """Return the link for the next month."""
        return self.calURL('monthly', self.nextMonth())

    def dayOfWeek(self, date):
        return day_of_week_names[date.weekday()]

    def weekTitle(self, date):
        msg = _('Week ${week_no}',
                mapping={'week_no': date.isocalendar()[1]})
        return msg

    def getCurrentMonth(self):
        """Return the current month as a nested list of CalendarDays."""
        return self.getMonth(self.cursor)


class YearlyCalendarView(CalendarViewBase):
    """Yearly calendar view."""

    __used_for__ = ISchoolToolCalendar

    cal_type = 'yearly'

    next_title = _("Next year")
    current_title = _("Current year")
    prev_title = _("Previous year")

    def pdfURL(self):
        return None

    def inCurrentPeriod(self, dt):
        return dt.year == self.cursor.year

    def title(self):
        return unicode(self.cursor.year)

    def prev(self):
        """Return the link for the previous year."""
        return self.calURL('yearly', date(self.cursor.year - 1, 1, 1))

    def current(self):
        """Return the link for the current year."""
        # XXX shouldn't use date.today; it depends on the server's timezone
        # which may not match user expectations
        return self.calURL('yearly', date.today())

    def next(self):
        """Return the link for the next year."""
        return self.calURL('yearly', date(self.cursor.year + 1, 1, 1))

    def shortDayOfWeek(self, date):
        return short_day_of_week_names[date.weekday()]

    def _initDaysCache(self):
        """Initialize the _days_cache attribute.

        When ``update`` figures out which time period will be displayed to the
        user, it calls ``_initDaysCache`` to give the view a chance to
        precompute the calendar events for the time interval.

        This implementation designates the year of self.cursor as the time
        interval for caching.
        """
        CalendarViewBase._initDaysCache(self)
        first_day_of_year = self.cursor.replace(month=1, day=1)
        first = week_start(first_day_of_year, self.first_day_of_week)
        last_day_of_year = self.cursor.replace(month=12, day=31)
        last = week_start(last_day_of_year,
                          self.first_day_of_week) + timedelta(7)
        self._days_cache.extend(first, last)


class DailyCalendarView(CalendarViewBase):
    """Daily calendar view.

    The events are presented as boxes on a 'sheet' with rows
    representing hours.

    The challenge here is to present the events as a table, so that
    the overlapping events are displayed side by side, and the size of
    the boxes illustrate the duration of the events.
    """

    __used_for__ = ISchoolToolCalendar

    cal_type = 'daily'

    starthour = 8
    endhour = 19

    next_title = _("The next day")
    current_title = _("Today")
    prev_title = _("The previous day")

    def inCurrentPeriod(self, dt):
        return dt == self.cursor

    def title(self):
        return self.dayTitle(self.cursor)

    def prev(self):
        """Return the link for the next day."""
        return self.calURL('daily', self.cursor - timedelta(1))

    def current(self):
        """Return the link for today."""
        # XXX shouldn't use date.today; it depends on the server's timezone
        # which may not match user expectations
        return self.calURL('daily', date.today())

    def next(self):
        """Return the link for the previous day."""
        return self.calURL('daily', self.cursor + timedelta(1))

    def getColumns(self):
        """Return the maximum number of events that are overlapping.

        Extends the event so that start and end times fall on hour
        boundaries before calculating overlaps.
        """
        width = [0] * 24
        daystart = datetime.combine(self.cursor, time(tzinfo=utc))
        for event in self.dayEvents(self.cursor):
            t = daystart
            dtend = daystart + timedelta(1)
            for title, start, duration in self.calendarRows():
                if start <= event.dtstart < start + duration:
                    t = start
                if start < event.dtstart + event.duration <= start + duration:
                    dtend = start + duration
            while True:
                width[t.hour] += 1
                t += timedelta(hours=1)
                if t >= dtend:
                    break
        return max(width) or 1

    def _setRange(self, events):
        """Set the starthour and endhour attributes according to events.

        The range of the hours to display is the union of the range
        8:00-18:00 and time spans of all the events in the events
        list.
        """
        for event in events:
            start = self.timezone.localize(datetime.combine(self.cursor,
                                            time(self.starthour)))
            end = self.timezone.localize(datetime.combine(self.cursor,
                   time()) + timedelta(hours=self.endhour)) # endhour may be 24
            if event.dtstart < start:
                newstart = max(self.timezone.localize(
                                        datetime.combine(self.cursor, time())),
                                        event.dtstart.astimezone(self.timezone))
                self.starthour = newstart.hour

            if event.dtstart + event.duration > end and \
                event.dtstart.astimezone(self.timezone).day <= self.cursor.day:
                newend = min(self.timezone.localize(
                                        datetime.combine(self.cursor,
                                                        time())) + timedelta(1),
                            event.dtstart.astimezone(self.timezone) +
                                        event.duration + timedelta(0, 3599))
                self.endhour = newend.hour
                if self.endhour == 0:
                    self.endhour = 24

    __cursor = None
    __calendar_rows = None

    def calendarRows(self):
        """Iterate over (title, start, duration) of time slots that make up
        the daily calendar.

        Returns a list, caches the answer for subsequent calls.
        """
        view = zapi.getMultiAdapter((self.context, self.request),
                                    name='daily_calendar_rows')
        return view.calendarRows(self.cursor, self.starthour, self.endhour)

    def _getCurrentTime(self):
        """Returns current time localized to UTC timezone."""
        return utc.localize(datetime.utcnow())

    def getHours(self):
        """Return an iterator over the rows of the table.

        Every row is a dict with the following keys:

            'time' -- row label (e.g. 8:00)
            'cols' -- sequence of cell values for this row

        A cell value can be one of the following:
            None  -- if there is no event in this cell
            event -- if an event starts in this cell
            ''    -- if an event started above this cell

        """
        nr_cols = self.getColumns()
        all_events = self.dayEvents(self.cursor)
        # Filter allday events
        simple_events = [event for event in all_events
                         if not event.allday]
        self._setRange(simple_events)
        slots = Slots()
        top = 0
        for title, start, duration in self.calendarRows():
            end = start + duration
            hour = start.hour

            # Remove the events that have already ended
            for i in range(nr_cols):
                ev = slots.get(i, None)
                if ev is not None and ev.dtstart + ev.duration <= start:
                    del slots[i]

            # Add events that start during (or before) this hour
            while (simple_events and simple_events[0].dtstart < end):
                event = simple_events.pop(0)
                slots.add(event)

            cols = []
            # Format the row
            for i in range(nr_cols):
                ev = slots.get(i, None)
                if (ev is not None
                    and ev.dtstart < start
                    and hour != self.starthour):
                    # The event started before this hour (except first row)
                    cols.append('')
                else:
                    # Either None, or new event
                    cols.append(ev)

            height = duration.seconds / 900.0
            if height < 1.5:
                # Do not display the time of the start of the period when there
                # is too little space as that looks rather ugly.
                title = ''

            active = start <= self._getCurrentTime() < end

            yield {'title': title,
                   'cols': tuple(cols),
                   'time': start.strftime("%H:%M"),
                   'active': active,
                   'top': top,
                   'height': height,
                   # We can trust no period will be longer than a day
                   'duration': duration.seconds // 60}

            top += height

    def snapToGrid(self, dt):
        """Calculate the position of a datetime on the display grid.

        The daily view uses a grid where a unit (currently 'em', but that
        can be changed in the page template) corresponds to 15 minutes, and
        0 represents self.starthour.

        Clips dt so that it is never outside today's box.
        """
        base = self.timezone.localize(datetime.combine(self.cursor, time()))
        display_start = base + timedelta(hours=self.starthour)
        display_end = base + timedelta(hours=self.endhour)
        clipped_dt = max(display_start, min(dt, display_end))
        td = clipped_dt - display_start
        offset_in_minutes = td.seconds / 60 + td.days * 24 * 60
        return offset_in_minutes / 15.

    def eventTop(self, event):
        """Calculate the position of the top of the event block in the display.

        See `snapToGrid`.
        """
        return self.snapToGrid(event.dtstart.astimezone(self.timezone))

    def eventHeight(self, event, minheight=3):
        """Calculate the height of the event block in the display.

        Rounds the height up to a minimum of minheight.

        See `snapToGrid`.
        """
        dtend = event.dtstart + event.duration
        return max(minheight,
                   self.snapToGrid(dtend) - self.snapToGrid(event.dtstart))

    def isResourceCalendar(self):
        """Return True if we are showing a calendar of some resource."""
        return IResource.providedBy(self.context.__parent__)

    def getAllDayEvents(self):
        """Get a list of EventForDisplay objects for the all-day events at the
        cursors current position.
        """
        for event in self.dayEvents(self.cursor):
            if event.allday:
                yield event


class DailyCalendarRowsView(BrowserView):
    """Daily calendar rows view for SchoolTool.

    This view differs from the original view in SchoolBell in that it can
    also show day periods instead of hour numbers.
    """

    __used_for__ = ISchoolToolCalendar

    def getPersonTimezone(self):
        """Return the prefered timezone of the user."""
        return ViewPreferences(self.request).timezone

    def getPeriodsForDay(self, date):
        """Return a list of timetable periods defined for `date`.

        This function uses the default timetable schema and the appropriate time
        period for `date`.

        Retuns a list of (id, dtstart, duration) tuples.  The times
        are timezone-aware and in the timezone of the timetable.

        Returns an empty list if there are no periods defined for `date` (e.g.
        if there is no default timetable schema, or `date` falls outside all
        time periods, or it happens to be a holiday).
        """
        schooldays = getTermForDate(date)
        ttcontainer = getSchoolToolApplication()['ttschemas']
        if ttcontainer.default_id is None or schooldays is None:
            return []
        ttschema = ttcontainer.getDefault()
        tttz = timezone(ttschema.timezone)
        displaytz = self.getPersonTimezone()

        # Find out the days in the timetable that our display date overlaps
        daystart = displaytz.localize(datetime.combine(date, time(0)))
        dayend = daystart + date.resolution
        day1 = daystart.astimezone(tttz).date()
        day2 = dayend.astimezone(tttz).date()

        def resolvePeriods(date):
            term = getTermForDate(date)
            if not term:
                return []

            periods = ttschema.model.periodsInDay(term, ttschema, date)
            result = []
            for id, tstart, duration in  periods:
                dtstart = datetime.combine(date, tstart)
                dtstart = tttz.localize(dtstart)
                result.append((id, dtstart, duration))
            return result

        periods = resolvePeriods(day1)
        if day2 != day1:
            periods += resolvePeriods(day2)

        result = []

        # Filter out periods outside date boundaries and chop off the
        # ones overlapping them.
        for id, dtstart, duration in periods:
            if (dtstart + duration <= daystart) or (dayend <= dtstart):
                continue
            if dtstart < daystart:
                duration -= daystart - dtstart
                dtstart = daystart.astimezone(tttz)
            if dayend < dtstart + duration:
                duration = dayend - dtstart
            result.append((id, dtstart, duration))

        return result

    def getPeriods(self, cursor):
        """Return the date we get from getPeriodsForDay.

        Checks user preferences, returns an empty list if no user is
        logged in.
        """
        person = IPerson(self.request.principal, None)
        if (person is not None and
            IPersonPreferences(person).cal_periods):
            return self.getPeriodsForDay(cursor)
        else:
            return []

    def calendarRows(self, cursor, starthour, endhour):
        """Iterate over (title, start, duration) of time slots that make up
        the daily calendar.

        Returns a generator.
        """
        tz = self.getPersonTimezone()
        periods = self.getPeriods(cursor)

        daystart = tz.localize(datetime.combine(cursor, time()))
        rows = [daystart + timedelta(hours=hour)
                for hour in range(starthour, endhour+1)]

        if periods:
            timetable = getSchoolToolApplication()['ttschemas'].getDefault()
            tttz = timezone(timetable.timezone)

            # Put starts and ends of periods into rows
            for period in periods:
                period_id, pstart, duration = period
                pend = (pstart + duration).astimezone(tz)
                for point in rows[:]:
                    if pstart < point < pend:
                        rows.remove(point)
                if pstart not in rows:
                    rows.append(pstart)
                if pend not in rows:
                    rows.append(pend)
            rows.sort()

        calendarRows = []

        start, row_ends = rows[0], rows[1:]
        start = start.astimezone(tz)
        for end in row_ends:
            if periods and periods[0][1] == start:
                period = periods.pop(0)
                calendarRows.append((period[0], start, period[2]))
            else:
                duration = end - start
                calendarRows.append(('%d:%02d' % (start.hour, start.minute),
                                     start, duration))
            start = end
        return calendarRows

    def rowTitle(self, hour, minute):
        """Return the row title as HH:MM or H:MM am/pm."""
        prefs = ViewPreferences(self.request)
        return time(hour, minute).strftime(prefs.timeformat)


class CalendarSTOverlayView(CalendarOverlayView):
    """View for the calendar overlay portlet.

    Much like the original CalendarOverlayView in SchoolBell, this view allows
    you to choose calendars to be displayed, but this one allows you to view
    timetables of the calendar owners as well.

    This view can be used with any context, but it gets rendered to an empty
    string unless context is the calendar of the authenticated user.

    Note that this view contains a self-posting form and handles submits that
    contain 'OVERLAY_APPLY' or 'OVERLAY_MORE' in the request.
    """

    SHOW_TIMETABLE_KEY = 'schooltool.app.browser.cal.show_my_timetable'

    def items(self):
        """Return items to be shown in the calendar overlay.

        Does not include "my calendar".

        Each item is a dict with the following keys:

            'title' - title of the calendar, or label for section calendars

            'calendar' - the calendar object

            'color1', 'color2' - colors assigned to this calendar

            'id' - identifier for form controls

            'checked' - was this item checked for display (either "checked" or
            None)?

            'checked_tt' - was this calendar owner's timetable checked for
            display?
        """
        def getTitleOrLabel(item):
            object = item.calendar.__parent__
            if ISection.providedBy(object):
                return removeSecurityProxy(object.label)
            else:
                return item.calendar.title

        person = IPerson(self.request.principal)
        items = [(item.calendar.title,
                  {'title': getTitleOrLabel(item),
                   'id': getPath(item.calendar.__parent__),
                   'calendar': item.calendar,
                   'checked': item.show and "checked" or '',
                   'checked_tt':
                       IShowTimetables(item).showTimetables and "checked" or '',
                   'color1': item.color1,
                   'color2': item.color2})
                 for item in person.overlaid_calendars
                 if canAccess(item.calendar, '__iter__')]
        items.sort()
        return [i[-1] for i in items]

    def update(self):
        """Process form submission."""
        if 'OVERLAY_APPLY' in self.request:
            person = IPerson(self.request.principal)
            selected = Set(self.request.get('overlay_timetables', []))
            for item in person.overlaid_calendars:
                path = getPath(item.calendar.__parent__)
                # XXX this is related to the issue
                # http://issues.schooltool.org/issue391!
                IShowTimetables(item).showTimetables = path in selected

            # The unproxied object will only be used for annotations.
            person = removeSecurityProxy(person)

            annotations = IAnnotations(person)
            annotations[self.SHOW_TIMETABLE_KEY] = bool('my_timetable'
                                                        in self.request)
        return CalendarOverlayView.update(self)

    def myTimetableShown(self):
        person = IPerson(self.request.principal)
        # The unproxied object will only be used for annotations.
        person = removeSecurityProxy(person)
        annotations = IAnnotations(person)
        return annotations.get(self.SHOW_TIMETABLE_KEY, True)


class CalendarListSubscriber(object):
    """A subscriber that can tell which calendars should be displayed.

    This subscriber includes composite timetable calendars, overlaid
    calendars and the calendar you are looking at.
    """

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def getCalendars(self):
        """Get a list of calendars to display.

        Yields tuples (calendar, color1, color2).
        """
        # personal calendar
        yield (self.context, '#9db8d2', '#7590ae')

        parent = zapi.getParent(self.context)
        ttcalendar = ICompositeTimetables(parent).makeTimetableCalendar()

        user = IPerson(self.request.principal, None)
        if user is None:
            yield (ttcalendar, '#9db8d2', '#7590ae')
            return # unauthenticated user

        unproxied_context = removeSecurityProxy(self.context)
        unproxied_calendar = removeSecurityProxy(ISchoolToolCalendar(user))
        if unproxied_context is not unproxied_calendar:
            yield (ttcalendar, '#9db8d2', '#7590ae')
            return # user looking at the calendar of some other person

        # personal timetable
        unproxied_person = removeSecurityProxy(user) # for annotations
        annotations = IAnnotations(unproxied_person)
        if annotations.get(CalendarSTOverlayView.SHOW_TIMETABLE_KEY, True):
            yield (ttcalendar, '#9db8d2', '#7590ae')
            # Maybe we should change the colour to differ from the user's
            # personal calendar?

        for item in user.overlaid_calendars:
            if canAccess(item.calendar, '__iter__'):
                # overlaid calendars
                if item.show:
                    yield (item.calendar, item.color1, item.color2)

                # overlaid timetables
                if IShowTimetables(item).showTimetables:
                    owner = item.calendar.__parent__
                    ttcalendar = ICompositeTimetables(owner).makeTimetableCalendar()
                    yield (ttcalendar, item.color1, item.color2)

#
# Calendar modification views
#

class EventDeleteView(BrowserView):
    """A view for deleting events."""

    __used_for__ = ISchoolToolCalendar

    def handleEvent(self):
        """Handle a request to delete an event.

        If the event is not recurrent, it is simply deleted, None is returned
        and the user is redirected to the calendar view.

        If the event being deleted is recurrent event, the request is checked
        for a command.  If one is found, it is handled, the user again is
        redirected to the calendar view.  If no commands are found in the
        request, the recurrent event is returned to be shown in the view.
        """
        event_id = self.request['event_id']
        date = parse_date(self.request['date'])

        event = self._findEvent(event_id)
        if event is None:
            # The event was not found.
            return self._redirectBack()

        if event.recurrence is None or event.__parent__ != self.context:
            # Bah, the event is not recurrent.  Easy!
            # XXX It shouldn't be.  We should still ask for confirmation.
            self.context.removeEvent(removeSecurityProxy(event))
            return self._redirectBack()
        else:
            # The event is recurrent, we might need to show a form.
            return self._deleteRepeatingEvent(event, date)

    def _findEvent(self, event_id):
        """Find an event that has the id event_id.

        First the event is searched for in the current calendar and then,
        overlaid calendars if any.

        If no event with the given id is found, None is returned.
        """
        try:
            return self.context.find(event_id)
        except KeyError:
            pass

    def _redirectBack(self):
        """Redirect to the current calendar's daily view."""
        url = absoluteURL(self.context, self.request)
        self.request.response.redirect(url)

    def _deleteRepeatingEvent(self, event, date):
        """Delete a repeating event."""
        if 'CANCEL' in self.request:
            pass # Fall through and redirect back to the calendar.
        elif 'ALL' in self.request:
            self.context.removeEvent(removeSecurityProxy(event))
        elif 'FUTURE' in self.request:
            self._modifyRecurrenceRule(event, until=(date - timedelta(1)),
                                       count=None)
        elif 'CURRENT' in self.request:
            exceptions = event.recurrence.exceptions + (date, )
            self._modifyRecurrenceRule(event, exceptions=exceptions)
        else:
            return event # We don't know what to do, let's ask the user.

        # We did our job, redirect back to the calendar view.
        return self._redirectBack()

    def _modifyRecurrenceRule(self, event, **kwargs):
        """Modify the recurrence rule of an event.

        If the event does not have any recurrences afterwards, it is removed
        from the parent calendar
        """
        rrule = event.recurrence
        new_rrule = rrule.replace(**kwargs)
        # This view requires the modifyEvent permission.
        event.recurrence = removeSecurityProxy(new_rrule)
        if not event.hasOccurrences():
            ICalendar(event).removeEvent(removeSecurityProxy(event))


class Slots(dict):
    """A dict with automatic key selection.

    The add method automatically selects the lowest unused numeric key
    (starting from 0).

    Example:

      >>> s = Slots()
      >>> s.add("first")
      >>> s
      {0: 'first'}

      >>> s.add("second")
      >>> s
      {0: 'first', 1: 'second'}

    The keys can be reused:

      >>> del s[0]
      >>> s.add("third")
      >>> s
      {0: 'third', 1: 'second'}

    """

    def add(self, obj):
        i = 0
        while i in self:
            i += 1
        self[i] = obj


class CalendarEventView(BrowserView):
    """View for single events."""

    # XXX what are these used for?
    color1 = '#9db8d2'
    color2 = '#7590ae'

    def __init__(self, context, request):
        self.context = context
        self.request = request

        self.preferences = ViewPreferences(request)

        self.dtstart = context.dtstart.astimezone(self.preferences.timezone)
        self.dtend = self.dtstart + context.duration
        self.start = self.dtstart.strftime(self.preferences.timeformat)
        self.end = self.dtend.strftime(self.preferences.timeformat)

        dayformat = '%A, ' + self.preferences.dateformat
        self.day = unicode(self.dtstart.strftime(dayformat))

        self.display = EventForDisplay(context, self.request,
                                       self.color1, self.color2,
                                       context.__parent__,
                                       timezone=self.preferences.timezone)


class ICalendarEventAddForm(Interface):
    """Schema for event adding form."""

    title = TextLine(
        title=_("Title"),
        required=False)
    allday = Bool(
        title=_("All day"),
        required=False)
    start_date = Date(
        title=_("Date"),
        required=False)
    start_time = TextLine(
        title=_("Time"),
        description=_("Start time in 24h format"),
        required=False)

    duration = Int(
        title=_("Duration"),
        required=False,
        default=60)

    duration_type = Choice(
        title=_("Duration Type"),
        required=False,
        default="minutes",
        vocabulary=vocabulary([("minutes", _("Minutes")),
                               ("hours", _("Hours")),
                               ("days", _("Days"))]))

    location = TextLine(
        title=_("Location"),
        required=False)

    description = HtmlFragment(
        title=_("Description"),
        required=False)

    # Recurrence
    recurrence = Bool(
        title=_("Recurring"),
        required=False)

    recurrence_type = Choice(
        title=_("Recurs every"),
        required=True,
        default="daily",
        vocabulary=vocabulary([("daily", _("Day")),
                               ("weekly", _("Week")),
                               ("monthly", _("Month")),
                               ("yearly", _("Year"))]))

    interval = Int(
        title=_("Repeat every"),
        required=False,
        default=1)

    range = Choice(
        title=_("Range"),
        required=False,
        default="forever",
        vocabulary=vocabulary([("count", _("Count")),
                               ("until", _("Until")),
                               ("forever", _("forever"))]))

    count = Int(
        title=_("Number of events"),
        required=False)

    until = Date(
        title=_("Repeat until"),
        required=False)

    weekdays = List(
        title=_("Weekdays"),
        required=False,
        value_type=Choice(
            title=_("Weekday"),
            vocabulary=vocabulary([(0, _("Mon")),
                                   (1, _("Tue")),
                                   (2, _("Wed")),
                                   (3, _("Thu")),
                                   (4, _("Fri")),
                                   (5, _("Sat")),
                                   (6, _("Sun"))])))

    monthly = Choice(
        title=_("Monthly"),
        default="monthday",
        required=False,
        vocabulary=vocabulary([("monthday", "md"),
                               ("weekday", "wd"),
                               ("lastweekday", "lwd")]))

    exceptions = Text(
        title=_("Exception dates"),
        required=False)


class CalendarEventViewMixin(object):
    """A mixin that holds the code common to CalendarEventAdd and Edit Views."""

    timezone = utc

    def _setError(self, name, error=RequiredMissing()):
        """Set an error on a widget."""
        # XXX Touching widget._error is bad, see
        #     http://dev.zope.org/Zope3/AccessToWidgetErrors
        # The call to setRenderedValue is necessary because
        # otherwise _getFormValue will call getInputValue and
        # overwrite _error while rendering.
        widget = getattr(self, name + '_widget')
        widget.setRenderedValue(widget._getFormValue())
        if not IWidgetInputError.providedBy(error):
            error = WidgetInputError(name, widget.label, error)
        widget._error = error

    def _requireField(self, name, errors):
        """If widget has no input, WidgetInputError is set.

        Also adds the exception to the `errors` list.
        """
        widget = getattr(self, name + '_widget')
        field = widget.context
        try:
            if widget.getInputValue() == field.missing_value:
                self._setError(name)
                errors.append(widget._error)
        except WidgetInputError, e:
            # getInputValue might raise an exception on invalid input
            errors.append(e)

    def setUpEditorWidget(self, editor):
        editor.editorWidth = 430
        editor.editorHeight = 300
        editor.toolbarConfiguration = "schooltool"
        url = zapi.absoluteURL(ISchoolToolApplication(None), self.request)
        editor.configurationPath = (url + '/@@/editor_config.js')

    def weekdayChecked(self, weekday):
        """Return True if the given weekday should be checked.

        The weekday of start_date is always checked, others can be selected by
        the user.

        Used to format checkboxes for weekly recurrences.
        """
        return (int(weekday) in self.weekdays_widget._getFormValue() or
                self.weekdayDisabled(weekday))

    def weekdayDisabled(self, weekday):
        """Return True if the given weekday should be disabled.

        The weekday of start_date is always disabled, all others are always
        enabled.

        Used to format checkboxes for weekly recurrences.
        """
        day = self.getStartDate()
        return bool(day and day.weekday() == int(weekday))

    def getMonthDay(self):
        """Return the day number in a month, according to start_date.

        Used by the page template to format monthly recurrence rules.
        """
        evdate = self.getStartDate()
        if evdate is None:
            return '??'
        else:
            return str(evdate.day)

    def getWeekDay(self):
        """Return the week and weekday in a month, according to start_date.

        The output looks like '4th Tuesday'

        Used by the page template to format monthly recurrence rules.
        """
        evdate = self.getStartDate()
        if evdate is None:
            return _("same weekday")

        weekday = evdate.weekday()
        index = (evdate.day + 6) // 7

        indexes = {1: _('1st'), 2: _('2nd'), 3: _('3rd'), 4: _('4th'),
                   5: _('5th')}
        day_of_week = day_of_week_names[weekday]
        return "%s %s" % (indexes[index], day_of_week)

    def getLastWeekDay(self):
        """Return the week and weekday in a month, counting from the end.

        The output looks like 'Last Friday'

        Used by the page template to format monthly recurrence rules.
        """
        evdate = self.getStartDate()

        if evdate is None:
            return _("last weekday")

        lastday = calendar.monthrange(evdate.year, evdate.month)[1]

        if lastday - evdate.day >= 7:
            return None
        else:
            weekday = evdate.weekday()
            day_of_week_msgid = day_of_week_names[weekday]
            day_of_week = translate(day_of_week_msgid, context=self.request)
            msg = _("Last ${weekday}", mapping={'weekday': day_of_week})
            return msg

    def getStartDate(self):
        """Return the value of the widget if a start_date is set."""
        try:
            return self.start_date_widget.getInputValue()
        except (WidgetInputError, ConversionError):
            return None

    def updateForm(self):
        # Just refresh the form.  It is necessary because some labels for
        # monthly recurrence rules depend on the event start date.
        self.update_status = ''
        try:
            data = getWidgetsData(self, self.schema, names=self.fieldNames)
            kw = {}
            for name in self._keyword_arguments:
                if name in data:
                    kw[str(name)] = data[name]
            self.processRequest(kw)
        except WidgetsError, errors:
            self.errors = errors
            self.update_status = _("An error occurred.")
            return self.update_status
        # AddView.update() sets self.update_status and returns it.  Weird,
        # but let's copy that behavior.
        return self.update_status

    def processRequest(self, kwargs):
        """Put information from the widgets into a dict.

        This method performs additional validation, because Zope 3 forms aren't
        powerful enough.  If any errors are encountered, a WidgetsError is
        raised.
        """
        errors = []
        self._requireField("title", errors)
        self._requireField("start_date", errors)

        # What we require depends on weather or not we have an allday event
        allday = kwargs.pop('allday', None)
        if not allday:
            self._requireField("start_time", errors)

        self._requireField("duration", errors)

        # Remove fields not needed for makeRecurrenceRule from kwargs
        title = kwargs.pop('title', None)
        start_date = kwargs.pop('start_date', None)
        start_time = kwargs.pop('start_time', None)
        if start_time:
            try:
                start_time = parse_time(start_time)
            except ValueError:
                self._setError("start_time",
                               ConversionError(_("Invalid time")))
                errors.append(self.start_time_widget._error)
        duration = kwargs.pop('duration', None)
        duration_type = kwargs.pop('duration_type', 'minutes')
        location = kwargs.pop('location', None)
        description = kwargs.pop('description', None)
        recurrence = kwargs.pop('recurrence', None)

        if recurrence:
            self._requireField("interval", errors)
            self._requireField("recurrence_type", errors)
            self._requireField("range", errors)

            range = kwargs.get('range')
            if range == "count":
                self._requireField("count", errors)
            elif range == "until":
                self._requireField("until", errors)
                if start_date and kwargs.get('until'):
                    if kwargs['until'] < start_date:
                        self._setError("until", ConstraintNotSatisfied(
                                    _("End date is earlier than start date")))
                        errors.append(self.until_widget._error)

        exceptions = kwargs.pop("exceptions", None)
        if exceptions:
            try:
                kwargs["exceptions"] = datesParser(exceptions)
            except ValueError:
                self._setError("exceptions", ConversionError(
                 _("Invalid date.  Please specify YYYY-MM-DD, one per line.")))
                errors.append(self.exceptions_widget._error)

        if errors:
            raise WidgetsError(errors)

        # Some fake data for allday events, based on what iCalendar seems to
        # expect
        if allday is True:
            # iCalendar has no spec for describing all-day events, but it seems
            # to be the de facto standard to give them a 1d duration.
            # XXX ignas: ical has allday events, they are different
            # from normal events, because they have a date as their
            # dtstart not a datetime
            duration_type = "days"
            start_time = time(0, 0, tzinfo=utc)
            start = datetime.combine(start_date, start_time)
        else:
            start = datetime.combine(start_date, start_time)
            start = self.timezone.localize(start).astimezone(utc)

        dargs = {duration_type : duration}
        duration = timedelta(**dargs)

        # Shift the weekdays to the correct timezone
        if 'weekdays' in kwargs and kwargs['weekdays']:
            kwargs['weekdays'] = tuple(convertWeekdaysList(start,
                                                           self.timezone,
                                                           start.tzinfo,
                                                           kwargs['weekdays']))


        rrule = recurrence and makeRecurrenceRule(**kwargs) or None
        return {'location': location,
                'description': description,
                'title': title,
                'allday': allday,
                'start': start,
                'duration': duration,
                'rrule': rrule}


class CalendarEventAddView(CalendarEventViewMixin, AddView):
    """A view for adding an event."""

    __used_for__ = ISchoolToolCalendar
    schema = ICalendarEventAddForm

    title = _("Add event")
    submit_button_title = _("Add")

    show_book_checkbox = True
    show_book_link = False
    _event_uid = None

    error = None

    def __init__(self, context, request):

        prefs = ViewPreferences(request)
        self.timezone = prefs.timezone

        if "field.start_date" not in request:
            # XXX shouldn't use date.today; it depends on the server's timezone
            # which may not match user expectations
            today = date.today().strftime("%Y-%m-%d")
            request.form["field.start_date"] = today
        super(AddView, self).__init__(context, request)
        self.setUpEditorWidget(self.description_widget)

    def create(self, **kwargs):
        """Create an event."""
        data = self.processRequest(kwargs)
        event = self._factory(data['start'], data['duration'], data['title'],
                              recurrence=data['rrule'],
                              location=data['location'],
                              allday=data['allday'],
                              description=data['description'])
        return event

    def add(self, event):
        """Add the event to a calendar."""
        self.context.addEvent(event)
        uid = event.unique_id
        self._event_name = event.__name__
        session_data = ISession(self.request)['schooltool.calendar']
        session_data.setdefault('added_event_uids', set()).add(uid)
        return event

    def update(self):
        """Process the form."""
        if 'UPDATE' in self.request:
            return self.updateForm()
        elif 'CANCEL' in self.request:
            self.update_status = ''
            self.request.response.redirect(self.nextURL())
            return self.update_status
        else:
            return AddView.update(self)

    def nextURL(self):
        """Return the URL to be displayed after the add operation."""
        if "field.book" in self.request:
            url = absoluteURL(self.context, self.request)
            return '%s/%s/booking.html' % (url, self._event_name)
        else:
            return absoluteURL(self.context, self.request)


class ICalendarEventEditForm(ICalendarEventAddForm):
    pass


class CalendarEventEditView(CalendarEventViewMixin, EditView):
    """A view for editing an event."""

    error = None
    show_book_checkbox = False
    show_book_link = True

    title = _("Edit event")
    submit_button_title = _("Update")

    def __init__(self, context, request):
        prefs = ViewPreferences(request)
        self.timezone = prefs.timezone
        EditView.__init__(self, context, request)
        self.setUpEditorWidget(self.description_widget)

    def keyword_arguments(self):
        """Wraps fieldNames under another name.

        AddView and EditView API does not match so some wrapping is needed.
        """
        return self.fieldNames

    _keyword_arguments = property(keyword_arguments, None)

    def _setUpWidgets(self):
        setUpWidgets(self, self.schema, IInputWidget, names=self.fieldNames,
                     initial=self._getInitialData(self.context))

    def _getInitialData(self, context):
        """Extract initial widgets data from context."""

        initial = {}
        initial["title"] = context.title
        initial["allday"] = context.allday
        initial["start_date"] = context.dtstart.date()
        initial["start_time"] = context.dtstart.astimezone(self.timezone).strftime("%H:%M")
        duration = context.duration.seconds / 60 + context.duration.days * 1440
        initial["duration_type"] = (duration % 60 and "minutes" or
                                    duration % (24 * 60) and "hours" or
                                    "days")
        initial["duration"] = (initial["duration_type"] == "minutes" and duration or
                               initial["duration_type"] == "hours" and duration / 60 or
                               initial["duration_type"] == "days" and duration / 60 / 24)
        initial["location"] = context.location
        initial["description"] = context.description
        recurrence = context.recurrence
        initial["recurrence"] = recurrence is not None
        if recurrence:
            initial["interval"] = recurrence.interval
            recurrence_type = (
                IDailyRecurrenceRule.providedBy(recurrence) and "daily" or
                IWeeklyRecurrenceRule.providedBy(recurrence) and "weekly" or
                IMonthlyRecurrenceRule.providedBy(recurrence) and "monthly" or
                IYearlyRecurrenceRule.providedBy(recurrence) and "yearly")

            initial["recurrence_type"] = recurrence_type
            if recurrence.until:
                initial["until"] = recurrence.until
                initial["range"] = "until"
            elif recurrence.count:
                initial["count"] = recurrence.count
                initial["range"] = "count"
            else:
                initial["range"] = "forever"

            if recurrence.exceptions:
                exceptions = map(str, recurrence.exceptions)
                initial["exceptions"] = "\n".join(exceptions)

            if recurrence_type == "weekly":
                if recurrence.weekdays:
                    # Convert weekdays to the correct TZ
                    initial["weekdays"] = convertWeekdaysList(
                        self.context.dtstart,
                        self.context.dtstart.tzinfo,
                        self.timezone,
                        recurrence.weekdays)

            if recurrence_type == "monthly":
                if recurrence.monthly:
                    initial["monthly"] = recurrence.monthly

        return initial

    def getStartDate(self):
        if "field.start_date" in self.request:
            return CalendarEventViewMixin.getStartDate(self)
        else:
            return self.context.dtstart.astimezone(self.timezone).date()

    def applyChanges(self):
        data = getWidgetsData(self, self.schema, names=self.fieldNames)
        kw = {}
        for name in self._keyword_arguments:
            if name in data:
                kw[str(name)] = data[name]

        widget_data = self.processRequest(kw)

        parsed_date = parse_datetimetz(widget_data['start'].isoformat())
        self.context.dtstart = parsed_date
        self.context.recurrence = widget_data['rrule']
        for attrname in ['allday', 'duration', 'title',
                         'location', 'description']:
            setattr(self.context, attrname, widget_data[attrname])
        return True

    def update(self):
        if self.update_status is not None:
            # We've been called before. Just return the status we previously
            # computed.
            return self.update_status

        status = ''

        start_date = self.context.dtstart.strftime("%Y-%m-%d")

        if "UPDATE" in self.request:
            return self.updateForm()
        elif 'CANCEL' in self.request:
            self.update_status = ''
            self.request.response.redirect(self.nextURL())
            return self.update_status
        elif "UPDATE_SUBMIT" in self.request:
            # Replicating EditView functionality
            changed = False
            try:
                changed = self.applyChanges()
                if changed:
                    notify(ObjectModifiedEvent(self.context))
            except WidgetsError, errors:
                self.errors = errors
                status = _("An error occurred.")
                transaction.abort()
            else:
                if changed:
                    formatter = self.request.locale.dates.getFormatter(
                        'dateTime', 'medium')
                    status = _("Updated on ${date_time}",
                               mapping = {'date_time': formatter.format(
                                   datetime.utcnow())})
                self.request.response.redirect(self.nextURL())

        self.update_status = status
        return status

    def nextURL(self):
        """Return the URL to be displayed after the add operation."""
        if "field.book" in self.request:
            return absoluteURL(self.context, self.request) + '/booking.html'
        else:
            return absoluteURL(self.context.__parent__, self.request)


class EventForBookingDisplay(object):
    """Event wrapper for display in booking view.

    This is a wrapper around an ICalendarEvent object.  It adds view-specific
    attributes:

        dtend -- timestamp when the event ends
        shortTitle -- title truncated to ~15 characters

    """

    def __init__(self, event):
        # The event came from resource calendar, so its parent might
        # be a calendar we don't have permission to view.
        self.context = removeSecurityProxy(event)
        self.dtstart = self.context.dtstart
        self.dtend = self.context.dtstart + self.context.duration
        self.title = self.context.title
        if len(self.title) > 16:
            # Title needs truncation.
            self.shortTitle = self.title[:15] + '...'
        else:
            self.shortTitle = self.title
        self.unique_id = self.context.unique_id


class CalendarEventBookingView(CalendarEventView):
    """A view for booking resources."""

    errors = ()
    update_status = None

    template = ViewPageTemplateFile("templates/event_booking.pt")

    def __init__(self, context, request):
        CalendarEventView.__init__(self, context, request)

        format = '%s - %s' % (self.preferences.dateformat,
                              self.preferences.timeformat)
        self.start = u'' + self.dtstart.strftime(format)
        self.end = u'' + self.dtend.strftime(format)

    def __call__(self):
        self.checkPermission()
        return self.template()

    def checkPermission(self):
        if canAccess(self.context, 'bookResource'):
            return
        # If the authenticated user has the addEvent permission and has
        # come here directly from the event adding form, let him book.
        # (Fixes issue 486.)
        if self.justAddedThisEvent():
            return
        raise Unauthorized("user not allowed to book")

    def hasBookedItems(self):
        return bool(self.context.resources)

    def bookingStatus(self, item, formatter):
        conflicts = self.getConflictingEvents(item)
        status = {}
        for conflict in conflicts:
            if conflict.context.__parent__ and conflict.context.__parent__.__parent__:
                zapi.absoluteURL(self.context, self.request)
                owner = conflict.context.__parent__.__parent__
                url = zapi.absoluteURL(owner, self.request)
            else:
                owner = conflict.context.activity.owner
                url = owner.absolute_url()
            owner_url = "%s/calendar" % url
            owner_name = owner.title
            status[owner_name] = owner_url
        return status


    def columnsForAvailable(self):

        def statusFormatter(value, item, formatter):
            url = []
            if value:
                for eventOwner, ownerCalendar in value.items():
                    url.append('<a href="%s">%s</a>' % (ownerCalendar, eventOwner))
                return ", ".join(url)
            else:
                return 'Free'

        return [GetterColumn(name='title',
                             title=u"Title",
                             getter=lambda i, f: i.title,
                             subsort=True),
                GetterColumn(title="Booked by others",
                             cell_formatter=statusFormatter,
                             getter=self.bookingStatus
                             )]

    def getBookedItems(self):
        return self.context.resources

    def renderBookedTable(self):
        prefix = "remove_item"
        columns = [CheckboxColumn(prefix=prefix, name='remove', title=u''),
                   GetterColumn(name='title',
                             title=u"Title",
                             getter=lambda i, f: i.title,
                             subsort=True),]
        formatter = table.FormFullFormatter(
            self.context, self.request, self.getBookedItems(),
            columns=columns,
            batch_start=self.batch_start, batch_size=self.batch_size,
            sort_on=self.sortOn(),
            prefix="booked")
        formatter.cssClasses['table'] = 'data'
        return formatter()


    def renderAvailableTable(self):
        prefix = "add_item"
        columns = [CheckboxColumn(prefix=prefix, name='add', title=u'', 
                                  isDisabled=self.getConflictingEvents)]
        available_columns = self.columnsForAvailable()
        available_columns[0] = LabelColumn(available_columns[0], prefix)
        columns.extend(available_columns)
        formatter = table.FormFullFormatter(
            self.context, self.request, self.getAvailableItems(),
            columns=columns,
            batch_start=self.batch_start, batch_size=self.batch_size,
            sort_on=self.sortOn(),
            prefix="available")
        formatter.cssClasses['table'] = 'data'
        return formatter()

    def sortOn(self):
        return (("title", False),)

    def getAvailableItemsContainer(self):
        return ISchoolToolApplication(None)['resources']

    def getAvailableItems(self):
        container = self.getAvailableItemsContainer()
        bookedItems = set(self.getBookedItems())
        allItems = set(container.values())
        return list(allItems - bookedItems)

    def filter(self, list):
        return self.filter_widget.filter(list)


    def updateBatch(self, lst):
        self.batch_start = int(self.request.get('batch_start', 0))
        self.batch_size = int(self.request.get('batch_size', 10))
        self.batch = Batch(lst, self.batch_start, self.batch_size, sort_by='title')

    def justAddedThisEvent(self):
        session_data = ISession(self.request)['schooltool.calendar']
        added_event_ids = session_data.get('added_event_uids', [])
        return self.context.unique_id in added_event_ids

    def clearJustAddedStatus(self):
        """Remove the context uid from the list of added events."""
        session_data = ISession(self.request)['schooltool.calendar']
        added_event_ids = session_data.get('added_event_uids', [])
        uid = self.context.unique_id
        if uid in added_event_ids:
            added_event_ids.remove(uid)

    def update(self):
        """Book/unbook resources according to the request."""
        start_date = self.context.dtstart.strftime("%Y-%m-%d")
        self.filter_widget = queryMultiAdapter((self.getAvailableItemsContainer(),
                                                self.request),
                                                IFilterWidget)

        if 'CANCEL' in self.request:
            url = absoluteURL(self.context, self.request)
            self.request.response.redirect(self.nextURL())

        elif "BOOK" in self.request: # and not self.update_status:
            self.update_status = ''
            sb = getSchoolToolApplication()
            for res_id, resource in sb["resources"].items():
                if 'add_item.%s' % res_id in self.request:
                    #import pdb;pdb.set_trace()
                    booked = self.hasBooked(resource)
                    if not booked:
                        event = removeSecurityProxy(self.context)
                        event.bookResource(resource)
            self.clearJustAddedStatus()
        #    self.request.response.redirect(self.nextURL())

        elif "UNBOOK" in self.request:
            self.update_status = ''
            sb = getSchoolToolApplication()
            for res_id, resource in sb["resources"].items():
                if 'remove_item.%s' % res_id in self.request:
                    booked = self.hasBooked(resource)
                    if booked:
                        # Always allow unbooking, even if permission to
                        # book that specific resource was revoked.
                        self.context.unbookResource(resource)

        self.updateBatch(self.getAvailableItems())
        return self.update_status

    @property
    def availableResources(self):
        """Gives us a list of all bookable resources."""
        sb = getSchoolToolApplication()
        calendar_owner = removeSecurityProxy(self.context.__parent__.__parent__)
        def isBookable(resource):
            if resource is calendar_owner:
                # A calendar event in a resource's calendar shouldn't book
                # that resource, it would be silly.
                return False
            return self.canBook(resource) or self.hasBooked(resource)
        return filter(isBookable, sb['resources'].values())

    def canBook(self, resource):
        """Can the user book this resource?"""
        return canAccess(ISchoolToolCalendar(resource), "addEvent")

    def hasBooked(self, resource):
        """Checks whether a resource is booked by this event."""
        return resource in self.context.resources

    def nextURL(self):
        """Return the URL to be displayed after the add operation."""
        return absoluteURL(self.context.__parent__, self.request)

    def getConflictingEvents(self, resource):
        """Return a list of events that would conflict when booking a resource."""
        calendar = ISchoolToolCalendar(resource)
        if not canAccess(calendar, "expand"):
            return []

        ttcalendar = ICompositeTimetables(resource).makeTimetableCalendar()
        events = []

        for cal in (calendar, ttcalendar):
            evts = list(cal.expand(self.context.dtstart,
                                   self.context.dtstart + self.context.duration))
            events.extend(evts)

        return [EventForBookingDisplay(event)
                for event in events
                if event != self.context]


def makeRecurrenceRule(interval=None, until=None,
                       count=None, range=None,
                       exceptions=None, recurrence_type=None,
                       weekdays=None, monthly=None):
    """Return a recurrence rule according to the arguments."""
    if interval is None:
        interval = 1

    if range != 'until':
        until = None
    if range != 'count':
        count = None

    if exceptions is None:
        exceptions = ()

    kwargs = {'interval': interval, 'count': count,
              'until': until, 'exceptions': exceptions}

    if recurrence_type == 'daily':
        return DailyRecurrenceRule(**kwargs)
    elif recurrence_type == 'weekly':
        weekdays = weekdays or ()
        return WeeklyRecurrenceRule(weekdays=tuple(weekdays), **kwargs)
    elif recurrence_type == 'monthly':
        monthly = monthly or "monthday"
        return MonthlyRecurrenceRule(monthly=monthly, **kwargs)
    elif recurrence_type == 'yearly':
        return YearlyRecurrenceRule(**kwargs)
    else:
        raise NotImplementedError()


def convertWeekdaysList(dt, fromtz, totz, weekdays):
    """Convert the weekday list from one timezone to the other.

    The days can shift by one day in either direction or stay,
    depending on the timezones and the time of the event.

    The arguments are as follows:

       dt       -- the tz-aware start of the event
       fromtz   -- the timezone the weekdays list is in
       totz     -- the timezone the weekdays list is converted to
       weekdays -- a list of values in range(7), 0 is Monday.

    """
    delta_td = dt.astimezone(totz).date() - dt.astimezone(fromtz).date()
    delta = delta_td.days
    return [(wd + delta) % 7 for wd in weekdays]


def datesParser(raw_dates):
    r"""Parse dates on separate lines into a tuple of date objects.

    Incorrect lines are ignored.

    >>> datesParser('2004-05-17\n\n\n2004-01-29')
    (datetime.date(2004, 5, 17), datetime.date(2004, 1, 29))

    >>> datesParser('2004-05-17\n123\n\nNone\n2004-01-29')
    Traceback (most recent call last):
    ...
    ValueError: Invalid date: '123'

    """
    results = []
    for dstr in raw_dates.splitlines():
        if dstr:
            d = parse_date(dstr)
            if isinstance(d, date):
                results.append(d)
    return tuple(results)


def enableVfbView(ical_view):
    """XXX wanna docstring!"""
    return IReadFile(ical_view.context)


def enableICalendarUpload(ical_view):
    """An adapter that enables HTTP PUT for calendars.

    When the user performs an HTTP PUT request on /path/to/calendar.ics,
    Zope 3 traverses to a view named 'calendar.ics' (which is most likely
    a schooltool.calendar.browser.Calendar ICalendarView).  Then Zope 3 finds an
    IHTTPrequest view named 'PUT'.  There is a standard one, that adapts
    its context (which happens to be the view named 'calendar.ics' in this
    case) to IWriteFile, and calls `write` on it.

    So, to hook up iCalendar uploads, the simplest way is to register an
    adapter for CalendarICalendarView that provides IWriteFile.

        >>> from zope.app.testing import setup, ztapi
        >>> setup.placelessSetUp()

    We have a calendar that provides IEditCalendar.

        >>> from schooltool.calendar.interfaces import IEditCalendar
        >>> from schooltool.app.cal import Calendar
        >>> calendar = Calendar(None)

    We have a fake "real adapter" for IEditCalendar

        >>> class RealAdapter:
        ...     implements(IWriteFile)
        ...     def __init__(self, context):
        ...         pass
        ...     def write(self, data):
        ...         print 'real adapter got %r' % data
        >>> ztapi.provideAdapter(IEditCalendar, IWriteFile, RealAdapter)

    We have a fake view on that calendar

        >>> from zope.publisher.browser import BrowserView
        >>> from zope.publisher.browser import TestRequest
        >>> view = BrowserView(calendar, TestRequest())

    And now we can hook things up together

        >>> adapter = enableICalendarUpload(view)
        >>> adapter.write('iCalendar data')
        real adapter got 'iCalendar data'

        >>> setup.placelessTearDown()

    """
    return IWriteFile(ical_view.context)


class CalendarEventBreadcrumbInfo(breadcrumbs.GenericBreadcrumbInfo):
    """Calendar Event Breadcrumb Info

    First, set up a parent:

      >>> class Object(object):
      ...     def __init__(self, parent=None, name=None):
      ...         self.__parent__ = parent
      ...         self.__name__ = name

      >>> calendar = Object()
      >>> from zope.traversing.interfaces import IContainmentRoot
      >>> import zope.interface
      >>> zope.interface.directlyProvides(calendar, IContainmentRoot)

    Now setup the event:

      >>> event = Object(calendar, u'+1243@localhost')

    Setup a request:

      >>> from zope.publisher.browser import TestRequest
      >>> request = TestRequest()

    Now register the breadcrumb info component and other setup:

      >>> import zope.component
      >>> import zope.interface
      >>> from schooltool.skin import interfaces, breadcrumbs
      >>> zope.component.provideAdapter(breadcrumbs.GenericBreadcrumbInfo,
      ...                              (Object, TestRequest),
      ...                              interfaces.IBreadcrumbInfo)

      >>> from zope.app.testing import setup
      >>> setup.setUpTraversal()

    Now initialize this info and test it:

      >>> info = CalendarEventBreadcrumbInfo(event, request)
      >>> info.url
      'http://127.0.0.1/+1243@localhost/edit.html'
    """

    @property
    def url(self):
        name = urllib.quote(self.context.__name__.encode('utf-8'), "@+")
        parent_info = zapi.getMultiAdapter(
            (self.context.__parent__, self.request), IBreadcrumbInfo)
        return '%s/%s/edit.html' %(parent_info.url, name)

CalendarBreadcrumbInfo = breadcrumbs.CustomNameBreadCrumbInfo(_('Calendar'))
