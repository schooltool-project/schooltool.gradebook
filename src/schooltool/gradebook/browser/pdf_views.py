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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
"""
PDF Views
"""

from datetime import datetime
from decimal import Decimal

from zope.cachedescriptors.property import Lazy
from zope.browserpage.viewpagetemplatefile import ViewPageTemplateFile
from zope.component import getUtility, getMultiAdapter
from zope.i18n.interfaces.locales import ICollator
from zope.security.proxy import removeSecurityProxy
from reportlab.lib import units

from schooltool.app.browser.app import ActiveSchoolYearContentMixin
from schooltool.app.interfaces import ISchoolToolApplication
from schooltool.app.browser.report import ReportPDFView
from schooltool.course.interfaces import ILearner, ISectionContainer
from schooltool.course.interfaces import ISection
from schooltool.person.interfaces import IPerson
from schooltool.person.interfaces import IPersonFactory
from schooltool.schoolyear.interfaces import ISchoolYear
from schooltool.term.interfaces import ITerm, IDateManager

import schooltool.table
from schooltool.skin import flourish
from schooltool.gradebook import GradebookMessage as _
from schooltool.gradebook.browser.gradebook import GradebookOverview
from schooltool.gradebook.browser.gradebook import convertAverage
from schooltool.gradebook.browser.report_card import (ABSENT_HEADING,
    TARDY_HEADING, ABSENT_ABBREVIATION, TARDY_ABBREVIATION, ABSENT_KEY,
    TARDY_KEY, AVERAGE_KEY, AVERAGE_HEADING)
from schooltool.gradebook.browser.report_utils import buildHTMLParagraphs
from schooltool.gradebook.interfaces import IGradebookRoot, IActivities
from schooltool.gradebook.interfaces import IGradebook
from schooltool.gradebook.interfaces import ISectionJournalData
from schooltool.requirement.interfaces import IEvaluations
from schooltool.requirement.interfaces import IDiscreteValuesScoreSystem
from schooltool.requirement.interfaces import IScoreSystemContainer
from schooltool.requirement.scoresystem import UNSCORED


def getSortingKey(request):
    collator = ICollator(request.locale)
    factory = getUtility(IPersonFactory)
    sorting_key = lambda x: factory.getSortingKey(x, collator)
    return sorting_key


class BasePDFView(ReportPDFView):
    """A base class for all PDF views"""

    def __init__(self, context, request):
        super(BasePDFView, self).__init__(context, request)
        self.current_term = getUtility(IDateManager).current_term
        if self.current_term is None:
            self.schoolyear = None
        else:
            self.schoolyear = ISchoolYear(self.current_term)
        if 'term' in self.request:
            self.term = self.schoolyear[self.request['term']]
        else:
            self.term = None

    def guessPeriodGroup(self, meeting):
        # XXX: this is a quick fix, evil in it's own way
        if meeting.period is not None:
            return meeting.period.title
        return meeting.dtstart.time().isoformat()[:5]

    def makeFileName(self, basename):
        timestamp = datetime.now().strftime('%y%m%d%H%M')
        return '%s_%s.pdf' % (basename, timestamp)


class TermPDFPage(flourish.report.PlainPDFPage):

    current_term = None
    schoolyear = None
    term = None

    @property
    def scope(self):
        scope = []
        if self.term is not None:
            scope.append(self.term.title)
        if self.schoolyear is not None:
            scope.append(self.schoolyear.title)
        return ' | '.join(scope)

    def updateTimespan(self):
        self.current_term = getUtility(IDateManager).current_term
        if self.current_term is not None:
            self.schoolyear = ISchoolYear(self.current_term)
        if 'term' in self.request:
            self.term = self.schoolyear.get(self.request['term'])

    def update(self):
        self.updateTimespan()
        super(TermPDFPage, self).update()

    def formatDate(self, date, format='mediumDate'):
        if date is None:
            return ''
        formatter = getMultiAdapter((date, self.request), name=format)
        return formatter()

    def guessPeriodGroup(self, meeting):
        # XXX: this is a copy-pasted quick fix, evil in it's own way
        if meeting.period is not None:
            return meeting.period.title
        return meeting.dtstart.time().isoformat()[:5]


