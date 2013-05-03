#! /usr/bin/env python
"""A GNU Make replacement in python.

A python scripe which import pymake, defines a list of rules and
calls "make(rules, trgt)" is now a standalone makefile.

Internally, rules are parsed into a dependency tree of "requirements",
this is compressed into a hierarchical list of orders, and then the
orders are executed.

"""


import subprocess
import re
import os
import sys
import itertools
from threading import Thread
from collections import defaultdict
from termcolor import cprint


def print_recipe(string, **kwargs):
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

    def __init__(self, trgt, preqs=[], recipe=None, **env):
        self.env = env
        self.target_template = trgt
        self.prerequisite_templates = [template.strip() for template in preqs]
        self.recipe_template = recipe

    def __repr__(self):
        return ("Rule(trgt={self.target_template!r}, "
                "preqs={self.prerequisite_templates!r}, "
                "recipe={self.recipe_template!r}, "
                "**{self.env!r})").format(self=self)

    def __str__(self):
        return ("{self.target_template} : {self.prerequisite_templates}\n"
                "{self.recipe_template}").format(self=self)

    def _get_target_pattern(self):
        """Return the target pattern.

        The target pattern is returned as an exact regex.
        (i.e. with ^ and $ around it.)

        """
        return "^" + self.target_template.format(**self.env) + "$"

    def _make_target_groups(self, trgt):
        """Return regex groups for a target.

        """
        target_pattern = self._get_target_pattern()
        match = re.match(target_pattern, trgt)
        if match is not None:
            return match.groups()
        else:
            raise ValueError("{trgt} does not match {ptrn}".
                             format(trgt=trgt, ptrn=target_pattern))

    def applies(self, trgt):
        """Return if the query target matches the rule's pattern."""
        try:
            self._make_target_groups(trgt)
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
        prerequisites = [template.format(None, *groups, trgt=trgt, **self.env)
                         for template in self.prerequisite_templates]
        return prerequisites

    def _make_recipe(self, trgt):
        """Return the recipe for the target.

        Construct the recipe by matching the rule's target
        pattern to the *trgt* string.

        """
        if self.recipe_template is None:
            return None
        groups = self._get_target_groups(trgt)
        preqs = self._make_preqs(trgt)
        all_preqs = " ".join(preqs)
        return self.recipe_template.format(None, *groups, trgt=trgt,
                                           preqs=preqs, all_preqs=all_preqs,
                                           **self.env)

    def make_task(self, trgt):
        """Return a task reprisentation of rule applied to *trgt*."""
        # The trgt should always match the pattern.
        assert self.applies(trgt)
        if self.recipe_pattern is None:
            return DummyReq(trgt, self._make_preqs(trgt))
        else:
            return TaskReq(trgt, self._make_preqs(trgt),
                           self._make_recipe(trgt))

    def make_req(self, trgt):
        self.make_task(self, trgt)


class Requirement():
    """Base class for all requirements.

    Requirements are items which must be verified or carried out in a
    particular order.  All requirements have a "target" which should be
    a unique identifier for the requirement, usually a file path.

    A Rule produces a particular type of requirement called a Task
    which consists of the filled in recipe template.

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
    """A Requirement subclass used for files"""

    def __init__(self, trgt_path):
        super(FileReq, self).__init__(trgt=trgt_path)

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
        self._has_run = False  # This is just a defensive move.

    def __repr__(self):
        return ("{self.__class__.__name__}(trgt={self.target!r}, "
                "preqs={self.prerequisites!r}, "
                "recipe={self.recipe!r})").format(self=self)

    def __str__(self):
        return self.recipe

    def __hash__(self):
        return hash(self.recipe)

    def __eq__(self, other):
        # But for TaskReq objects, the recipe itself determines identity.
        return self.recipe == other.recipe

    def last_update(self):
        if os.path.exists(self.target):
            return os.path.getmtime(self.target)
        else:
            return 0.0

    def run(self, print_recipe=True, execute=True, **kwargs):
        """Run the task to create the target."""
        assert not self._has_run  # Defensive...
        if print_recipe:
            print_recipe(self.recipe, file=sys.stderr)
        if execute:
            subprocess.check_call(self.recipe, shell=True)
        self._has_run = True


class DummyReq(Requirement):
    """A requirement which only points to other requirements."""

    def __init__(self, name, preqs):
        super(DummyReq, self).__init__(trgt=name)
        self.prerequisites = preqs

    def last_update(self):
        return 0.0

    def run(self, print_recipe=True, **kwargs):
        if print_recipe:
            print("Nothing left to do for header '{trgt}'"
                  .format(trgt=self.target))


def build_dep_graph(trgt, rules, required_by=None):
    """Return a dependency graph.

    A dependency graph is a direction network linking tasks to their
    pre-requisites.

    This function encodes the graph as a recursive dictionary of Requirement
    objects.  Each requirement points to it's pre-requisites, which
    themselves point to their own pre-requisites, etc.

    The returned graph is guarenteed to be acyclic, and the root of the graph
    has the key *None*.

    Operates recursively.

    TODO: Is the "required_by" kwarg really necessary?

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
            union[requirement] = union[requirement] | graph[requirement]
    return dict(union)


