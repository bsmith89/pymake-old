#! /usr/bin/env python
"""A GNU Make replacement in python.

Example:

>>> # Define a list of rules in order of priority:
>>> rules = [Rule(trgt=r'all{some_key}\.test\.txt',
...               preqs=['this.test.txt', 'that.test.txt',
...                      'theother.test.txt'],
...               recipe=('sleep 1\\n'  # Simulates a longer running job.
...                       'cat {all_preqs} > all{some_key}.test.txt'),
...               some_key=5),
...          Rule(trgt=r'this\.test.txt',
...               preqs='foo.thing',
...               recipe='cat foo.thing > this.test.txt'),
...          Rule(trgt=r'(.*)\.test\.txt',
...               recipe='echo {1} > {trgt}'),
...          Rule(trgt='clean', recipe='rm *.test.txt foo.thing')]
>>> # Let's make the only pure dependency:
>>> foo = open('foo.thing', 'w')
>>> foo.write('booooyaaaaa!!!!\\n')
16
>>> foo.close()
>>> import time
>>> time.sleep(1)  # Because otherwise the timestamps are too similar.
>>> # And now call make().  It really is that easy!
>>> make('all5.test.txt', rules)
cat foo.thing > this.test.txt
echo that > that.test.txt
echo theother > theother.test.txt
sleep 1
cat this.test.txt that.test.txt theother.test.txt > all5.test.txt

>>> # And the contents:
>>> open('all5.test.txt').read()
'booooyaaaaa!!!!\\nthat\\ntheother\\n'
>>> # Now what happens if we try to make it again?
>>> make('all5.test.txt', rules)
>>> # Everythings up to date alread!
>>> # If we touch foo.thing...
>>> os.utime('foo.thing')
>>> # One branch of the tree must be re-run.
>>> make('all5.test.txt', rules)
cat foo.thing > this.test.txt
sleep 1
cat this.test.txt that.test.txt theother.test.txt > all5.test.txt

>>> # Oh look, we defined a 'clean' rule!
>>> make('clean', rules)
rm *.test.txt foo.thing



A python scripe which import pymake, defines a list of rules and
calls "make(rules, trgt)" is now a standalone makefile.

DONE: Make syntax more consistant by using {1} for the first groups
rather than \\1.
TODO: Parse the dependency tree to compress it into a dependency graph
      i.e. don't remake identical pre-requisites.

"""


import subprocess
import re
import os
import sys
from datetime import datetime
from multiprocessing.pool import ThreadPool as Pool
from functools import partial
from termcolor import cprint


def clean_strings(strings):
    """Return a list of strings with None's and empty strings removed."""
    clean_strings = []
    if strings is None:
        return clean_strings
    for string in strings:
        if string is None:
            continue
        string = string.strip()
        if string == "":
            continue
        else:
            clean_strings.append(string)
    return clean_strings


def print_bold(string, **kwargs):
    cprint(string, color='blue', attrs=['bold'], **kwargs)


