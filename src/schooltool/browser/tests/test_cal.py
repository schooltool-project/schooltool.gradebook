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
Tests for SchoolTool-specific calendar views.

$Id$
"""

import unittest
from datetime import date, timedelta, time
from zope.testing import doctest
from zope.interface import directlyProvides
from zope.publisher.browser import TestRequest
from zope.app.tests import setup, ztapi
from zope.app.traversing.interfaces import IContainmentRoot
from zope.app.pagetemplate.simpleviewclass import SimpleViewClass

from schoolbell.app.browser.tests.setup import setUp, tearDown

from schooltool.common import parse_datetime
from schooltool.timetable import SchooldayTemplate, SchooldayPeriod
from schooltool.timetable import SequentialDaysTimetableModel
from pytz import timezone

utc = timezone('UTC')


def setUpSchoolToolSite():
    from schooltool.app import SchoolToolApplication
    app = SchoolToolApplication()
    directlyProvides(app, IContainmentRoot)
    from zope.app.component.site import LocalSiteManager
    app.setSiteManager(LocalSiteManager(app))
    from zope.app.component.hooks import setSite
    setSite(app)
    return app


def dt(timestr):
    dt = parse_datetime('2004-11-05 %s:00' % timestr)
    return dt.replace(tzinfo=utc)


class TestDailyCalendarView(unittest.TestCase):

    def setUp(self):
        from schooltool.app import getPersonPreferences
        from schooltool.interfaces import IPersonPreferences
        from schoolbell.app.interfaces import IHavePreferences

        # set up adaptation (the view checks user preferences)
        setup.placelessSetUp()
        setup.setUpAnnotations()
        ztapi.provideAdapter(IHavePreferences, IPersonPreferences,
                             getPersonPreferences)

        # set up the site
        app = setUpSchoolToolSite()
        from schooltool.app import Person
        self.person = app['persons']['person'] = Person('person')

        # set up the timetable schema
        days = ['A', 'B', 'C']
        schema = self.createSchema(days,
                                   ['1', '2', '3', '4'],
                                   ['1', '2', '3', '4'],
                                   ['1', '2', '3', '4'])
        template = SchooldayTemplate()
        template.add(SchooldayPeriod('1', time(9, 0), timedelta(hours=1)))
        template.add(SchooldayPeriod('2', time(10, 15), timedelta(hours=1)))
        template.add(SchooldayPeriod('3', time(11, 30), timedelta(hours=1)))
        template.add(SchooldayPeriod('4', time(12, 30), timedelta(hours=1)))
        schema.model = SequentialDaysTimetableModel(days, {None: template})

        app['ttschemas']['default'] = schema

        # set up terms
        from schooltool.timetable import Term
        app['terms']['term'] = term = Term("Some term", date(2004, 9, 1),
                                           date(2004, 12, 31))
        term.add(date(2004, 11, 5))

    def tearDown(self):
        setup.placelessTearDown()

    def createSchema(self, days, *periods_for_each_day):
        """Create a timetable schema."""
        from schooltool.timetable import TimetableSchema
        from schooltool.timetable import TimetableSchemaDay
        schema = TimetableSchema(days)
        for day, periods in zip(days, periods_for_each_day):
            schema[day] = TimetableSchemaDay(list(periods))
        return schema

    def test_calendarRows(self):
        from schooltool.browser.cal import DailyCalendarView
        from schoolbell.app.security import Principal

        request = TestRequest()
        principal = Principal('person', 'Some person', person=self.person)
        request.setPrincipal(principal)
        view = DailyCalendarView(self.person.calendar, request)
        view.cursor = date(2004, 11, 5)

        result = list(view.calendarRows())

        expected = [("8:00", dt('08:00'), timedelta(hours=1)),
                    ("1", dt('09:00'), timedelta(hours=1)),
                    ("10:00", dt('10:00'), timedelta(minutes=15)),
                    ("2", dt('10:15'), timedelta(hours=1)),
                    ("11:15", dt('11:15'), timedelta(minutes=15)),
                    ("3", dt('11:30'), timedelta(hours=1)),
                    ("4", dt('12:30'), timedelta(hours=1)),
                    ("13:30", dt('13:30'), timedelta(minutes=30)),
                    ("14:00", dt('14:00'), timedelta(hours=1)),
                    ("15:00", dt('15:00'), timedelta(hours=1)),
                    ("16:00", dt('16:00'), timedelta(hours=1)),
                    ("17:00", dt('17:00'), timedelta(hours=1)),
                    ("18:00", dt('18:00'), timedelta(hours=1))]

        self.assertEquals(result, expected)

    def test_calendarRows_no_periods(self):
        from schooltool.browser.cal import DailyCalendarView
        from schooltool.app import getPersonPreferences
        from schoolbell.app.security import Principal

        prefs = getPersonPreferences(self.person)
        prefs.cal_periods = False # do not show periods
        request = TestRequest()
        principal = Principal('person', 'Some person', person=self.person)
        request.setPrincipal(principal)
        view = DailyCalendarView(self.person.calendar, request)
        view.cursor = date(2004, 11, 5)

        result = list(view.calendarRows())

        expected = [("%d:00" % i, dt('%d:00' % i), timedelta(hours=1))
                    for i in range(8, 19)]
        self.assertEquals(result, expected)

    def test_calendarRows_default(self):
        from schooltool.browser.cal import DailyCalendarView

        request = TestRequest()
        # do not set the principal
        view = DailyCalendarView(self.person.calendar, request)
        view.cursor = date(2004, 11, 5)

        result = list(view.calendarRows())

        # the default is not to show periods
        expected = [("%d:00" % i, dt('%d:00' % i), timedelta(hours=1))
                    for i in range(8, 19)]
        self.assertEquals(result, expected)


def doctest_CalendarSTOverlayView():
    r"""Tests for CalendarSTOverlayView

        >>> from schooltool.browser.cal import CalendarSTOverlayView
        >>> View = SimpleViewClass('../templates/calendar_overlay.pt',
        ...                        bases=(CalendarSTOverlayView,))

    CalendarOverlayView is a view on anything.

        >>> context = object()
        >>> request = TestRequest()
        >>> view = View(context, request)

    It renders to an empty string unless its context is the calendar of the
    authenticated user

        >>> view()
        u'\n'

    If you are an authenticated user looking at your own calendar, this view
    renders a calendar selection portlet.

        >>> from schooltool.app import Person, Group
        >>> from schoolbell.app.security import Principal
        >>> app = setUpSchoolToolSite()
        >>> person = app['persons']['whatever'] = Person('fred')
        >>> group1 = app['groups']['g1'] = Group(title="Group 1")
        >>> group2 = app['groups']['g2'] = Group(title="Group 2")
        >>> person.overlaid_calendars.add(group1.calendar, show=True,
        ...                               show_timetables=False)
        >>> person.overlaid_calendars.add(group2.calendar, show=False,
        ...                               show_timetables=True)

        >>> request = TestRequest()
        >>> request.setPrincipal(Principal('id', 'title', person))
        >>> view = View(person.calendar, request)

        >>> print view()
        <div id="portlet-calendar-overlay" class="portlet">
        ...
        <input type="checkbox" checked="checked" disabled="disabled" />
        <input type="checkbox" name="my_timetable"
               checked="checked" />
        My Calendar
        ...
        <input type="checkbox" name="overlay:list"
               checked="checked" value="/groups/g1" />
        <input type="checkbox"
               name="overlay_timetables:list"
               value="/groups/g1" />
        ...
        <input type="checkbox" name="overlay:list"
               value="/groups/g2" />
        <input type="checkbox" name="overlay_timetables:list"
               checked="checked" value="/groups/g2" />
        ...
        </div>

    If the request has 'OVERLAY_APPLY', CalendarOverlayView applies your
    changes

        >>> request.form['overlay'] = [u'/groups/g2']
        >>> request.form['overlay_timetables'] = [u'/groups/g1']
        >>> request.form['OVERLAY_APPLY'] = u"Apply"
        >>> print view()
        <div id="portlet-calendar-overlay" class="portlet">
        ...
        <input type="checkbox" checked="checked" disabled="disabled" />
        <input type="checkbox" name="my_timetable" />
        My Calendar
        ...
        <input type="checkbox" name="overlay:list"
               value="/groups/g1" />
        <input type="checkbox"
               name="overlay_timetables:list"
               checked="checked" value="/groups/g1" />
        ...
        <input type="checkbox" name="overlay:list"
               checked="checked" value="/groups/g2" />
        <input type="checkbox" name="overlay_timetables:list"
               value="/groups/g2" />
        ...
        </div>

    It also redirects you to request.URL:

        >>> request.response.getStatus()
        302
        >>> request.response.getHeader('Location')
        'http://127.0.0.1'

    There are two reasons for the redirect: first, part of the page template
    just rendered might have become invalid when calendar overlay selection
    changed, second, this lets the user refresh the page without having to
    experience confirmation dialogs that say "Do you want to POST this form
    again?".

    If the request has 'OVERLAY_MORE', CalendarOverlayView redirects to
    calendar_selection.html

        >>> request = TestRequest()
        >>> request.setPrincipal(Principal('id', 'title', person))
        >>> request.form['OVERLAY_MORE'] = u"More..."
        >>> view = View(person.calendar, request)
        >>> content = view()
        >>> request.response.getStatus()
        302
        >>> request.response.getHeader('Location')
        'http://127.0.0.1/persons/fred/calendar_selection.html?nexturl=http%3A//127.0.0.1'

    """


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestDailyCalendarView))
    suite.addTest(doctest.DocTestSuite(setUp=setUp, tearDown=tearDown,
                                       optionflags=doctest.ELLIPSIS|
                                                   doctest.REPORT_NDIFF|
                                                 doctest.NORMALIZE_WHITESPACE))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