class BaseStudentPDFView(BasePDFView):
    """A base class for all student PDF views"""

    def isJournalSource(self, layout):
        return layout.source in [ABSENT_KEY, TARDY_KEY]

    def getJournalScore(self, student, section, layout):
        jd = ISectionJournalData(section, None)
        if jd is None:
            return None
        result = 0
        for meeting in jd.recordedMeetings(student):
            grade = jd.getGrade(student, meeting)
            if grade == 'n' and layout.source == ABSENT_KEY:
                result += 1
            if grade == 'p' and layout.source == TARDY_KEY:
                result += 1
        return result or None

    def isAverageSource(self, layout):
        termName, worksheetName, activityName = layout.source.split('|')
        return activityName == AVERAGE_KEY

    def getAverageScore(self, student, section, layout):
        termName, worksheetName, activityName = layout.source.split('|')
        activities = IActivities(section)
        if worksheetName not in activities:
            return None
        worksheet = activities[worksheetName]

        gradebook = removeSecurityProxy(IGradebook(worksheet))
        person = IPerson(self.request.principal, None)
        if person is None:
            columnPreferences = {}
        else:
            columnPreferences = gradebook.getColumnPreferences(person)
        prefs = columnPreferences.get('average', {})
        scoresystems = IScoreSystemContainer(ISchoolToolApplication(None))
        average_scoresystem = scoresystems.get(prefs.get('scoresystem', ''))

        total, average = gradebook.getWorksheetTotalAverage(worksheet, student)
        if average is UNSCORED:
            return None
        return convertAverage(average, average_scoresystem)

    def getActivity(self, section, layout):
        termName, worksheetName, activityName = layout.source.split('|')
        activities = IActivities(section)
        if worksheetName in activities:
            return activities[worksheetName][activityName]
        return None

    def getLayoutActivityHeading(self, layout, truncate=True):
        if layout.source == ABSENT_KEY:
            return ABSENT_HEADING
        if layout.source == TARDY_KEY:
            return TARDY_HEADING
        termName, worksheetName, activityName = layout.source.split('|')
        if activityName == AVERAGE_KEY:
            return AVERAGE_HEADING
        root = IGradebookRoot(ISchoolToolApplication(None))
        heading = root.deployed[worksheetName][activityName].title
        if len(layout.heading):
            heading = layout.heading
        if truncate:
            heading = heading[:5]
        return heading

    def getCourseTitle(self, course, sections):
        teachers = []
        for section in sections:
            if course == tuple(section.courses):
                for teacher in section.instructors:
                    if teacher not in teachers:
                        teachers.append(teacher)
        courseTitles = ', '.join(c.title for c in course)
        teacherNames = [teacher.title for teacher in teachers]
        teacherNames = ', '.join(teacherNames)
        return '%s (%s)' % (courseTitles, teacherNames)

    def getGrid(self, student, sections):
        root = IGradebookRoot(ISchoolToolApplication(None))
        if self.schoolyear.__name__ in root.layouts:
            layouts = root.layouts[self.schoolyear.__name__].columns
        else:
            layouts = []

        courses = []
        for section in sections:
            course = tuple(section.courses)
            if course not in courses:
                courses.append(course)

        scores = {}
        evaluations = IEvaluations(student)
        for layout in layouts:
            byCourse = {}
            for section in sections:
                course = tuple(section.courses)
                if self.isJournalSource(layout):
                    score = self.getJournalScore(student, section, layout)
                    if score is not None:
                        if course in byCourse:
                            score += int(byCourse[course])
                        byCourse[course] = unicode(score)
                elif self.isAverageSource(layout):
                    score = self.getAverageScore(student, section, layout)
                    if score is not None:
                        byCourse[course] = unicode(score)
                else:
                    activity = self.getActivity(section, layout)
                    if activity is None:
                        continue
                    score = evaluations.get(activity, None)
                    if score:
                        byCourse[course] = unicode(score.value)
            if len(byCourse):
                scores[layout.source] = byCourse

        scoredLayouts = [l for l in layouts if l.source in scores]

        headings = []
        for layout in scoredLayouts:
            headings.append(self.getLayoutActivityHeading(layout))

        rows = []
        for course in courses:
            grid_scores = []
            for layout in scoredLayouts:
                byCourse = scores[layout.source]
                score = byCourse.get(course, '')
                grid_scores.append(score)

            row = {
                'title': self.getCourseTitle(course, sections),
                'scores': grid_scores,
                }
            rows.append(row)

        return {
            'headings': headings,
            'widths': '8.2cm' + ',1.6cm' * len(scoredLayouts),
            'rows': rows,
            }