class Rule():
    """A task construction and dependency rule.

    A rule is a template for a task, defining:
    
    *trgt* - a target pattern; a regular expression matching targets
             of the rule
    *preqs* - a list of prerequisite templates
    *recipe* - a recipe template

    Rules construct Tasks.

    """

    def __init__(self, trgt, preqs="", recipe="", **env):
        # Immediately replace all format identifiers in trgt.
        self.env = env
        self.target_pattern = "^" + trgt.format_map(self.env) + "$"
        # But not in pre-reqs or the recipe...
        if isinstance(preqs, str):
            self.prerequisite_patterns = [preqs]
        # TODO: Figure out how to make cleaning the pre-requisites unecessary
        else:
            self.prerequisite_patterns = preqs
        self.prerequisite_patterns = clean_strings(self.prerequisite_patterns)
        self.recipe_pattern = recipe

    def __repr__(self):
        return ("Rule(trgt='{trgt}', "
                "preqs={self.prerequisite_patterns}, "
                "recipe='{self.recipe_pattern}', "
                "**{self.env})").format(trgt=self.target_pattern[1:-1],
                                        self=self)

    def __str__(self):
        return "{trgt} : {preqs}\n\t{self.recipe_pattern}"\
               .format(trgt=self.target_pattern[1:-1],
                       preqs=" ".join(self.prerequisite_patterns),
                       self=self)

    def _get_target_groups(self, trgt):
        """Return a regex groups for a target.

        """
        match = re.match(self.target_pattern, trgt)
        if match is not None:
            return match.groups()
        else:
            raise ValueError("{trgt} does not match {ptrn}".
                             format(trgt=trgt, ptrn=self.target_pattern))

    def applies(self, trgt):
        """Return if the query target matches the rule's pattern."""
        try:
            self._get_target_groups(trgt)
        except ValueError:
            return False
        else:
            return True

    def _make_preqs(self, trgt):
        """Return a list of prerequistites for the target.

        Construct pre-requisites by matching the rule's target
        pattern to the *trgt* string.

        """
        groups = self._get_target_groups(trgt)
        prerequisites = [pattern.format(None, *groups, trgt=trgt, **self.env)
                         for pattern in self.prerequisite_patterns]
        return prerequisites

    def _make_recipe(self, trgt):
        """Return the recipe for the target.

        Construct the recipe by matching the rule's target
        pattern to the *trgt* string.

        """
        groups = self._get_target_groups(trgt)
        preqs = self._make_preqs(trgt)
        all_preqs = " ".join(self._make_preqs(trgt))
        # TODO: figure out what I want the first positional arg to be.
        return self.recipe_pattern.format(None, *groups, trgt=trgt,
                                          preqs=preqs, all_preqs=all_preqs,
                                          **self.env)

    def make_task(self, trgt):
        """Return a task reprisentation of rule applied to *trgt*."""
        # The trgt should always match the pattern.
        assert self.applies(trgt)
        return TaskReq(trgt, self._make_preqs(trgt),
                       self._make_recipe(trgt))


class Requirement():
    """Base class for all requirements.

    """

    def __init__(self, trgt):
        self.target = trgt

    def __repr__(self):
        return ("{self.__class__.__name__}"
                "(trgt={self.target!r})").format(self=self)

    def __str__(self):
        return self.target

    def last_update(self):
        """Return the time that the target was last updated.

        The time returned determines the whether or not other tasks are
        considered up to date, so if you want all tasks which depend on
        the given task to run, this function should return a larger value.

        """
        raise NotImplementedError("The base Requirement class has not "
                                  "implemented last_update, but it *should* "
                                  "be implemented in all functioning "
                                  "sub-classes")


class FileReq(Requirement):
    """A Requirement subclass used for file requirements."""
    def __init__(self, trgt_path):
        super(FileReq, self).__init__(trgt = trgt_path)

    def last_update(self):
        if os.path.exists(self.target):
            return os.path.getmtime(self.target)
        else:
            return 0.0


class TaskReq(Requirement):
    """A requirement which defines how to make the target."""

    def __init__(self, trgt, preqs, recipe):
        super(TaskReq, self).__init__(trgt=trgt)
        self.prerequisites = preqs
        self.recipe = recipe

    def __repr__(self):
        return ("{self.__class__.__name__}(trgt={self.target!r}, "
                "preqs={self.prerequisites!r}, "
                "recipe={self.recipe!r})").format(self=self)

    def __str__(self):
        # TODO
        return self.recipe

    def last_update(self):
        if os.path.exists(self.target):
            return os.path.getmtime(self.target)
        elif self.prerequisites in (None, [], "", [""]):
            return 0.0
        else:
            return 0.0

    def run(self, print_recipe=True, execute=True):
        """Run the task to create the target."""
        if print_recipe:
            print_bold(self.recipe, file=sys.stderr)
        if execute:
            subprocess.check_call(self.recipe, shell=True)


