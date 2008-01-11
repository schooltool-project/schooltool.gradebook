=============
The Gradebook
=============

Traditionally, the gradebook is a simple spreadsheet where the columns are the
activities to be graded and each row is a student. Since SchoolTool is an
object-oriented application, we have the unique oppurtunity to implement it a
little bit different and to provide some unique features.

Categories
----------

When the SchoolTool instance is initially setup, it is part of the
administations job to setup activity categories. Activity categories can be
"homework", "paper", "test", "final exam", etc.

    >>> from schooltool.testing import setup
    >>> school = setup.setUpSchoolToolSite()

By default, some categories should be available in the vocabulary. Since this
is a test, we have to set them up manually:

    >>> from schooltool.testing import registry
    >>> from schooltool.gradebook.gradebook import GradebookInit
    >>> plugin = GradebookInit(school)
    >>> plugin()

The categories are managed by a special option storage vocabulary. As soon as
the SchoolTool application is registered as a site, the vocabulary can be
easily initiated.

    >>> from schooltool.gradebook import category
    >>> categories = category.CategoryVocabulary()

We can now see the default categories:

    >>> sorted([term.title for term in categories])
    [u'Assignment', u'Essay', u'Exam', u'Homework', u'Journal', u'Lab',
     u'Presentation', u'Project']

The actual categories, however, are not managed by the vocabulary directly,
but by an option storage dictionary. The category module provides a high-level
function to get the dictionary:

    >>> dict = category.getCategories(school)

Now we can add,

    >>> dict.addValue('quiz', 'en', u'Quiz')
    >>> sorted([term.title for term in categories])
    [u'Assignment', u'Essay', u'Exam', u'Homework', u'Journal', u'Lab',
     u'Presentation', u'Project', u'Quiz']

delete,

    >>> dict.delValue('quiz', 'en')
    >>> sorted([term.title for term in categories])
    [u'Assignment', u'Essay', u'Exam', u'Homework', u'Journal', u'Lab',
     u'Presentation', u'Project']

and query values:

    >>> dict.getValue('assignment','en')
    u'Assignment'

    >>> dict.getValue('faux','en')
    Traceback (most recent call last):
    ...
    KeyError: 'Invalid row/column pair'

    >>> dict.queryValue('faux','en', default=u'default')
    u'default'

    >>> sorted(dict.getKeys())
    ['assignment', 'essay', 'exam', 'homework', 'journal', 'lab',
     'presentation', 'project']

As you can see, the option storage also supports multiple languages, though
only English is currently supported. (Of course, administrators can delete all
default categories and register new ones in their favorite language.)


Activities
----------

Activities are items that can be graded.  In other software they are also
referred to as assignments or grading items.  Activities can be defined for
courses and sections.  They are organized into worksheets to allow teachers
to keep activities separate from quarter to quarter.  Worksheets could be used
to keep assignments organized by type.  It's up to the teacher.

Let's create some people, a course and a section:

    >>> from schooltool.person import person
    >>> from schooltool.course import course, section
    >>> tom = person.Person('tom', 'Tom Hoffman')
    >>> paul = person.Person('paul', 'Paul Cardune')
    >>> claudia = person.Person('claudia', 'Claudia Richter')
    >>> stephan = person.Person('stephan', 'Stephan Richter')
    >>> alg1 = course.Course('Alg1', 'Algebra 1')
    >>> sectionA = section.Section('Alg1-A')
    >>> alg1.sections.add(sectionA)

We add some students and a teacher to the class,

    >>> sectionA.members.add(tom)
    >>> sectionA.members.add(paul)
    >>> sectionA.members.add(claudia)
    >>> sectionA.instructors.add(stephan)

We will deal with the most common case first.  Here, Stephan teaches a
two week course in algebra, and he would like to have two worksheets,
one for each week.  At first there will be no worksheets in the section.

    >>> from schooltool.gradebook import interfaces
    >>> sectionA_act = interfaces.IActivities(sectionA)
    >>> sectionA_act
    Activities(u'Activities')
    >>> list(sectionA_act.items())
    []

We'll create two worksheets, while adding them to the section activities.

    >>> from schooltool.gradebook import activity
    >>> sectionA_act['week1'] = activity.Worksheet(u'Week 1')
    >>> week1 = sectionA_act['week1']
    >>> sectionA_act['week2'] = activity.Worksheet(u'Week 2')
    >>> week2 = sectionA_act['week2']
    >>> list(sectionA_act.items())
    [('week1', Worksheet(u'Week 1')), ('week2', Worksheet(u'Week 2'))]
    
Both worksheets start out empty.

    >>> list(week1.items())
    []
    >>> list(week2.items())
    []
    