class BaseReportCardPDFView(BaseStudentPDFView):
    """The report card (PDF) base class"""

    template=ViewPageTemplateFile('rml/report_card_rml.pt')

    def __call__(self):
        """Make sure there is a current term."""
        if self.current_term is None:
            template = ViewPageTemplateFile('templates/no_current_term.pt')
            return template(self)
        return super(BaseReportCardPDFView, self).__call__()

    def title(self):
        return _('Report Card: ${schoolyear}',
                 mapping={'schoolyear': self.schoolyear.title})

    def course_heading(self):
        return _('Courses')

    def students(self):
        results = []
        for student in self.collectStudents():
            student_title = _('Student: ${student}',
                              mapping={'student': student.title})

            sections = []
            for section in ILearner(student).sections():
                term = ITerm(section)
                schoolyear = ISchoolYear(term)
                if schoolyear != self.schoolyear:
                    continue
                if self.term is not None and term != self.term:
                    continue
                sections.append(section)

            result = {
                'title': student_title,
                'grid': self.getGrid(student, sections),
                'outline': self.getOutline(student, sections),
                }

            results.append(result)
        return results

    def getOutline(self, student, sections):
        root = IGradebookRoot(ISchoolToolApplication(None))
        if self.schoolyear.__name__ in root.layouts:
            layouts = root.layouts[self.schoolyear.__name__].outline_activities
        else:
            layouts = []
        evaluations = IEvaluations(student)

        section_list = []
        for section in sections:
            worksheets = []
            term = ITerm(section)
            for layout in layouts:
                termName, worksheetName, activityName = layout.source.split('|')
                activities = IActivities(section)
                if worksheetName not in activities:
                    continue
                if activityName not in activities[worksheetName]:
                    continue
                activity = activities[worksheetName][activityName]

                score = evaluations.get(activity, None)
                if not score:
                    continue

                for worksheet in worksheets:
                    if worksheet['name'] == worksheetName:
                        break
                else:
                    worksheet = {
                        'name': worksheetName,
                        'heading': activities[worksheetName].title,
                        'activities': [],
                        }
                    worksheets.append(worksheet)

                heading = self.getLayoutActivityHeading(layout, truncate=False)
                activity_result = {
                    'heading': heading,
                    'value': buildHTMLParagraphs(unicode(score.value)),
                    }

                worksheet['activities'].append(activity_result)

            if len(worksheets):
                section_result = {
                    'heading': "%s - %s" % (term.title, section.title),
                    'worksheets': worksheets,
                    }
                section_list.append(section_result)

        return section_list


class StudentReportCardPDFView(BaseReportCardPDFView):
    """A view for printing a report card for a student"""

    def collectStudents(self):
        return [self.context]

    @property
    def filename(self):
        return self.makeFileName('report_card_%s' % self.context.username)


class GroupReportCardPDFView(BaseReportCardPDFView):
    """A view for printing a report card for each person in a group"""

    def collectStudents(self):
        return list(self.context.members)

    @property
    def filename(self):
        return self.makeFileName('report_card_%s' % self.context.__name__)


class BaseStudentDetailPDFView(BaseStudentPDFView):
    """The report card (PDF) base class"""

    template=ViewPageTemplateFile('rml/student_detail_rml.pt')

    def __call__(self):
        """Make sure there is a current term."""
        if self.current_term is None:
            template = ViewPageTemplateFile('templates/no_current_term.pt')
            return template(self)
        return super(BaseStudentDetailPDFView, self).__call__()

    def title(self):
        return _('Detailed Student Report: ${schoolyear}',
                 mapping={'schoolyear': self.schoolyear.title})

    def grades_heading(self):
        return _('Grade Detail')

    def course_heading(self):
        return _('Courses')

    def attendance_heading(self):
        return _('Attendance Detail')

    def date_heading(self):
        return _('Dates')

    def name_heading(self):
        return _('Student Name')

    def userid_heading(self):
        return _('User Id')

    def grades(self, student):
        sections = []
        for section in ILearner(student).sections():
            term = ITerm(section)
            schoolyear = ISchoolYear(term)
            if schoolyear != self.schoolyear:
                continue
            if self.term is not None and term != self.term:
                continue
            sections.append(section)
        return self.getGrid(student, sections)

    def attendance(self, student):
        data = {}
        sections = []
        for section in ILearner(student).sections():
            term = ITerm(section)
            schoolyear = ISchoolYear(term)
            if schoolyear != self.schoolyear:
                continue
            if self.term is not None and term != self.term:
                continue
            sections.append(section)
        for section in sections:
            jd = ISectionJournalData(section, None)
            if jd is None:
                continue
            for meeting in jd.recordedMeetings(student):
                period = self.guessPeriodGroup(meeting)
                day = meeting.dtstart
                grade = jd.getGrade(student, meeting)
                result = ''
                if grade == 'n':
                    result = ABSENT_ABBREVIATION
                if grade == 'p':
                    result = TARDY_ABBREVIATION
                if result:
                    data.setdefault(day, {})[period] = result

        periods = {}
        for day in data:
            for period in data[day]:
                periods[period] = 0
        periods = sorted(periods.keys())

        widths = '4cm'
        for period in periods:
            width = 1
            if len(period) > 4:
                width = float(len(period)) / 4.5
            widths += ',%fcm' % width

        rows = []
        for day in sorted(data):
            scores = [''] * len(periods)
            for period in data[day]:
                index = periods.index(period)
                scores[index] = data[day][period]
            row = {
                'title': day.strftime('%x'),
                'scores': scores,
                }
            rows.append(row)

        return {
            'widths': widths,
            'headings': periods,
            'rows': rows,
            }

    def students(self):
        results = []
        for student in self.collectStudents():
            result = {
                'name': student.title,
                'userid': student.username,
                'grades': self.grades(student),
                'attendance': self.attendance(student),
                }
            results.append(result)
        return results


