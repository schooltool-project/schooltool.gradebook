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
"""Gradebook Views

$Id$
"""
__docformat__ = 'reStructuredText'
import zope.schema
from zope.security import proxy
from zope.app import zapi
from zope.app.keyreference.interfaces import IKeyReference
from zope.viewlet import viewlet

from schooltool.app import app
from schooltool.app.interfaces import ISchoolToolApplication
from schooltool.gradebook import interfaces
from schooltool.person.interfaces import IPerson
from schooltool.requirement.scoresystem import UNSCORED
from schooltool.securitypolicy.crowds import TeachersCrowd, StudentsCrowd
from schooltool.common import SchoolToolMessage as _

GradebookCSSViewlet = viewlet.CSSViewlet("gradebook.css")


class SectionFinder(object):
    """Base class for GradebookOverview and MyGradesView"""

    @property
    def isTeacher(self):
        return TeachersCrowd(self.context).contains(self.request.principal)

    @property
    def isStudent(self):
        return StudentsCrowd(self.context).contains(self.request.principal)

    def getSections(self):
        gradebook = proxy.removeSecurityProxy(self.context)
        for section in ISchoolToolApplication(None)['sections'].values():
            if self.isTeacher and not self.person in section.instructors:
                continue
            if self.isStudent and not self.person in section.members:
                continue
            url = zapi.absoluteURL(section, self.request)
            if self.isTeacher:
                url += '/gradebook'
            elif self.isStudent:
                url += '/mygrades'
            title = '%s<br/>%s' % (list(section.courses)[0].title, section.title)
            css = 'inactive-menu-item'
            if section == gradebook.context:
                css = 'active-menu-item'
            yield {'url': url, 'title': title, 'css': css}


class GradebookOverview(SectionFinder):
    """Gradebook Overview/Table"""

    def update(self):
        """Retrieve sorting information and store changes of it."""
        self.person = IPerson(self.request.principal)
        if 'sort_by' in self.request:
            sort_by = self.request['sort_by']
            key, reverse = self.context.getSortKey(self.person)
            if sort_by == key:
                reverse = not reverse
            else:
                reverse=False
            self.context.setSortKey(self.person, (sort_by, reverse))
        self.sortKey = self.context.getSortKey(self.person)

        """Handle change of current worksheet."""
        if 'currentWorksheet' in self.request:
            for worksheet in self.context.worksheets:
                if worksheet.title == self.request['currentWorksheet']:
                    self.context.setCurrentWorksheet(self.person, worksheet)
                    break

    def getCurrentWorksheet(self):
        return self.context.getCurrentWorksheet(self.person)

    def activities(self):
        """Get  a list of all activities."""
        result = [
            {'title': activity.title,
             'max':activity.scoresystem.getBestScore(),
             'hash': hash(IKeyReference(activity))}
            for activity in self.context.getCurrentActivities(self.person)]
        return result

    def table(self):
        """Generate the table of grades."""
        gradebook = proxy.removeSecurityProxy(self.context)
        worksheet = gradebook.getCurrentWorksheet(self.person)
        activities = [(hash(IKeyReference(activity)), activity)
            for activity in gradebook.getWorksheetActivities(worksheet)]
        rows = []
        for student in self.context.students:
            grades = []
            for act_hash, activity in activities:
                ev = gradebook.getEvaluation(student, activity)
                if ev is not None:
                    grades.append({'activity': act_hash, 'value': ev.value,
                                   'has_value': True})
                else:
                    grades.append({'activity': act_hash, 'value': '-',
                                   'has_value': False})

            average = str(gradebook.getWorksheetAverage(worksheet, student))

            rows.append(
                {'student': {'title': student.title, 'id': student.username},
                 'grades': grades,
                 'average': average})

        # Do the sorting
        key, reverse = self.sortKey
        def generateKey(row):
            if key != 'student':
                grades = dict([(str(grade['activity']), (grade['has_value'],
                                                         grade['value']))
                               for grade in row['grades']])
                if not grades.get(key, [None])[0]:
                    return (1, row['student']['title'])
                else:
                    return (0, grades.get(key)[1])
            return row['student']['title']

        return sorted(rows, key=generateKey, reverse=reverse)


