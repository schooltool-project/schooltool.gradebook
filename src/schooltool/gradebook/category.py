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
"""Activity Category

$Id$
"""
__docformat__ = 'reStructuredText'

import z3c.optionstorage.vocabulary
from zope.interface import implements, implementer
from zope.component import adapter
from zope.schema.interfaces import IIterableVocabulary
from zope.container.btree import BTreeContainer

from schooltool.app.interfaces import ISchoolToolApplication
from schooltool.app.utils import TitledContainerItemVocabulary
from schooltool.gradebook.interfaces import ICategoryContainer


CATEGORIES_KEY = 'schooltool.gradebook.category'


# BBB: for old data.fs'es
class CategoryVocabulary(z3c.optionstorage.vocabulary.OptionStorageVocabulary):
    pass


class CategoryContainer(BTreeContainer):
    implements(ICategoryContainer)

    default_key = None

    @property
    def default(self):
        return self.get(self.default_key)


class CategoriesVocabulary(TitledContainerItemVocabulary):
    """Vocabulary of categorys."""
    implements(IIterableVocabulary)

    def getTitle(self, item):
        return item

    def __iter__(self):
        for key in sorted(self.container):
            yield self.getTerm(self.container[key])

    @property
    def container(self):
        app = ISchoolToolApplication(None)
        return ICategoryContainer(app)


def categoryVocabularyFactory():
    return CategoriesVocabulary


@adapter(ISchoolToolApplication)
@implementer(ICategoryContainer)
def getCategories(app):
    return app.get(CATEGORIES_KEY)