class StudentDetailPDFView(BaseStudentDetailPDFView):
    """A view for printing a report card for a student"""

    def collectStudents(self):
        return [self.context]

    @property
    def filename(self):
        return self.makeFileName('student_detail_%s' % self.context.username)


class GroupDetailPDFView(BaseStudentDetailPDFView):
    """A view for printing a report card for each person in a group"""

    def collectStudents(self):
        return list(self.context.members)

    @property
    def filename(self):
        return self.makeFileName('student_detail_%s' % self.context.__name__)


class FailingReportPDFView(flourish.report.PlainPDFPage):
    """A view for printing a report of all the students failing an activity"""

    content_template = flourish.templates.XMLFile('rml/failing_report_rml.pt')

    name = _("Failures by Term")

    @property
    def message_title(self):
        return _("term ${term} failures",
                 mapping={'term': self.term.title})

    def __init__(self, context, request):
        super(FailingReportPDFView, self).__init__(context, request)
        self.term = self.context
        self.activity = self.getActivity()
        self.score = self.request.get('min', None)

    def getActivity(self):
        source = self.request.get('activity', None)
        if source is None:
            return None
        termName, worksheetName, activityName = source.split('|')
        root = IGradebookRoot(ISchoolToolApplication(None))
        return root.deployed[worksheetName][activityName]

    def formatDate(self, date, format='mediumDate'):
        if date is None:
            return ''
        formatter = getMultiAdapter((date, self.request), name=format)
        return formatter()

    @property
    def scope(self):
        term = ITerm(self.context)
        first = self.formatDate(term.first)
        last = self.formatDate(term.last)
        return '%s | %s - %s' % (term.title, first, last)

    @property
    def base_filename(self):
        return 'failures_%s' % self.term.__name__

    @property
    def subtitles_left(self):
        subtitles = [
            _('Report Sheet: ${worksheet}', mapping={
                    'worksheet': self.activity.__parent__.title}),
            _('Activity: ${activity}', mapping={
                    'activity': self.activity.title}),
            _('Passing Score: ${score}', mapping={
                    'score': self.request.get('min', '')}),
            ]
        return subtitles

    def heading_message(self):
        return _('The following students are at risk of failing the following courses:')

    def getSectionData(self, section):
        data = []
        for worksheet in IActivities(section).values():
            if worksheet.__name__ == self.activity.__parent__.__name__:
                gb = IGradebook(worksheet)
                activity = worksheet[self.activity.__name__]
                break
        else:
            return []
        for student in gb.students:
            score = gb.getScore(student, activity)
            if not score:
                continue
            failure = False
            if IDiscreteValuesScoreSystem.providedBy(score.scoreSystem):
                for definition in score.scoreSystem.scores:
                    if definition[0] == self.score:
                        passing_value = definition[2]
                    if definition[0] == score.value:
                        this_value = definition[2]
                if score.scoreSystem._isMaxPassingScore:
                    if this_value > passing_value:
                        failure = True
                elif this_value < passing_value:
                    failure = True
            else:
                passing_value = Decimal(self.score)
                this_value = score.value
                if this_value < passing_value:
                    failure = True
            if failure:
                data.append([student, score.value])
        return data

    def students(self):
        student_rows = {}
        for section in ISectionContainer(self.term).values():
            for student, value in self.getSectionData(section):
                rows = student_rows.setdefault(student, [])
                row = {
                    'section': section,
                    'grade': value,
                    }
                rows.append(row)

        results = []
        for student in sorted(student_rows,  key=getSortingKey(self.request)):
            rows = []
            for student_row in student_rows[student]:
                teacher = list(student_row['section'].instructors)[0]
                row = {
                    'course': list(student_row['section'].courses)[0].title,
                    'teacher': teacher.title,
                    'grade': student_row['grade'],
                    }
                rows.append(row)
            result = {
                'name': student.title,
                'rows': rows,
                }
            results.append(result)
        return results


