#
# SchoolTool - common information systems platform for school administration
# Copyright (c) 2003 Shuttleworth Foundation
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
SchoolTool groups and members

$Id: model.py 153 2003-10-16 12:33:50Z mg $
"""

from sets import Set
from zope.interface import implements, moduleProvides
from persistence import Persistent
from zodb.btrees.IOBTree import IOBTree
from schooltool.interfaces import IQueryLinks, IGroupMember, IGroup
from schooltool.interfaces import ISpecificURI, IRemovableLink
from schooltool.interfaces import URIMembership, URIGroup, URIMember
from schooltool.interfaces import IMembershipEvent
from schooltool.interfaces import IMemberAddedEvent
from schooltool.interfaces import IMemberRemovedEvent
from schooltool.interfaces import IModuleSetup
from schooltool.db import PersistentKeysDict
from schooltool.relationships import RelationshipSchema, RelationshipEvent
from schooltool.component import registerRelationship

moduleProvides(IModuleSetup)

__metaclass__ = type


class GroupLink:
    """An object that represents membership in a group as a link.

    IOW, this is a link from a member to a group.
    """

    implements(IRemovableLink)
    __slots__ = '_group', 'name', '__parent__'
    role = URIGroup
    title = "Membership"
    reltype = URIMembership

    def __init__(self, parent, group, name):
        """The arguments are the following:
             parent is the owner of this link (a group member)
             group is the group at the opposite end of the relationship
             name is the key of parent in the group
        """
        self._group = group
        self.name = name
        self.__parent__ = parent

    def traverse(self):
        """See ILink"""
        return self._group

    def unlink(self):
        """See IRemovableLink"""
        del self._group[self.name]
        otherlink = MemberLink(self._group, self.__parent__, self.name)
        event = MemberRemovedEvent((self, otherlink))
        event.dispatch(self.traverse())
        event.dispatch(otherlink.traverse())


class MemberLink:
    """An object that represents containment of a group member as a link."""

    implements(IRemovableLink)
    __slots__ = '_member', 'name', '__parent__'
    role = URIMember
    title = "Membership"
    reltype = URIMembership

    def __init__(self, parent, member, name):
        """The arguments are the following:
             parent is the owner of this link (a group)
             member is the object at the opposite end of the relationship
             name is the key of member in parent
        """
        self._member = member
        self.name = name
        self.__parent__ = parent

    def traverse(self):
        """See ILink"""
        return self._member

    def unlink(self):
        """See IRemovableLink"""
        del self.__parent__[self.name]
        otherlink = GroupLink(self._member, self.__parent__, self.name)
        event = MemberRemovedEvent((self, otherlink))
        event.dispatch(self.traverse())
        event.dispatch(otherlink.traverse())


class MemberMixin(Persistent):
    """A mixin providing the IGroupMember interface.

    Also, it implements ILocation by setting the first group the
    member is added to as a parent, and clearing it if the member is
    removed from it.
    """

    implements(IGroupMember, IQueryLinks)

    def __init__(self):
        self._groups = PersistentKeysDict()
        self.__name__ = None
        self.__parent__ = None

    def groups(self):
        """See IGroupMember"""
        return self._groups.keys()

    def notifyAdd(self, group, name):
        """See IGroupMember"""
        self._groups[group] = name
        if self.__parent__ is None:
            self.__parent__ = group
            self.__name__ = str(name)

    def notifyRemove(self, group):
        """See IGroupMember"""
        del self._groups[group]
        if group == self.__parent__:
            self.__parent__ = None
            self.__name__ = None

    def listLinks(self, role=ISpecificURI):
        if URIGroup.extends(role, False):
            return [GroupLink(self, group, name)
                    for group, name in self._groups.iteritems()]
        else:
            return []


class GroupMixin(Persistent):
    """This class is a mixin which makes things a group"""

    implements(IQueryLinks)

    def __init__(self):
        self._next_key = 0
        self._members = IOBTree()

    def keys(self):
        """See IGroup"""
        return self._members.keys()

    def values(self):
        """See IGroup"""
        return self._members.values()

    def items(self):
        """See IGroup"""
        return self._members.items()

    def __getitem__(self, key):
        """See IGroup"""
        return self._members[key]

    def add(self, member):
        """See IGroup"""
        if not IGroupMember.isImplementedBy(member):
            raise TypeError("Members must implement IGroupMember")
        ## XXX can we remove this?
        ##if self._p_jar is not None:
        ##    self._p_jar.add(member)
        key = self._next_key
        self._next_key += 1
        self._members[key] = member
        self._addhook(member)
        member.notifyAdd(self, key)
        return key

    def __delitem__(self, key):
        """See IGroup"""
        member = self._members[key]
        member.notifyRemove(self)
        self._deletehook(member)
        del self._members[key]

    def listLinks(self, role=ISpecificURI):
        """See IQueryLinks"""
        if URIMember.extends(role, False):
            return [MemberLink(self, member, name)
                    for name, member in self.items()]
        else:
            return []

    # Hooks for use by mixers-in

    def _addhook(self, member):
        pass

    def _deletehook(self, member):
        pass


Membership = RelationshipSchema(URIMembership,
                                group=URIGroup, member=URIMember)


class MembershipEvent(RelationshipEvent):

    implements(IMembershipEvent, URIMembership)

    def __init__(self, links):
        RelationshipEvent.__init__(self, links)
        self.member = None
        self.group = None
        for link in links:
            if link.role.extends(URIMember, False):
                if self.member is not None:
                    raise TypeError("only one URIMember must be present"
                                    " among links", links)
                self.member = link.traverse()
            if link.role.extends(URIGroup, False):
                if self.group is not None:
                    raise TypeError("only one URIGroup must be present"
                                    " among links", links)
                self.group = link.traverse()
        if self.member is None or self.group is None:
            raise TypeError("both URIGroup and URIMember must be present"
                            " among links", links)


class MemberAddedEvent(MembershipEvent):
    implements(IMemberAddedEvent)


class MemberRemovedEvent(MembershipEvent):
    implements(IMemberRemovedEvent)


def membershipRelate(relationship_type, (a, role_a), (b, role_b), title=None):
    """See IRelationshipFactory"""

    if relationship_type is not URIMembership:
        raise TypeError("Membership relationship must be of type"
                        " URIMembership.", relationship_type)
    if title is not None and title != "Membership":
        raise TypeError(
            "A relationship of type URIMembership must have roles"
            " URIMember and URIGroup, and the title (if any) must be"
            " 'Membership'.")

    r = Set((role_a, role_b))
    try:
        r.remove(URIMember)
        r.remove(URIGroup)
    except KeyError:
        raise TypeError(
            "A relationship of type URIMembership must have roles"
            " URIMember and URIGroup, and the title (if any) must be"
            " 'Membership'.")

    if r:
        raise TypeError(
            "A relationship of type URIMembership must have roles"
            " URIMember and URIGroup, and the title (if any) must be"
            " 'Membership'.")

    if role_a is URIGroup:
        group, member = a, b
        name = group.add(member)
        links = (MemberLink(group, member, name),
                 GroupLink(member, group, name))
    else:
        group, member = b, a
        name = group.add(member)
        links = (GroupLink(member, group, name),
                 MemberLink(group, member, name))
    event = MemberAddedEvent(links)
    event.dispatch(a)
    event.dispatch(b)
    return links


def setUp():
    """Register the URIMembership relationship handler."""
    registerRelationship(URIMembership, membershipRelate)

