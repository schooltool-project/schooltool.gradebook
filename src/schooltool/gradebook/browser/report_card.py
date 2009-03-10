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
Report Card Views
"""

from zope.app.container.interfaces import INameChooser
from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile
from zope.component import adapts
from zope.interface import Interface, implements
from zope.schema import Choice
from zope.security.checker import canWrite
from zope.security.interfaces import Unauthorized
from zope.traversing.api import getName
from zope.traversing.browser.absoluteurl import absoluteURL

from z3c.form import form, field, button

from schooltool.app.interfaces import ISchoolToolApplication
from schooltool.common import SchoolToolMessage as _
from schooltool.course.interfaces import ISectionContainer
from schooltool.person.interfaces import IPerson

from schooltool.gradebook.interfaces import IGradebookRoot
from schooltool.gradebook.interfaces import IActivities, IReportActivity
from schooltool.gradebook.activity import Worksheet, Activity, ReportActivity


class TemplatesView(object):
    """A view for managing report sheet templates"""

    @property
    def worksheets(self):
        """Get  a list of all worksheets."""
        pos = 0
        for worksheet in self.context.values():
            pos += 1
            yield {'name': getName(worksheet),
                   'title': worksheet.title,
                   'url': absoluteURL(worksheet, self.request),
                   'pos': pos}

    def positions(self):
        return range(1, len(self.context.values())+1)

    def canModify(self):
        return canWrite(self.context, 'title')

    def update(self):
        self.person = IPerson(self.request.principal, None)
        if self.person is None:
            # XXX ignas: i had to do this to make the tests pass,
            # someone who knows what this code should do if the user
            # is unauthenticated should add the relevant code
            raise Unauthorized("You don't have the permission to do this.")

        if 'DELETE' in self.request:
            for name in self.request.get('delete', []):
                del self.context[name]

        elif 'form-submitted' in self.request:
            old_pos = 0
            for worksheet in self.context.values():
                old_pos += 1
                name = getName(worksheet)
                if 'pos.'+name not in self.request:
                    continue
                new_pos = int(self.request['pos.'+name])
                if new_pos != old_pos:
                    self.context.changePosition(name, new_pos-1)


class IExistingScoreSystem(Interface):
    """A schema used to choose an existing score system."""

    scoresystem = Choice(
        title=_('Exisiting Score System'),
        vocabulary='schooltool.requirement.scoresystems',
        required=True)


class ExistingScoresSystem(object):
    implements(IExistingScoreSystem)
    adapts(IReportActivity)

    def __init__(self, context):
        self.__dict__['context'] = context

    def __setattr__(self, name, value):
        if name == 'scoresystem':
            self.context.scoresystem = value
        else:
            setattr(self.context, name, value)

    def __getattr__(self, name):
        return getattr(self.context, name)


class ReportActivityAddView(form.AddForm):
    """A view for adding an activity."""
    label = _("Add new activity")
    template = ViewPageTemplateFile('add_edit_report_activity.pt')

    fields = field.Fields(IReportActivity).select('title', 'description',
                                                  'category')
    fields += field.Fields(IExistingScoreSystem)

    def updateActions(self):
        super(ReportActivityAddView, self).updateActions()
        self.actions['add'].addClass('button-ok')
        self.actions['cancel'].addClass('button-cancel')

    @button.buttonAndHandler(_('Add'), name='add')
    def handleAdd(self, action):
        data, errors = self.extractData()
        if errors:
            self.status = self.formErrorsMessage
            return
        obj = self.createAndAdd(data)
        if obj is not None:
            # mark only as finished if we get the new object
            self._finishedAdd = True

    @button.buttonAndHandler(_("Cancel"))
    def handle_cancel_action(self, action):
        url = absoluteURL(self.context, self.request)
        self.request.response.redirect(url)

    def create(self, data):
        activity = ReportActivity(data['title'], data['category'], 
                                  data['scoresystem'], data['description'])
        return activity

    def add(self, activity):
        """Add activity to the worksheet."""
        chooser = INameChooser(self.context)
        name = chooser.chooseName('', activity)
        self.context[name] = activity
        return activity

    def nextURL(self):
        return absoluteURL(self.context, self.request)


class ReportActivityEditView(form.EditForm):
    """Edit form for basic person."""
    form.extends(form.EditForm)
    template = ViewPageTemplateFile('add_edit_report_activity.pt')

    fields = field.Fields(IReportActivity).select('title', 'description',
                                                  'category')
    fields += field.Fields(IExistingScoreSystem)

    @button.buttonAndHandler(_("Cancel"))
    def handle_cancel_action(self, action):
        self.request.response.redirect(self.nextURL())

    def updateActions(self):
        super(ReportActivityEditView, self).updateActions()
        self.actions['apply'].addClass('button-ok')
        self.actions['cancel'].addClass('button-cancel')

    def applyChanges(self, data):
        super(ReportActivityEditView, self).applyChanges(data)
        self.request.response.redirect(self.nextURL())

    @property
    def label(self):
        return _(u'Change information for ${fullname}',
                 mapping={'fullname': self.context.title})

    def nextURL(self):
        return absoluteURL(self.context.__parent__, self.request)


class DeployReportWorksheetView(object):
    """A view for deploying a report sheet template to a term"""

    @property
    def worksheets(self):
        """Get  a list of all report worksheets."""
        root = IGradebookRoot(ISchoolToolApplication(None))
        for worksheet in root.templates.values():
            yield {'name': getName(worksheet),
                   'title': worksheet.title}

    def update(self):
        if 'form-submitted' in self.request:
            if 'DEPLOY' in self.request:
                self.deploy()
            self.request.response.redirect(self.nextURL())

    def deploy(self):
        root = IGradebookRoot(ISchoolToolApplication(None))
        worksheet = root.templates[self.request['reportWorksheet']]

        # copy worksheet template to deployed container
        term = self.context
        schoolyear = term.__parent__
        deployedKey = '%s_%s' % (schoolyear.__name__, term.__name__)
        deployedWorksheet = Worksheet(worksheet.title)
        chooser = INameChooser(root.deployed)
        name = chooser.chooseName(deployedKey, deployedWorksheet)
        root.deployed[name] = deployedWorksheet
        self.copyActivities(worksheet, deployedWorksheet)

        # now copy the template to all sections in the term
        sections = ISectionContainer(term)
        for section in sections.values():
            activities = IActivities(section)
            worksheetCopy = Worksheet(deployedWorksheet.title)
            worksheetCopy.deployed = True
            chooser = INameChooser(activities)
            name = chooser.chooseName('', worksheetCopy)
            activities[name] = worksheetCopy
            self.copyActivities(deployedWorksheet, worksheetCopy)

    def copyActivities(self, sourceWorksheet, destWorksheet):
        for activity in sourceWorksheet.values():
            activityCopy = Activity(activity.title, activity.category,
                                    activity.scoresystem, activity.description)
            chooser = INameChooser(destWorksheet)
            name = chooser.chooseName('', activityCopy)
            destWorksheet[name] = activityCopy

    def nextURL(self):
        return absoluteURL(self.context, self.request)