class AbsencesByDayPDFView(TermPDFPage):

    name = _('ABSENCES BY DAY')

    @property
    def message_title(self):
        day = self.getDay()
        if day is None:
            return _('absences by day report')
        return _('absences for ${day}',
                 mapping={'day': self.formatDate(day)})

    @property
    def title(self):
        for_date = self.getDay()
        if for_date is None:
            return None
        formatted_date = self.formatDate(for_date, format="fullDate")
        return formatted_date

    @property
    def base_filename(self):
        day = self.getDay()
        if day is None:
            filename = 'abs_day_' + self.context.__name__
        else:
            filename = 'abs_day_%d_%02d_%02d' % (day.year, day.month, day.day)
        return filename

    def getDay(self):
        day = self.request.get('day', None)
        if day is None:
            return datetime.date(datetime.now())
        try:
            year, month, day = [int(part) for part in day.split('-')]
            return datetime.date(datetime(year, month, day))
        except (TypeError, ValueError):
            pass
        try:
            return datetime.date(day)
        except (TypeError, ValueError):
            return None

    def formatDate(self, date, format='mediumDate'):
        if date is None:
            return ''
        formatter = getMultiAdapter((date, self.request), name=format)
        return formatter()

    def compareDates(self, first, second):
        return (first.year == second.year and first.month == second.month and
                first.day == second.day)

    def getData(self):
        day = self.getDay()
        if day is None:
            return []
        for term in self.schoolyear.values():
            if day in term:
                break
        else:
            return []

        data = {}
        for section in ISectionContainer(term).values():
            jd = ISectionJournalData(section, None)
            if jd is None:
                continue
            for student in section.members:
                for meeting in jd.recordedMeetings(student):
                    if not self.compareDates(meeting.dtstart, day):
                        continue
                    period = self.guessPeriodGroup(meeting)
                    grade = jd.getGrade(student, meeting)
                    result = ''
                    if grade == 'n':
                        result = ABSENT_ABBREVIATION
                    if grade == 'p':
                        result = TARDY_ABBREVIATION
                    if result:
                        data.setdefault(student, {})[period] = result
        return data

    def getPeriods(self, data):
        periods = {}
        for student in data:
            for period in data[student]:
                periods[period] = 0
        return sorted(periods.keys())

    def widths(self):
        data = self.getData()
        periods = self.getPeriods(data)
        n_cols = len(periods)
        if not n_cols:
            return None
        col_width = max(int(40./n_cols), 8)
        widths_string = ' '.join(
            ['%d%%' % max((100-col_width*n_cols), 10)] +
            ['%d%%' % col_width] * (n_cols)
            )
        return widths_string

    def header_widths(self):
        return '60% 40%'

    def periods(self):
        data = self.getData()
        return self.getPeriods(data)

    def students(self):
        data = self.getData()
        periods = self.getPeriods(data)

        rows = []
        for student in sorted(data, key=getSortingKey(self.request)):
            scores = [''] * len(periods)
            for period in data[student]:
                index = periods.index(period)
                scores[index] = data[student][period]
            row = {
                'name': student.title,
                'periods': scores,
                }
            rows.append(row)
        return rows


class SectionAbsencesPDFView(TermPDFPage):
    """A view for printing a report with absences for a given section"""

    name = _('SECTION ABSENCES')

    @property
    def message_title(self):
        return _('${section} absence report',
                 mapping={'section': self.section.title})

    @property
    def title(self):
        return self.section.title

    @property
    def section(self):
        return self.context

    @property
    def subtitles_left(self):
        instructors = [teacher.title
                       for teacher in self.section.instructors]
        subtitles = [
            _('Teacher(s): ${instructors}',
              mapping={'instructors': ', '.join(instructors)})
            ]
        return subtitles

    @property
    def base_filename(self):
        courses = [c.__name__ for c in self.section.courses]
        filename = 'abs_section_%s' % '_'.join(courses)
        return filename

    def updateTimespan(self):
        self.term = ITerm(self.section)
        self.schoolyear = ISchoolYear(self.term)
        self.current_term = getUtility(IDateManager).current_term

    def getStudentData(self, jd, student):
        student_data = {}
        student_data['absences'] = 0
        student_data['tardies'] = 0
        for meeting in jd.recordedMeetings(student):
            grade = jd.getGrade(student, meeting)
            if grade == 'n':
                student_data['absences'] += 1
            if grade == 'p':
                student_data['tardies'] += 1
        return student_data

    def students(self):
        data = {}
        jd = ISectionJournalData(self.section, None)
        if jd is not None:
            for student in self.section.members:
                student_data = self.getStudentData(jd, student)
                if student_data['absences'] + student_data['tardies'] > 0:
                    data[student] = student_data

        rows = []
        for student in sorted(data, key=getSortingKey(self.request)):
            row = {
                'name': student.title,
                'absences': data[student]['absences'],
                'tardies': data[student]['tardies'],
                'total': data[student]['absences'] + data[student]['tardies'],
                }
            rows.append(row)
        return rows


