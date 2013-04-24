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
DONE: Parse the dependency tree to compress it into a dependency graph
      i.e. don't remake identical pre-requisites.

"""


import subprocess
import re
import os
import sys
from datetime import datetime
from multiprocessing.pool import ThreadPool
from functools import partial
from collections import defaultdict
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
        # For a Requirement object, self.target wholey determines
        # identity.

    def __hash__(self):
        return hash(self.target)

    def __eq__(self, other):
        return self.target == other.target

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
        self.has_run = False

    def __repr__(self):
        return ("{self.__class__.__name__}(trgt={self.target!r}, "
                "preqs={self.prerequisites!r}, "
                "recipe={self.recipe!r})").format(self=self)

    def __str__(self):
        # TODO
        return self.recipe

    def __hash__(self):
        return hash(self.recipe)

    def __eq__(self, other):
        # But for TaskReq objects, the recipe itself determines identity.
        return self.recipe == other.recipe

    def last_update(self):
        if os.path.exists(self.target):
            return os.path.getmtime(self.target)
        elif self.prerequisites in (None, [], "", [""]):
            return 0.0
        else:
            return 0.0

    def run(self, print_recipe=True, execute=True):
        """Run the task to create the target."""
        if self.has_run:
            return
        if print_recipe:
            print_bold(self.recipe, file=sys.stderr)
        if execute:
            subprocess.check_call(self.recipe, shell=True)


def build_dep_graph(trgt, rules, required_by=None):
    """Return a dependency graph.

    A dependency graph is a direction network linking tasks to their
    pre-requisites.

    This function encodes the graph as a recursive dictionary of Requirement
    objects.  Each requirement points to it's pre-requisites, which
    themselves point to their own pre-requisites, etc.

    The returned graph is guarenteed to be acyclic, and the root of the graph
    has the key *None*.

    """
    rules = list(rules)
    trgt = trgt.strip()
    if trgt is None:
        return None
    if trgt is "":
        return None
    trgt_rule = None
    for i, rule in enumerate(rules):
        if rule.applies(trgt):
            trgt_rule = rules.pop(i)
            break
    if trgt_rule is None:
        if os.path.exists(trgt):
            requirement = FileReq(trgt)
            return {required_by: set([requirement]), requirement: set()}
        else:
            raise ValueError(("No rule defined for {trgt!r}, or there is a "
                              "cycle in the dependency graph.")
                             .format(trgt=trgt))
    task = trgt_rule.make_task(trgt)
    preqs = task.prerequisites
    preq_graphs = [build_dep_graph(preq_trgt, rules, task)
                   for preq_trgt in preqs]
    union = defaultdict(set)
    union[task]  # Initialize a set of pre-reqs for task
    union[required_by] = set([task])
    for graph in preq_graphs:
        for requirement in graph:
            union[requirement] = union[requirement] | \
                                 graph[requirement]
    return dict(union)


def run_dep_graph(req, graph, parallel=False, **kwargs):
    last_graph_update = 0.0
    last_req_update = req.last_update()
    try:
        # This is the step which prevents double running tasks.
        # The dependency graph dictionary is shared between the threads,
        # so poping all of the dependencies forces the task to only be done
        # once.
        preqs = graph.pop(req)
    except KeyError:
        # When the task has already been done, it's key is removed from
        # the dictionary.  That means that a KeyError is raised for any
        # task which has already been run.
        # The result is that no task is run, and the requirement's update
        # time is returned.
        # TODO: are we sure that this won't mess up the scheme I'm using to
        # figure out when to update requirements?
        return max(last_graph_update, last_req_update)
    if len(preqs) != 0:
        if parallel:
            # The use of a ThreadPool is vital, since the state of the
            # dependency graph must be shared.
            pool = ThreadPool(processes=len(preqs))
            map_func = pool.map
        else:
            map_func = map
        run_graph = partial(run_dep_graph, graph=graph, **kwargs)
        last_graph_update = max(map_func(run_graph, preqs))
    if last_graph_update >= last_req_update:
        req.run(**kwargs)
        return datetime.now().timestamp()
    else:
        return max(last_graph_update, last_req_update)


def unduplicate_graph(graph):
    """Probably the most obfuscated code I've ever written.

    But it works!"""
    graph = dict(graph)
    for out_node in graph:
        if out_node is None:
            continue
        for in_node in graph[out_node]:
            if in_node in graph:
                graph[out_node].remove(in_node)
                graph[out_node].add(list(graph)[list(graph).index(in_node)])
    return(graph)


def make(trgt, rules, **kwargs):
    """Construct the dependency graph and run it."""
    graph = build_dep_graph(trgt, rules)
    # This is a hack, and should be fixed:
    graph = unduplicate_graph(graph)
    run_dep_graph(graph[None].pop(), graph, **kwargs)

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
#    system_test0()
    pass