class DepTree():
    """A dependency tree which is defined recursively."""
    def __init__(target, preqs=[]):
        # TODO
        raise NotImplementedError("The dependency tree data structure has "
                                  "not yet been implemented.")


def build_task_tree(trgt, rules):
    """Build a dependency tree by walking a rules list recursively."""
    rules = list(rules)  # Copy the rules list so that we can edit in place.
    trgt = trgt.strip()
    if trgt is None:
        return None
    if trgt is "":
        return None
    target_rule = None
    for i, rule in enumerate(rules):
        if rule.applies(trgt):
            target_rule = rules.pop(i)
            break
    if target_rule is None:
        if os.path.exists(trgt):
            return (FileReq(trgt),)
        else:
            raise ValueError(("No rule defined for {trgt!r}, or there is a "
                              "cycle in the dependency graph.")
                             .format(trgt=trgt))
    task = target_rule.make_task(trgt)
    preqs = task.prerequisites
    preq_trees = [build_task_tree(preq_trgt, rules)
                  for preq_trgt in preqs]
    branch = (task,) + tuple(preq_trees)
    return branch


def run_task_tree(tree, **kwargs):
    """Run a dependency tree by walking it recursively."""
    requirement = tree[0]
    last_tree_update = 0.0
    last_req_update = requirement.last_update()
    preq_trees = tree[1:]
    if len(preq_trees) != 0:
        run_tree = partial(run_task_tree, **kwargs)
        last_tree_update = max(map(run_tree, preq_trees))
    if last_tree_update >= last_req_update:
        requirement.run(**kwargs)
        return datetime.now().timestamp()
    else:
        return max(last_tree_update, last_req_update)


def pll_run_task_tree(tree, **kwargs):
    """Run a dependency tree by walking it recursively.

    Parallelize running by making a new thread for each
    pre-requisite of a task.

    """
    requirement = tree[0]
    last_tree_update = 0.0
    last_req_update = requirement.last_update()
    preq_trees = tree[1:]
    if len(preq_trees) != 0:
        # Let's setup the parallelization.
        run_tree = partial(pll_run_task_tree, **kwargs)
        pool = Pool(processes=len(preq_trees))
        map = pool.map
        # Now the rest is exactly the same as run_task_tree...
        last_tree_update = max(map(run_tree, preq_trees))
    if last_tree_update >= last_req_update:
        requirement.run(**kwargs)
        return datetime.now().timestamp()
    else:
        return max(last_tree_update, last_req_update)



def make(trgt, rules, parallel=False, **kwargs):
    """Construct the task tree and run it."""
    tree = build_task_tree(trgt, rules)
    if parallel:
        pll_run_task_tree(tree, **kwargs)
    else:
        run_task_tree(tree, **kwargs)

def system_test0():
    """Currently almost the same as the unit-test.
    
    Assistance for debugging.
    
    """
    rules = [Rule(trgt=r'all{some_key}\.test\.txt',
                  preqs=['this.test.txt', 'that.test.txt',
                         'theother.test.txt'],
                  recipe=('cat {all_preqs} > {trgt}'),
                  some_key=5),
             Rule(trgt=r'this\.test.txt',
                  preqs='foo.thing',
                  recipe='cat foo.thing > this.test.txt'),
             Rule(trgt=r'(.*)\.test\.txt',
                  recipe='echo {1} > {trgt}'),
             Rule(trgt='clean', recipe='rm *.test.txt foo.thing')]
    foo = open('foo.thing', 'w')
    foo.write('booooyaaaaa!!!!\n')
    foo.close()
    make('all5.test.txt', rules)
    print(open('all5.test.txt').read())
    make('all5.test.txt', rules, parallel=True)  # Test parallelized make.
    os.utime('foo.thing')
    # One branch of the tree must be re-run.
    make('all5.test.txt', rules)
    make('clean', rules)

def doctest():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
#    doctest()
    system_test0()
    pass