class GradebookPDFView(BasePDFView, GradebookOverview):
    """The gradebook pdf view class"""

    template=ViewPageTemplateFile('rml/gradebook_rml.pt')
    topMargin = 30
    leftMargin = 35

    def __init__(self, context, request):
        super(GradebookPDFView, self).__init__(context, request)
        self.person = IPerson(self.request.principal)
        self.sortKey = self.context.getSortKey(self.person)
        self.processColumnPreferences()
        self.worksheet = removeSecurityProxy(context).context
        self.section = ISection(self.worksheet)
        self.term = ITerm(self.section)

    def pages(self):
        results = []
        activities = list(self.activities())

        table = self.table()

        num_rows = len(table)
        num_cols = len(self.activities())
        start_row, start_col = 0, 0
        max_rows, max_cols = 34, 8
        if not self.absences_hide:
            max_cols -= 1
        if not self.tardies_hide:
            max_cols -= 1
        if not self.total_hide:
            max_cols -= 1
        if not self.average_hide:
            max_cols -= 1

        while True:
            end_row = start_row + max_rows
            if end_row > num_rows:
                end_row = num_rows
            next_row = start_row

            next_col = start_col + max_cols
            if next_col >= num_cols:
                end_col = num_cols
                next_col = 0
                next_row = end_row
            else:
                end_col = next_col

            rows = [dict(r) for r in table[start_row:end_row]]
            for row in rows:
                row['grades'] = row['grades'][start_col:end_col]

            page = {
                'widths': self.widths(start_col, end_col),
                'rows': rows,
                'cols': activities[start_col:end_col],
                }
            results.append(page)

            if next_row < num_rows:
                start_row, start_col = next_row, next_col
            else:
                break

        return results

    def title(self):
        return _('Gradebook Report')

    def term_heading(self):
        return _('Term')

    def section_heading(self):
        return _('Section')

    def worksheet_heading(self):
        return _('Worksheet')

    def student_heading(self):
        return _('Student')

    def widths(self, start_col, end_col):
        num_cols = end_col - start_col
        if not self.absences_hide:
            num_cols += 1
        if not self.tardies_hide:
            num_cols += 1
        if not self.total_hide:
            num_cols += 1
        if not self.average_hide:
            num_cols += 1
        return '6cm' +',1.6cm' * (num_cols)


class FlourishGradebookPDFView(flourish.report.PlainPDFPage,
                               GradebookOverview):

    name = _("Gradebook")

    content_template=flourish.templates.Inline('''
    <tal:block repeat="worksheet view/worksheets"
               content="structure worksheet/schooltool:content/grid" />
    ''')

    def formatDate(self, date, format='mediumDate'):
        if date is None:
            return ''
        formatter = getMultiAdapter((date, self.request), name=format)
        return formatter()

    @property
    def message_title(self):
        return _('${section} gradebook',
                 mapping={'section': self.section.title})

    @property
    def scope(self):
        term = ITerm(self.section)
        schoolyear = ISchoolYear(term)
        return '%s | %s' % (term.title, schoolyear.title)

    @property
    def title(self):
        return ', '.join([course.title for course in self.section.courses])

    @property
    def subtitles_left(self):
        section = removeSecurityProxy(self.section)
        instructors = '; '.join([person.title
                                 for person in section.instructors])
        instructors_message = _('Instructors: ${instructors}',
                                mapping={'instructors': instructors})
        subtitles = [
            '%s (%s)' % (section.title, section.__name__),
            instructors_message,
            ]
        return subtitles

    @property
    def base_filename(self):
        courses = [c.__name__ for c in self.section.courses]
        worksheet = self.context.__parent__
        return 'gradebook_%s_%s' % ('_'.join(courses), worksheet.title)

    @Lazy
    def worksheets(self):
        worksheet = removeSecurityProxy(self.context).context
        return [worksheet]

    @Lazy
    def section(self):
        worksheet = removeSecurityProxy(self.context).context
        section = ISection(worksheet)
        return section

    def updateGradebookOverview(self):
        self.person = IPerson(self.request.principal)
        self.sortKey = self.context.getSortKey(self.person)
        self.processColumnPreferences()

    def update(self):
        super(FlourishGradebookPDFView, self).update()
        self.updateGradebookOverview()