class FinalGradesView(SectionFinder):
    """Final Grades Table for all students in the section"""

    def table(self):
        """Generate the table of grades."""
        gradebook = proxy.removeSecurityProxy(self.context)
        rows = []
        students = sorted(self.context.students, key=lambda x: x.title)
        for student in students:
            grades = []
            for worksheet in gradebook.worksheets:
                average = str(gradebook.getWorksheetAverage(worksheet, student))
                grades.append({'value': average})
            calculated = gradebook.getFinalGrade(student)
            final = gradebook.getAdjustedFinalGrade(self.person, student)
            adj_dict = gradebook.getFinalGradeAdjustment(self.person, student)
            adj_id = 'adj_' + student.username
            adj_value = adj_dict['adjustment']
            reason_id = 'reason_' + student.username
            reason_value = adj_dict['reason']

            rows.append(
                {'student': student,
                 'grades': grades,
                 'calculated': calculated,
                 'final': final,
                 'adjustment': {'id': adj_id, 'value': adj_value},
                 'reason': {'id': reason_id, 'value': reason_value}})

        return rows

    def update(self):
        """Retrieve final grade adjustments and store changes to them."""
        self.person = IPerson(self.request.principal)
        gradebook = proxy.removeSecurityProxy(self.context)
        students = sorted(self.context.students, key=lambda x: x.title)
        self.error_message = ''
        for student in students:
            adj_id = 'adj_' + student.username
            if adj_id in self.request:
                adj_value = self.request[adj_id]
                reason_value = self.request['reason_' + student.username]
                try:
                    gradebook.setFinalGradeAdjustment(self.person, student,
                        adj_value, reason_value)
                except ValueError, e:
                    if not self.error_message:
                        self.error_message = str(e)


class GradeStudent(object):
    """Grading a single student."""

    message = ''

    @property
    def student(self):
        id = self.request['student']
        school = app.getSchoolToolApplication()
        return school['persons'][id]

    @property
    def activities(self):
        return [
            {'title': activity.title,
             'max': activity.scoresystem.getBestScore(),
             'hash': hash(IKeyReference(activity))}
            for activity in self.context.getCurrentActivities(self.person)]

    def grades(self):
        activities = [(hash(IKeyReference(activity)), activity)
            for activity in self.context.getCurrentActivities(self.person)]
        student = self.student
        gradebook = proxy.removeSecurityProxy(self.context)
        for act_hash, activity in activities:
            ev = gradebook.getEvaluation(student, activity)
            value = self.request.get(str(act_hash))
            if ev is not None and ev.value is not UNSCORED:
                yield {'activity': act_hash, 'value': value or ev.value}
            else:
                yield {'activity': act_hash, 'value': value or ''}

    def update(self):
        self.person = IPerson(self.request.principal)
        
        if 'CANCEL' in self.request:
            self.request.response.redirect('index.html')

        elif 'UPDATE_SUBMIT' in self.request:
            student = self.student
            evaluator = zapi.getName(IPerson(self.request.principal))
            gradebook = proxy.removeSecurityProxy(self.context)
            # Iterate through all activities
            for activity in self.context.activities:
                # Create a hash and see whether it is in the request
                act_hash = str(hash(IKeyReference(activity)))
                if act_hash in self.request:

                    # If a value is present, create an evaluation, if the
                    # score is different
                    try:
                        score = activity.scoresystem.fromUnicode(
                            self.request[act_hash])
                    except (zope.schema.ValidationError, ValueError):
                        self.message = _(
                            'The grade $value for activity $name is not valid.',
                            mapping={'value': self.request[act_hash],
                                     'name': activity.title})
                        return
                    ev = gradebook.getEvaluation(student, activity)
                    # Delete the score
                    if ev is not None and score is UNSCORED:
                        self.context.removeEvaluation(student, activity)
                    # Do nothing
                    elif ev is None and score is UNSCORED:
                        continue
                    # Replace the score or add new one/
                    elif ev is None or score != ev.value:
                        self.context.evaluate(
                            student, activity, score, evaluator)

            self.request.response.redirect('index.html')


