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

from persistent import Persistent
from zope.app.container.contained import Contained
from zope.app.intid.interfaces import IIntIds
from zope.app.intid import IntIds
from zope.app.catalog.interfaces import ICatalog
from zope.app.catalog.catalog import Catalog
from zope.app.catalog.text import TextIndex
from zope.app.catalog.field import FieldIndex
from zope.interface import implements
from zope.component import adapts
from zope.interface import directlyProvides

from zc.table.interfaces import ISortableColumn

from schooltool.utility import UtilitySpecification, MultiUtilitySetUp

from schooltool.demographics.interfaces import ISearch
from schooltool.demographics.person import Person
from schooltool.person.interfaces import IPerson
from schooltool.person.interfaces import IPersonFactory
from schooltool.skin.table import LocaleAwareGetterColumn

class Search(object):
    implements(ISearch)
    adapts(IPerson)

    def __init__(self, context):
        self.context = context

    @property
    def fulltext(self):
        return [self.context.title]

    @property
    def parentName(self):
        result = []
        if self.context.parent1.name:
            result.append(self.context.parent1.name)
        if self.context.parent2.name:
            result.append(self.context.parent2.name)
        return result

    @property
    def studentId(self):
        if not self.context.schooldata.id:
            return ''
        return self.context.schooldata.id

def catalogSetUp(catalog):
    catalog['fulltext'] = TextIndex('fulltext', ISearch)
    catalog['parentName'] = TextIndex('parentName', ISearch)
    catalog['studentId'] = FieldIndex('studentId', ISearch)

catalogSetUpSubscriber = MultiUtilitySetUp(
    UtilitySpecification(IntIds, IIntIds),
    UtilitySpecification(Catalog, ICatalog, 'demographics_catalog',
                         setUp=catalogSetUp),
    )

class PersonFactory(Persistent, Contained):
    """BBB: as old utilities are persistent, we need this here."""


class PersonFactoryUtility(object):

    implements(IPersonFactory)

    def columns(self):
        first_name = LocaleAwareGetterColumn(
            name='first_name',
            title=u'Name',
            getter=lambda i, f: i.nameinfo.first_name,
            subsort=True)
        directlyProvides(first_name, ISortableColumn)

        last_name = LocaleAwareGetterColumn(
            name='last_name',
            title=u'Surname',
            getter=lambda i, f: i.nameinfo.last_name,
            subsort=True)
        directlyProvides(last_name, ISortableColumn)

        return [first_name, last_name]

    def sortOn(self):
        return (("last_name", False),)

    def __call__(self, *args, **kw):
        result = Person(*args, **kw)
        result.nameinfo.first_name = result.title
        result.nameinfo.last_name = u'Unknown last name'
        return result
