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
"""Requirement Interfaces

$Id$
"""

__docformat__ = 'restructuredtext'

import zope.schema
from zope.container.interfaces import IOrderedContainer, IContainer
from zope.container.constraints import contains, containers
from zope.location.interfaces import IContained
from zope.location.interfaces import ILocation

from schooltool.gradebook import GradebookMessage as _


class IRequirement(IOrderedContainer, IContained):
    """Something a student can do.

    A requirement can contain further requirements that are needed to fulfill
    this requirement. You can think of those requirements as dependencies of
    this requirement. We will refer to those requirements from now on as
    dependencies or depoendency requirements.
    """

    contains('.IRequirement')
    containers('.IRequirement')

    title = zope.schema.TextLine(
        title=_(u"Title"),
        description=u'',
        required=True)

    def changePosition(name, pos):
        """Changes the requirement's position to the specified position."""


class IHaveRequirement(zope.interface.Interface):
    """Marker interface for objects having requirements"""


class IScoreSystemContainer(IContainer):
    """A Container for Score Systems"""

    contains('.ICustomScoreSystem')


class IScoreSystem(zope.interface.Interface):
    """A Score System"""

    title = zope.schema.TextLine(
        title=_(u"Title"),
        description=u'A brief title of the score system.',
        required=False)

    description = zope.schema.TextLine(
        title=_(u"Description"),
        description=u'A brief description of the score system.',
        required=False)

    def isValidScore(score):
        """Return whether score is a valid score.

        The return value is a boolean.  The ``UNSCORED`` value is a valid
        score.
        """

    def fromUnicode(rawScore):
        """Convert a unicode representation of the score to a true value.

        User input always comes as a (unicode) string. Only the scoresystem
        contains the necessary information to convert those strings into real
        values.
        """


class ICommentScoreSystem(IScoreSystem):
    """A Score System for free-form comments."""


class IValuesScoreSystem(IScoreSystem):
    """A Score System that deal with specific score values."""

    def isPassingScore(score):
        """Return whether score meets a passing threshold.

        The return value is a boolean. When it cannot be determined whether
        the score is a passing score, then ``None`` is returned.
        """

    def getBestScore():
        """Return the best score of the grading system.

        The best score is required to compute statistics. It is also a helpful
        piece of information for the grader.
        """

    def getNumericalValue(score):
        """Return a numerical value for the score.

        In order to compute grades and statistics, we need to be able to
        assign a numerical value to a score.
        """

    def getFractionalValue(score):
        """Return a decimal fraction between 0..1 for the score.
        """


class IDiscreteValuesScoreSystem(IValuesScoreSystem):
    """A score system that consists of discrete values."""

    hidden = zope.schema.Bool(
        title=u"Hidden Score System",
        required=False
        )

    scores = zope.schema.List(
        title=u'Scores',
        description=u'A list of tuples of the form (score, abbr, value, percent).',
        value_type=zope.schema.Tuple(),
        required=True)


class ICustomScoreSystem(IDiscreteValuesScoreSystem):
    """A user-created score system that consists of discrete values."""


class IRangedValuesScoreSystem(IValuesScoreSystem):
    """A score system that allows for a randge of values."""

    min = zope.schema.Int(
        title=_(u'Minimum'),
        description=u'Minimum value in the score system',
        required=True,
        default=0)

    max = zope.schema.Int(
        title=_(u'Maximum'),
        description=u'Maximum value in the score system',
        required=True,
        default=100)


class IHaveEvaluations(zope.interface.Interface):
    """A marker interface for objects that can have evaluations"""


class IScore(zope.interface.Interface):
    """A score valid in a score system."""

    scoreSystem = zope.schema.Object(
        title=_(u'Score System'),
        description=u'The score system used for grading.',
        schema=IScoreSystem)

    value = zope.schema.Object(
        title=u'Value',
        description=u'A scoresystem-valid score that represents the grade.',
        schema=zope.interface.Interface,
        required=True)


class IEvaluation(IScore, IContained):
    """An Evaluation"""

    containers(".IEvaluations")

    requirement = zope.schema.Object(
        title=u'Requirement',
        description=u'The requirement being evaluated.',
        schema=IRequirement)

    time = zope.schema.Datetime(
        title=u'Time',
        description=u'The time the evaluation was made')

    evaluatee = zope.schema.Object(
        title=u'Evaluatee',
        description=u'The entity receiving the evaluation',
        schema=zope.interface.Interface,
        readonly=True,
        required=True)

    evaluator = zope.schema.Object(
        title=u'Evaluator',
        description=u'The entity doing the evaluation',
        schema=zope.interface.Interface,
        required=True)


class IEvaluations(zope.interface.common.mapping.IMapping):
    """Evaluation storage

    This object stores all evaluations of an entity. It is naturally a mapping
    from requirement to the evaluation. Note that this object is not a classical
    Zope container, because the key will **not** be a name, but some sort of
    key reference to the requirement.
    """
    contains(IEvaluation)

    def __init__(self, items=None):
        """Initialize object.

        The items should be a list of tuples or dictionary of evaluation names
        and objects.
        """

    def addEvaluation(evaluation):
        """Add an evaluation."""

    def getEvaluationsForRequirement(requirement, recursive=True):
        """Match all evaluations that satisfy the requirement.

        The return value is another ``IEvaluations`` object.  This allows for
        chained queries.  For recursive queries, evaluations for all dependency
        requirements will be returned as well.
        """

    def getEvaluationsOfEvaluator(evaluator):
        """Match all evaluations done by the specified evaluator.

        The return value is another ``IEvaluations`` object.  This allows for
        chained queries.  For recursive queries, evaluations for all dependency
        requirements will be returned as well.
        """


class IEvaluationsQuery(zope.interface.Interface):
    """Evaluation Query

    These objects query evaluations and return another evaluations object.
    """

    def __call__(self, *args, **kwargs):
        """Execute the query and return an ``IEvaluations`` object.

        The returned ``IEvaluations`` object *must* have the same parent and
        name that the original ``IEvaluations`` object had.
        """


class IScoreSystemsProxy(ILocation):
    """The Proxy class for adding/editing score systems"""

    def getScoreSystems():
        """Return list of tuples (name, scoresystem)"""

    def addScoreSystem(scoresystem):
        """Add scoresystem to app utilitiles"""

    def getScoreSystem(name):
        """Get scoresystem from app utilitiles by the given name"""