class WorksheetGrid(schooltool.table.pdf.GridContentBlock):

    absences_column = None
    tardies_column = None
    total_column = None
    average_column = None

    @property
    def title(self):
        return self.worksheet.title

    @property
    def worksheet(self):
        return self.context

    @property
    def gradebook_overview(self):
        return self.view

    def updateColumns(self):
        self.columns = []
        for info in self.gradebook_overview.filtered_activity_info:
            self.columns.append(schooltool.table.pdf.GridColumn(
                info['longTitle'], item=info['hash']
                ))
        if not self.gradebook_overview.absences_hide:
            self.absences_column = schooltool.table.pdf.GridColumn(
                self.gradebook_overview.absences_label,
                item='schooltool.gradebook.absences'
                )
            self.columns.append(self.absences_column)
        if not self.gradebook_overview.tardies_hide:
            self.tardies_column = schooltool.table.pdf.GridColumn(
                self.gradebook_overview.tardies_label,
                item='schooltool.gradebook.tardies',
                )
            self.columns.append(self.tardies_column)
        if not self.gradebook_overview.total_hide:
            self.total_column = schooltool.table.pdf.GridColumn(
                self.gradebook_overview.total_label, font_name='Ubuntu_Bold',
                item='schooltool.gradebook.total',
                )
            self.columns.append(self.total_column)
        if not self.gradebook_overview.average_hide:
            self.average_column = schooltool.table.pdf.GridColumn(
                self.gradebook_overview.average_label, font_name='Ubuntu_Bold',
                item='schooltool.gradebook.average',
                )
            self.columns.append(self.average_column)

    def updateRows(self):
        self.rows = []
        collator = ICollator(self.request.locale)
        for info in sorted(self.gradebook_overview.students_info,
                           key=lambda info: collator.key(info['title'])):
            self.rows.append(schooltool.table.pdf.GridRow(
                info['title'], item=info['id']
                ))

    def updateData(self):
        cols_by_hash = dict([(col.item, col) for col in self.columns])
        rows_by_id = dict([(row.item, row) for row in self.rows])
        self.grid = {}
        table = self.gradebook_overview.table(self.worksheet)
        for info in table:
            row = rows_by_id.get(info['student']['id'])
            for grade in info['grades']:
                col = cols_by_hash.get(grade['activity'])
                if (row is not None and
                    col is not None):
                    self.grid[row, col] = grade['value']
            if self.absences_column is not None:
                self.grid[row, self.absences_column] = info.get('absences', u'')
            if self.tardies_column is not None:
                self.grid[row, self.tardies_column] = info.get('tardies', u'')
            if self.total_column is not None:
                self.grid[row, self.total_column] = info.get('total', u'')
            if self.average_column is not None:
                self.grid[row, self.average_column] = info.get('average', u'')

    def updateGrid(self):
        super(WorksheetGrid, self).updateGrid()
        self.updateColumns()
        self.updateRows()
        self.updateData()


# XXX: this is duplicated in CanDo, move to core?
class NoHeaderPlainPageTemplate(flourish.report.PlainPageTemplate):

    @property
    def header(self):
        default = super(NoHeaderPlainPageTemplate, self).header
        default['height'] = 0
        return default


class FlourishStudentReportCardPDFView(flourish.report.PlainPDFPage,
                                       ActiveSchoolYearContentMixin,
                                       BaseStudentPDFView):

    name = _('Report Card')

    def students(self):
        return [self.context]

    def scope(self):
        schoolyear = self.schoolyear
        return schoolyear.title if schoolyear is not None else ''

    @property
    def base_filename(self):
        return 'report_card_%s' % self.context.__name__

    @property
    def message_title(self):
        return _('${student} report card',
                 mapping={'student': self.context.title})


class FlourishGroupReportCardPDFView(FlourishStudentReportCardPDFView):

    def students(self):
        return sorted(self.context.members, key=getSortingKey(self.request))


class StudentReportCardPDFStory(flourish.report.PDFStory):

    template = flourish.templates.Inline('''
    <tal:loop repeat="student view/view/students">
      <tal:block replace="structure student/schooltool:content/report_card" />
    </tal:loop>
    ''')


class StudentReportCardViewletManager(flourish.viewlet.ViewletManager):

    pass


class ReportCardStudentHeaderViewlet(flourish.viewlet.Viewlet):

    template = flourish.templates.XMLFile('rml/report_card_student_header.pt')


class ReportCardStudentGradesViewlet(flourish.viewlet.Viewlet):

    template = flourish.templates.Inline('''
    <tal:block replace="structure view/report_card_grid" />
    ''')

    @property
    def report_card_grid(self):
        view = self.view.view
        grid = getMultiAdapter((self.context, self.request, view),
                               name='report_card_grid')
        grid.update()
        if grid.rows:
            return grid
        return ''


class ReportCardStudentGradesMixin(object):

    @property
    def student(self):
        return self.context

    @property
    def term(self):
        term_id = self.request.get('term_id')
        if self.schoolyear is not None:
            return self.schoolyear.get(term_id)

    @Lazy
    def sections(self):
        sections = []
        for section in ILearner(self.student).sections():
            term = ITerm(section)
            schoolyear = ISchoolYear(term)
            if ((schoolyear != self.schoolyear) or
                (self.term is not None and term != self.term)):
                continue
            sections.append(section)
        return sections

    @Lazy
    def courses(self):
        courses = []
        collator = ICollator(self.request.locale)
        for section in self.sections:
            course = tuple(section.courses)
            if course not in courses:
                courses.append(course)
        return sorted(courses,
                      key=lambda x:collator.key(self.pdf_view.getCourseTitle(x, self.sections)))

    @Lazy
    def layout_columns(self):
        root = IGradebookRoot(ISchoolToolApplication(None))
        if (self.schoolyear is not None and
            self.schoolyear.__name__ in root.layouts):
            return root.layouts[self.schoolyear.__name__].columns
        return []

    @Lazy
    def outline_activities(self):
        root = IGradebookRoot(ISchoolToolApplication(None))
        if (self.schoolyear is not None and
            self.schoolyear.__name__ in root.layouts):
            return root.layouts[self.schoolyear.__name__].outline_activities
        return []