We will add two activities to each worksheet, a homework assignment and
a test.

    >>> from schooltool.requirement import scoresystem
    >>> week1['homework'] = activity.Activity(
    ...     title=u'HW 1',
    ...     description=u'Week 1 Homework',
    ...     category=u'Assginment',
    ...     scoresystem=scoresystem.RangedValuesScoreSystem(max=10))
    >>> hw1 = week1['homework']
    >>> week1['quiz'] = activity.Activity(
    ...     title=u'Quiz',
    ...     description=u'End of Week Quiz',
    ...     category=u'Exam',
    ...     scoresystem=scoresystem.PercentScoreSystem)
    >>> quiz = week1['quiz']
    >>> week2['homework'] = activity.Activity(
    ...     title=u'HW 2',
    ...     description=u'Week 2 Homework',
    ...     category=u'Assginment',
    ...     scoresystem=scoresystem.RangedValuesScoreSystem(max=15))
    >>> hw2 = week2['homework']
    >>> week2['final'] = activity.Activity(
    ...     title=u'Final',
    ...     description=u'Final Exam',
    ...     category=u'Exam',
    ...     scoresystem=scoresystem.PercentScoreSystem)
    >>> final = week2['final']

Besides the title and description, one must also specify the category and the
score system. The category is used to group similar activities together and
later facilitate in computing the final grade. The score system is an object
describing the type of score that can be associated with the activity.
    
Now we note that both worksheets have the activities in them.

    >>> list(week1.items())
    [('homework', <Activity u'HW 1'>), ('quiz', <Activity u'Quiz'>)]
    >>> list(week2.items())
    [('homework', <Activity u'HW 2'>), ('final', <Activity u'Final'>)]


Evaluations
-----------

Now that all of our activities have been defined, we can finally enter some
grades using the gradebook.

    >>> from schooltool.gradebook import interfaces
    >>> gradebook = interfaces.IGradebook(sectionA)
    
Already the gradebook has worksheets which it got from the section.

    >>> gradebook.worksheets
    [Worksheet(u'Week 1'), Worksheet(u'Week 2')]

Those worksheets have, int turn, the activities we added to them.

    >>> gradebook.getWorksheetActivities(week1)
    [<Activity u'HW 1'>, <Activity u'Quiz'>]
    >>> gradebook.getWorksheetActivities(week2)
    [<Activity u'HW 2'>, <Activity u'Final'>]

The current worksheet for the teacher will automatically be set to the first
one.

    >>> gradebook.getCurrentWorksheet(stephan)
    Worksheet(u'Week 1')
    >>> gradebook.getCurrentActivities(stephan)
    [<Activity u'HW 1'>, <Activity u'Quiz'>]
    
We can change it to be the second worksheet.

    >>> gradebook.setCurrentWorksheet(stephan, week2)
    >>> gradebook.getCurrentWorksheet(stephan)
    Worksheet(u'Week 2')
    >>> gradebook.getCurrentActivities(stephan)
    [<Activity u'HW 2'>, <Activity u'Final'>]

Let's enter some grades:

    >>> gradebook.evaluate(student=tom, activity=hw1, score=8)
    >>> gradebook.evaluate(student=paul, activity=hw1, score=10)
    >>> gradebook.evaluate(student=claudia, activity=hw1, score=7)

    >>> gradebook.evaluate(student=tom, activity=quiz, score=90)
    >>> gradebook.evaluate(student=paul, activity=quiz, score=80)
    >>> gradebook.evaluate(student=claudia, activity=quiz, score=99)

    >>> gradebook.evaluate(student=tom, activity=hw2, score=10)
    >>> gradebook.evaluate(student=paul, activity=hw2, score=12)
    >>> gradebook.evaluate(student=claudia, activity=hw2, score=14)

    >>> gradebook.evaluate(student=tom, activity=final, score=85)
    >>> gradebook.evaluate(student=paul, activity=final, score=99)
    >>> gradebook.evaluate(student=claudia, activity=final, score=90)

Of course there are some safety precautions:

1. You cannot add a grade for someone who is not in the section:

    >>> marius = person.Person('marius', 'Marius Gedminas')
    >>> gradebook.evaluate(student=marius, activity=final, score=99)
    Traceback (most recent call last):
    ...
    ValueError: Student 'marius' is not in this section.

2. You cannot add a grade for an activity that does not belong to the section:

    >>> hw3 = activity.Activity(
    ...     title=u'HW 3',
    ...     category=u'Assginment',
    ...     scoresystem=scoresystem.RangedValuesScoreSystem(max=10))

    >>> gradebook.evaluate(student=claudia, activity=hw3, score=8)
    Traceback (most recent call last):
    ...
    ValueError: u'HW 3' is not part of this section.

3. You cannot add a grade that is not a valid value of the score system:

    >>> gradebook.evaluate(student=claudia, activity=hw2, score=-8)
    Traceback (most recent call last):
    ...
    ValueError: -8 is not a valid score.

4. In the case of score systems providing IRangedValuesScoreSystem, a score
   greater than the max is allowed in order to give the teacher the chance
   to award extra credit.
   
    >>> gradebook.evaluate(student=claudia, activity=hw2, score=16)
    >>> gradebook.evaluate(student=claudia, activity=hw2, score=14)

There are a couple more management functions that can be used to maintain the
evaluations. For example, you can ask whether an evaluation for a particular
student and activity has been made:

    >>> gradebook.hasEvaluation(student=tom, activity=hw1)
    True