def pop_dep_graph_root(graph):
    """Return the target of the dependency graph

    As it is currently designed, *build_dep_graph* returns a dictionary
    where the root requirement (the requirement associated with the *trgt*
    argument) is the only member of a set with the key *None*.

    As per the name "pop", this function removes and returns that root
    requirement.

    TODO: Build the software so this silly, breakable function isn't
          necessary.

    """
    return graph.pop(None).pop()


def merge_orders(*iters):
    """Yield sets, where equal items are only returned once.

    Takes any number of iterators of sets and merges sets from the front.

    This function is meant to deal with the semi-ordered (i.e. ordered,
    but with multiple equivilant entries) lists of requirements
    which must be merged together.

    """
    returned_set = {None}  # So that None will never be returned
    for priority_orders in itertools.zip_longest(*iters, fillvalue=set()):
        priority_set = set.union(*priority_orders)
        priority_set -= returned_set
        returned_set |= priority_set
        if priority_set != set():
            yield priority_set


def build_orders(req, graph):
    """Return a list of requirements in priority order.

    Given a dependency graph and a root requirement, returns a list
    of sets.  The items in every set only depend on items further down the
    order list.

    Operates recursively.

    """
    last_graph_update = 0.0
    last_req_update = req.last_update()
    if (req not in graph) or (len(graph[req]) == 0):
        try:  # Duck typing
            req.run
        except AttributeError:
            return [set()], last_req_update
        else:
            return [{req}], last_req_update
    preq_update_times = []
    preq_orders_lists = []
    for preq in graph[req]:
        orders_list, update_time = build_orders(preq, graph)
        preq_orders_lists.append(orders_list)
        preq_update_times.append(update_time)
    last_graph_update = max(preq_update_times)
    preq_orders_list = list(merge_orders(*preq_orders_lists))
    if last_graph_update >= last_req_update:
        return [{req}] + preq_orders_list, last_graph_update
    else:
        return [set()], last_req_update


def run_orders(orders, parallel=False, **kwargs):
    """Execute each requirement in a dependency list in order.

    If *parallel* == True, a requirement set is run in parallel.

    """
    for order_set in reversed(orders):
        threads = [Thread(target=task.run, kwargs=kwargs)
                   for task in order_set]
        if parallel:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        else:
            for thread in threads:
                thread.start()
                thread.join()


def make(trgt, rules, **kwargs):
    """Construct the dependency graph and run it."""
    graph = build_dep_graph(trgt, rules)
    root = pop_dep_graph_root(graph)
    orders, newest_order_update = build_orders(root, graph)
    run_orders(orders, **kwargs)


def visualize_graph(trgt, rules, outpath=None):
    """Draw a figure representing the dependency graph.

    By default writes the graph to a file named the same as the calling
    script.

    """
    if outpath is None:
        import __main__
        outpath = ".".join([os.path.splitext(__main__.__file__)[0], 'png'])
    import pydot
    graph = build_dep_graph(trgt, rules)
    root = pop_dep_graph_root(graph)
    orders, newester_order_update = build_orders(root, graph)
    dot = pydot.Dot(graph_name="Dependency", graph_type='digraph',
                    labelloc='r', rankdir="RL")
    dot.set_node_defaults(shape='ellipse', fontsize=24)
    for req in graph:
        for preq in graph[req]:
            dot.add_edge(pydot.Edge(req.target, preq.target))
    for rank, rank_reqs in enumerate(orders, 1):
        rank_plate = pydot.Cluster(graph_name=str(rank),
                                   label="Parallel Set {r}".format(r=rank))
        for req in rank_reqs:
            rank_plate.add_node(pydot.Node(req.target))
        dot.add_subgraph(rank_plate)
    return dot.write_png(outpath)
