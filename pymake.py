#! /usr/bin/env python
"""A GNU Make replacement in python.

Example:

>>> rules = [Rule(trgt=r'all\.test\.txt',
...               preqs=['this.test.txt', 'that.test.txt',
...                      'theother.test.txt'],
...               recipe='cat {all_preqs} > all.test.txt'),
...          Rule(trgt=r'this\.test.txt',
...               preqs='foo.thing',
...               recipe='cat foo.thing > this.test.txt'),
...          Rule(trgt=r'(.*)\.test\.txt',
...               recipe='echo {1} > {trgt}'),
...          Rule(trgt='clean', recipe='rm *.test.txt foo.thing')]
>>> foo = open('foo.thing', 'w')
>>> foo.write('booooyaaaaa!!!!')
15
>>> foo.close()
>>> make(rules, 'all.test.txt')
cat foo.thing > this.test.txt
echo that > that.test.txt
echo theother > theother.test.txt
cat this.test.txt that.test.txt theother.test.txt > all.test.txt

>>> make(rules, 'clean')
rm *.test.txt foo.thing

These rule sets and targets can be put into a file, pymake can
be imported, and the final script serves as a complete makefile.

"""


import subprocess
import re
import os
import shutil
import datetime


def clean_strings(strings):
    clean_strings = []
    for string in strings:
        if string is None:
            continue
        string = string.strip()
        if string == "":
            continue
        else:
            clean_strings.append(string)
    return clean_strings

class Rule():
    def __init__(self, trgt, preqs="",
                 recipe="", env={}):
        # Immediately replace all format identifiers in trgt and preqs.
        self.env = env
        self.target_pattern = "^" + trgt.format_map(env) + "$"
        if isinstance(preqs, str):
            self.prerequisite_patterns = [preqs.format_map(env)]
        else:
            self.prerequisite_patterns = [pattern.format_map(env)
                                          for pattern in preqs]
        # TODO: Figure out how to make cleaning the pre-requisites unecessary
        self.prerequisite_patterns = clean_strings(self.prerequisite_patterns)
        self.recipe_pattern = recipe

    def __repr__(self):
        return ("Rule(trgt='{trgt}', "
                "preqs={self.prerequisite_patterns}, "
                "recipe='{self.recipe_pattern}', "
                "env={self.env})").format(trgt=self.target_pattern[1:-1],
                                          self=self)
    def __str__(self):
        return """{trgt} : {preqs}\n\t{self.recipe_pattern}"""\
                .format(trgt=self.target_pattern[1:-1],
                        preqs=" ".join(self.prerequisite_patterns),
                        self=self)

    def _get_target_match(self, trgt):
        match = re.match(self.target_pattern, trgt)
        if match is not None:
            return match
        else:
            raise ValueError("{trgt} does not match {ptrn}".
                             format(trgt=trgt, ptrn=self.target_pattern))

    def applies(self, trgt):
        try:
            self._get_target_match(trgt)
        except ValueError:
            return False
        else:
            return True

    def _make_preqs(self, trgt):
        match = self._get_target_match(trgt)
        prerequisites = [match.expand(pattern)
                         for pattern in self.prerequisite_patterns]
        return prerequisites

    def _make_recipe(self, trgt):
        match = self._get_target_match(trgt)
        groups = match.groups()
        mapping = dict(list(self.env.items()))
        mapping['trgt'] = trgt
        mapping['preqs'] = self._make_preqs(trgt)
        mapping['all_preqs'] = " ".join(mapping['preqs'])
        # TODO: figure out what I want the first positional arg to be.
        return self.recipe_pattern.format(None, *groups, **mapping)

    def make_task(self, trgt):
        # The trgt should always match the pattern.
        assert self.applies(trgt)
        return Task(trgt, self._make_preqs(trgt),
                    self._make_recipe(trgt))


class Requirement():
    def __init__(self, trgt):
        self.target = trgt

    def __repr__(self):
        return "Requirement(trgt={self.target!r})".format(self=self)

    def __str__(self):
        return self.target

    def last_update(self):
        """Return the last time the requirement was updated.

        The time returned determines the whether or not other tasks are
        considered up to date, so if you want all tasks which depend on
        the given task to run, this function should return a larger value.

        """
        if os.path.exists(self.target):
            return os.path.getmtime(self.target)
        else:
            return 0.0


class Task(Requirement):
    def __init__(self, trgt, preqs, recipe):
        super(Task, self).__init__(trgt=trgt)
        self.prerequisites = preqs
        self.recipe = recipe

    def __repr__(self):
        return ("Task(trgt={self.target!r}, preqs={self.prerequisites!r}, "
                "recipe={self.recipe!r})").format(self=self)

    def __str__(self):
        # TODO
        return self.recipe

    def run(self):
        print(self.recipe)
        subprocess.check_call(self.recipe, shell=True)


def build_task_tree(rules, trgt):
    """Build a dependency tree by walking it recursively."""
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
            return (Requirement(trgt),)
        else:
            raise ValueError(("No rule defined for {trgt!r}, or there is a "
                              "cycle in the dependency graph.")
                             .format(trgt=trgt))
    task = target_rule.make_task(trgt)
    preqs = task.prerequisites
    preq_trees = [build_task_tree(rules, preq_trgt)
                  for preq_trgt in preqs]
    branch = (task,) + tuple(preq_trees)
    return branch

def run_task_tree(tree):
    requirement = tree[0]
    last_tree_update = 0.0
    preq_trees = tree[1:]
    for preq in preq_trees:
        last_tree_update = max(run_task_tree(preq), last_tree_update)
    if last_tree_update >= requirement.last_update():
        requirement.run()
        return datetime.datetime.now().timestamp()
    else:
        return max(last_tree_update, requirement.last_update())

def make(rules, trgt):
    tree = build_task_tree(rules, trgt)
    run_task_tree(tree)


if __name__ == "__main__":
    import doctest
    doctest.testmod()