You can then also delete evaluations:

    >>> gradebook.removeEvaluation(student=tom, activity=hw1)
    >>> gradebook.hasEvaluation(student=tom, activity=hw1)
    False


Working with Worksheets
-----------------------

Now that we have created worksheets for our gradebook, added activities to
them, and evaulated the activities, it's time to look at the methods that
will facilitate the gradebook view in getting the info it needs.  We will
assume the currently viewed worksheet is the one for week 1 and get the
activities and evaluations for it.

    >>> gradebook.setCurrentWorksheet(stephan, week1)
    >>> sorted(gradebook.getCurrentActivities(stephan),
    ...        key=lambda x: x.title)
    [<Activity u'HW 1'>, <Activity u'Quiz'>]

    >>> sorted(gradebook.getCurrentEvaluationsForStudent(stephan, paul),
    ...        key=lambda x: x[0].title)
    [(<Activity u'HW 1'>, <Evaluation for <Activity u'HW 1'>, value=10>),
     (<Activity u'Quiz'>, <Evaluation for <Activity u'Quiz'>, value=80>)]

For a given activity, we can query the grades for all students for that
activity.  This represents a column of the worksheet

    >>> sorted(gradebook.getEvaluationsForActivity(hw1),
    ...        key=lambda x: x[0].username)
    [(<...Person ...>, <Evaluation for <Activity u'HW 1'>, value=7>),
     (<...Person ...>, <Evaluation for <Activity u'HW 1'>, value=10>)]

We can get an evaluation for a student, activity pair, which represents 
a cell in the worksheet.

    >>> gradebook.getEvaluation(paul, hw1)
    <Evaluation for <Activity u'HW 1'>, value=10>

We can get a student average for the worksheet, an integer percentage that
can later be used to formulate a letter grade.

    >>> gradebook.getWorksheetAverage(week1, paul)
    82


Sorting by Column
~~~~~~~~~~~~~~~~~

Another important feature of the gradebook is to be able to tell the sorting
rules for the grades table for a particular person. The method to get the
sorting key is ``getSortKey(person)``. By default the gradebook is sorted by
the student's title in A-Z:

    >>> gradebook.getSortKey(stephan)
    ('student', False)

The first element of the returned tuple is the field to sort by. "student" is
a special field. All other fields are the hash of the activity to be sorted
by. The second element specifies whether the sorting should be reversed. You
can set the key using the ``setSortKey(person, (key, reverse))`` method:

    >>> gradebook.setSortKey(stephan, ('student', True))
    >>> gradebook.getSortKey(stephan)
    ('student', True)

    >>> gradebook.setSortKey(stephan, ('-234', False))
    >>> gradebook.getSortKey(stephan)
    ('-234', False)

And that's it. The gradebook itself will not interpret the sorting key any
further. It is up to the view code to implement the rest of the sorting
feature. This is because the view code can often be much more efficient in
implement ordering.


Final Grade Calulation
----------------------

It is important for the teacher to be able to present the student with a final
grade at the end of a section.  We will calulate this for the teacher using
the following formula:

final grade = (4 * num(A) + 3 * num(B) + 2*num(C) + num(D)) / num(worksheets)

This will be rounded to the nearest integer and mapped to a letter grade.
We will hard-code this as 4 -> A, 3 -> B, ... 0 -> E until we have a customer 
that needs it done differently.  

The teacher will have the ability to override this value at his/her discretion 
with a different letter grade, supplying a reason if they wish.

First let's see what Paul's grades are for the two worksheets:

    >>> gradebook.getWorksheetAverage(week1, paul)
    82
    >>> gradebook.getWorksheetAverage(week2, paul)
    97
    
Paul got a B in the first week and an A in the second week.  Averaging them
together and rounding should yield an A.
    
    >>> gradebook.getFinalGrade(paul)
    'A'

Now let's say that Stephan felt that Paul's B in week 1 weighs more heavily
than his A in the second week.  He could indicate this by setting an override
value for Paul of 'B', stating the reason for the adjustment.

    >>> adjustment = gradebook.getFinalGradeAdjustment(stephan, paul)
    >>> sorted(adjustment.items())
    [('adjustment', ''), ('reason', '')]
    >>> gradebook.setFinalGradeAdjustment(stephan, paul, 'B',
    ...     'week 1 more important than week 2')
    >>> adjustment = gradebook.getFinalGradeAdjustment(stephan, paul)
    >>> sorted(adjustment.items())
    [('adjustment', 'B'), ('reason', 'week 1 more important than week 2')]

Paul's adjusted final grade will be a B.

    >>> gradebook.getAdjustedFinalGrade(stephan, paul)
    'B'

Trying to set the adjustment to an illegal letter will yield a ValueError.

    >>> gradebook.setFinalGradeAdjustment(stephan, paul, 'F',
    ...     'week 1 more important than week 2')
    Traceback (most recent call last):
    ...
    ValueError: Adjustment final grade 'F' is not a valid grade.