class GradeActivity(object):
    """Grading a single activity"""

    message = ''

    @property
    def activity(self):
        if hasattr(self, '_activity'):
            return self._activity
        act_hash = int(self.request['activity'])
        for activity in self.context.activities:
            if hash(IKeyReference(activity)) == act_hash:
                self._activity = activity
                return activity

    @property
    def grades(self):
        gradebook = proxy.removeSecurityProxy(self.context)
        for student in self.context.students:
            ev = gradebook.getEvaluation(student, self.activity)
            value = self.request.get(student.username)
            if ev is not None:
                value = value or ev.value
            else:
                value = value or ''

            yield {'student': {'title': student.title, 'id': student.username},
                   'value': value}

    def update(self):
        if 'CANCEL' in self.request:
            self.request.response.redirect('index.html')

        elif 'UPDATE_SUBMIT' in self.request:
            activity = self.activity
            evaluator = zapi.getName(IPerson(self.request.principal))
            gradebook = proxy.removeSecurityProxy(self.context)
            # Iterate through all students
            for student in self.context.students:
                id = student.username
                if id in self.request:

                    # If a value is present, create an evaluation, if the
                    # score is different
                    try:
                        score = activity.scoresystem.fromUnicode(
                            self.request[id])
                    except (zope.schema.ValidationError, ValueError):
                        self.message = _(
                            'The grade $value for $name is not valid.',
                            mapping={'value': self.request[id],
                                     'name': student.title})
                        return
                    ev = gradebook.getEvaluation(student, activity)
                    # Delete the score
                    if ev is not None and score is UNSCORED:
                        self.context.removeEvaluation(student, activity)
                    # Do nothing
                    elif ev is None and score is UNSCORED:
                        continue
                    # Replace the score or add new one/
                    elif ev is None or score != ev.value:
                        self.context.evaluate(
                            student, activity, score, evaluator)

            self.request.response.redirect('index.html')


class Grade(object):
    """Grading a specific activity for a student."""

    @property
    def student(self):
        id = self.request['student']
        school = app.getSchoolToolApplication()
        return school['persons'][id]

    @property
    def activity(self):
        if hasattr(self, '_activity'):
            return self._activity
        act_hash = int(self.request['activity'])
        for activity in self.context.activities:
            if hash(IKeyReference(activity)) == act_hash:
                self._activity = activity
                return activity

    @property
    def activityInfo(self):
        formatter = self.request.locale.dates.getFormatter('date', 'short')
        return {'title': self.activity.title,
                'date': formatter.format(self.activity.date),
                'maxScore': self.activity.scoresystem.getBestScore()}

    @property
    def evaluationInfo(self):
        formatter = self.request.locale.dates.getFormatter('dateTime', 'short')
        gradebook = proxy.removeSecurityProxy(self.context)
        ev = gradebook.getEvaluation(self.student, self.activity)
        if ev is not None:
            return {'value': ev.value,
                    'time': formatter.format(ev.time)}
        else:
            return {'value': '', 'time': ''}

    def update(self):
        if 'CANCEL' in self.request:
            self.request.response.redirect('index.html')

        elif 'DELETE' in self.request:
            self.context.removeEvaluation(self.student, self.activity)

        elif 'UPDATE_SUBMIT' in self.request:
            evaluator = zapi.getName(IPerson(self.request.principal))

            score = self.activity.scoresystem.fromUnicode(self.request['grade'])
            gradebook = proxy.removeSecurityProxy(self.context)
            ev = gradebook.getEvaluation(self.student, self.activity)
            if ev is None or score != ev.value:
                self.context.evaluate(
                    self.student, self.activity, score, evaluator)

            self.request.response.redirect('index.html')


class MyGradesView(SectionFinder):
    """Student view of own grades."""

    def update(self):
        self.person = IPerson(self.request.principal)

        """Handle change of current worksheet."""
        if 'currentWorksheet' in self.request:
            for worksheet in self.context.worksheets:
                if worksheet.title == self.request['currentWorksheet']:
                    self.context.setCurrentWorksheet(self.person, worksheet)
                    break

        self.table = []
        total = 0
        count = 0
        for activity in self.context.getCurrentActivities(self.person):
            activity = proxy.removeSecurityProxy(activity)
            ev = self.context.getEvaluation(self.person, activity)
            if ev:
                ss = ev.requirement.scoresystem
                grade = '%d/%d' % (ev.value, ss.max)
                
                total += ev.value - ss.min
                count += ss.max - ss.min
            else:
                grade = None
            self.table.append({'activity': activity.title, 
                               'possible': activity.scoresystem.max,
                               'grade': grade})
        if count:
            self.average = int((float(100 * total) / float(count)) + 0.5)
        else:
            self.average = None

    def getCurrentWorksheet(self):
        return self.context.getCurrentWorksheet(self.person)

