#!/usr/bin/make
#
# Makefile for schooltool.gradebook Buildout
#

BOOTSTRAP_PYTHON=python2.5

.PHONY: all
all: build

.PHONY: build
build:
	test -d python || $(MAKE) BOOTSTRAP_PYTHON=$(BOOTSTRAP_PYTHON) bootstrap
	test -f bin/test || $(MAKE) buildout
	test -d instance || $(MAKE) build-schooltool-instance

.PHONY: bootstrap
bootstrap:
	$(BOOTSTRAP_PYTHON) bootstrap.py

.PHONY: buildout
buildout:
	bin/buildout

.PHONY: update
update: build
	bzr up
	bin/buildout -n

.PHONY: test
test: build
	bin/test -u

.PHONY: testall
testall: build
	bin/test

.PHONY: ftest
ftest: build
	bin/test -f

.PHONY: build-schooltool-instance
build-schooltool-instance:
	bin/make-schooltool-instance instance instance_type=schooltool.stapp2007

.PHONY: run
run: build
	bin/start-schooltool-instance instance

.PHONY: release
release: compile-translations
	echo -n `sed -e 's/\n//' version.txt.in` > version.txt
	echo -n "_r" >> version.txt
	bzr revno >> version.txt
	bin/buildout setup setup.py sdist

.PHONY: move-release
move-release:
	 mv dist/schooltool.gradebook-*.tar.gz /home/ftp/pub/schooltool/releases/nightly

.PHONY: coverage
coverage: build
	rm -rf coverage
	bin/test -u --coverage=coverage
	mv parts/test/coverage .
	@cd coverage && ls | grep -v tests | xargs grep -c '^>>>>>>' | grep -v ':0$$'

.PHONY: coverage-reports-html
coverage-reports-html:
	rm -rf coverage/reports
	mkdir coverage/reports
	bin/coverage
	ln -s schooltool.gradebook.html coverage/reports/index.html

.PHONY: clean
clean:
	rm -rf bin develop-eggs parts python
	rm -rf build dist
	rm -f .installed.cfg
	rm -f ID TAGS tags
	find . -name '*.py[co]' -exec rm -f {} \;
	find . -name '*.mo' -exec rm -f {} +
	find . -name 'LC_MESSAGES' -exec rmdir -p --ignore-fail-on-non-empty {} +

.PHONY: extract-translations
extract-translations: build
	bin/i18nextract --egg schooltool.gradebook --domain schooltool.gradebook --zcml schooltool/gradebook/translations.zcml --output-file src/schooltool/gradebook/locales/schooltool.gradebook.pot

.PHONY: compile-translations
compile-translations:
	set -e; \
	locales=src/schooltool/gradebook/locales; \
	for f in $${locales}/*.po; do \
	    mkdir -p $${f%.po}/LC_MESSAGES; \
	    msgfmt -o $${f%.po}/LC_MESSAGES/schooltool.gradebook.mo $$f;\
	done

.PHONY: update-translations
update-translations: extract-translations
	set -e; \
	locales=src/schooltool/gradebook/locales; \
	for f in $${locales}/*.po; do \
	    msgmerge -qU $$f $${locales}/schooltool.gradebook.pot ;\
	done
	$(MAKE) PYTHON=$(PYTHON) compile-translations

.PHONY: ubuntu-environment
ubuntu-environment:
	@if [ `whoami` != "root" ]; then { \
	 echo "You must be root to create an environment."; \
	 echo "I am running as $(shell whoami)"; \
	 exit 3; \
	} else { \
	 apt-get install bzr build-essential python-all python-all-dev libc6-dev libicu-dev; \
	 apt-get build-dep python-imaging; \
	 apt-get build-dep python-libxml2 libxml2; \
	 echo "Installation Complete: Next... Run 'make'."; \
	} fi
