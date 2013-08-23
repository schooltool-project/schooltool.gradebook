#
# SchoolTool - common information systems platform for school administration
# Copyright (c) 2012 Shuttleworth Foundation
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
Selenium functional tests setup for schooltool.gradebook
"""

from schooltool.app.testing import format_table


css_to_code = {
    'valid': 'v',
    'error': 'i',
    'extracredit': 'e',
    }


def tertiary_navigation(browser):
    result = []
    sel = 'ul.third-nav li'
    for tab in browser.query_all.css(sel):
        text = tab.text.strip()
        css_class = tab.get_attribute('class')
        if css_class is not None and 'active' in css_class:
            text = '*%s*' % text
        result.append(text)
    return result


def table_header(browser):
    result = []
    row1 = []
    sel = '.students thead a.popup_link'
    for header in browser.query_all.css(sel):
        row1.append(header.text.strip())
    sel = '.grades thead a.popup_link'
    headers = browser.driver.execute_script(
        'return $(arguments[0])', sel)
    row1.extend([header.text.strip() for header in headers])
    sel = '.totals thead a.popup_link'
    headers = browser.driver.execute_script(
        'return $(arguments[0])', sel)
    row1.extend([header.text.strip() for header in headers])
    result.append(row1)
    row2 = ['']
    sel = '#grades-part thead tr:nth-child(2) th'
    headers = browser.driver.execute_script(
        'return $(arguments[0])', sel)
    row2.extend([header.text.strip() for header in headers])
    sel = '#totals-part thead th'
    headers = browser.driver.execute_script(
        'return $(arguments[0])', sel)
    row2.extend(['' for header in headers])
    result.append(row2)
    return result


def table_rows(browser, show_validation):
    rows = []
    sel = '.students tbody a.popup_link'
    students = browser.driver.execute_script(
        'return $(arguments[0])', sel)
    for student in students:
        rows.append([student.text.strip()])
    sel = '.grades tbody tr'
    grade_rows = browser.driver.execute_script(
        'return $(arguments[0])', sel)
    for index, row in enumerate(grade_rows):
        student = rows[index]
        tds = browser.driver.execute_script(
            'return $(arguments[0]).find("td").not(".placeholder")', row)
        for td in tds:
            fields = browser.driver.execute_script(
                'return $(arguments[0]).find("input")', td)
            if fields:
                field = fields[0]
                value = browser.driver.execute_script(
                    'return arguments[0].value', field)
                value = '[%s]' % value.ljust(5, '_')
                if show_validation:
                    css_class = field.get_attribute('class')
                    value += css_to_code.get(css_class, '')
            else:
                value = td.text.strip()
            student.append(value)
    sel = '.totals tbody tr'
    total_rows = browser.driver.execute_script(
        'return $(arguments[0])', sel)
    for index, row in enumerate(total_rows):
        student = rows[index]
        tds = browser.driver.execute_script(
            'return $(arguments[0]).find("td")', row)
        for td in tds:
            student.append(td.text.strip())
    return rows

def print_gradebook(browser, show_validation):
    print format_table([tertiary_navigation(browser)])
    rows = []
    rows.extend(table_header(browser))
    for row in table_rows(browser, show_validation):
        rows.append(row)
    print format_table(rows, header_rows=2)


def registerSeleniumSetup():
    try:
        import selenium
    except ImportError:
        return
    from schooltool.testing import registry
    import schooltool.testing.selenium

    def printGradebook(browser, show_validation=False):
        print_gradebook(browser, show_validation)

    registry.register('SeleniumHelpers',
        lambda: schooltool.testing.selenium.registerBrowserUI(
            'gradebook.worksheet.pprint', printGradebook))

    def score(browser, student, activity, grade):
        row_index = None
        column_index = None
        sel = '.students tbody a.popup_link'
        for index, link in enumerate(browser.query_all.css(sel)):
            if student == link.text:
                row_index = index
                break
        sel = '.grades thead a.popup_link'
        for index, link in enumerate(browser.query_all.css(sel)):
            if activity == link.text:
                column_index = index
                break
        sel = ('//div[contains(@class, "grades")]'
               '//tbody/tr[%s]/td[%s]' % (row_index+1, column_index+1))
        cell = browser.query.xpath(sel)
        cell.click()
        cell.query.tag('input').type(browser.keys.DELETE, grade)

    registry.register('SeleniumHelpers',
        lambda: schooltool.testing.selenium.registerBrowserUI(
            'gradebook.worksheet.score', score))

registerSeleniumSetup()
del registerSeleniumSetup