class ReportCardStudentCommentsViewlet(ReportCardStudentGradesMixin,
                                       flourish.viewlet.Viewlet):

    template = flourish.templates.XMLFile(
        'rml/report_card_student_comments.pt')

    @property
    def pdf_view(self):
        return self.view.view

    @property
    def schoolyear(self):
        return self.pdf_view.schoolyear

    def comments_by_course(self):
        view = self.pdf_view
        result = []
        for course in self.courses:
            result.append({
                    'title': view.getCourseTitle(course, self.sections),
                    'comments': self.getComments(course, self.sections),
                    })
        return result

    def getComments(self, course, sections):
        result = []
        evaluations = IEvaluations(self.student)
        for section in sections:
            if tuple(section.courses) == course:
                term = ITerm(section)
                for outline_activity in self.outline_activities:
                    source = outline_activity.source
                    termName, worksheetName, activityName = source.split('|')
                    if termName != term.__name__:
                        continue
                    activities = IActivities(section)
                    if worksheetName not in activities:
                        continue
                    if activityName not in activities[worksheetName]:
                        continue
                    activity = activities[worksheetName][activityName]
                    score = evaluations.get(activity, None)
                    if not score:
                        continue
                    heading = self.pdf_view.getLayoutActivityHeading(
                        outline_activity, truncate=False)
                    html2rml = getMultiAdapter((score.value, self.request),
                                               name='html2rml')
                    html2rml.para_class = 'report_card_comment'
                    activity_result = {
                        'heading': heading,
                        'value': html2rml,
                        }
                    result.append(activity_result)
        return result


class ReportCardGrid(ReportCardStudentGradesMixin,
                     schooltool.table.pdf.GridContentBlock):

    title = _('Courses')

    @property
    def pdf_view(self):
        return self.view

    @property
    def schoolyear(self):
        return self.pdf_view.schoolyear

    def updateGrid(self):
        super(ReportCardGrid, self).updateGrid()
        self.updateColumns()
        self.updateRows()
        self.updateData()

    def updateTables(self):
        id_base = self.getRMLId()
        table_width = self.getTableWidth()
        table = schooltool.table.pdf.AutoFitGrid(
            self.rows, self.columns, self.grid, table_width,
            style_id=id_base+'-style',
            table_style_name='report_card_grades',
            title_column_width=5*units.cm,
            min_column_width=1.5*units.cm,
            continued_font_size=8,
            header_min_font_size=12)
        table.update()
        self.tables = [table]
        while table.remaining_columns:
            other = schooltool.table.pdf.AutoFitGrid(
                self.rows, table.remaining_columns, self.grid, table_width,
                style_id=id_base+'-style%d' % len(self.tables),
                config=table.config)
            other.update()
            self.tables.append(other)
            table = other

    def updateColumns(self):
        self.columns = []
        for i, layout_column in enumerate(self.layout_columns):
            heading = self.pdf_view.getLayoutActivityHeading(layout_column,
                                                             truncate=False)
            self.columns.append(schooltool.table.pdf.GridColumn(
                    heading, item=i, font_size=8))

    def updateRows(self):
        self.rows = []
        for course in self.courses:
            course_title = self.pdf_view.getCourseTitle(course, self.sections)
            self.rows.append(schooltool.table.pdf.GridRow(
                    course_title, item=course, para_class='report_card.table.row-title'))

    def updateData(self):
        cols_by_id = dict([(col.item, col) for col in self.columns])
        rows_by_id = dict([(row.item, row) for row in self.rows])
        self.grid = {}
        scores = {}
        evaluations = IEvaluations(self.student)
        for i, layout in enumerate(self.layout_columns):
            byCourse = {}
            for section in self.sections:
                course = tuple(section.courses)
                if self.pdf_view.isJournalSource(layout):
                    score = self.pdf_view.getJournalScore(
                        self.student, section, layout)
                    if score is not None:
                        if course in byCourse:
                            score += int(byCourse[course])
                        byCourse[course] = unicode(score)
                elif self.pdf_view.isAverageSource(layout):
                    score = self.pdf_view.getAverageScore(
                        self.student, section, layout)
                    if score is not None:
                        byCourse[course] = unicode(score)
                else:
                    activity = self.pdf_view.getActivity(section, layout)
                    if activity is None:
                        continue
                    score = evaluations.get(activity, None)
                    if score:
                        byCourse[course] = unicode(score.value)
            if len(byCourse):
                scores[layout.source] = byCourse
        for course in self.courses:
            for i, layout in enumerate(self.layout_columns):
                byCourse = scores.get(layout.source)
                if byCourse is not None:
                    score = byCourse.get(course, '')
                    self.grid[rows_by_id[course], cols_by_id[i]] = score
