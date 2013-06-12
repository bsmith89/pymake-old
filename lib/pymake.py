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
import optparse
import logging
from threading import Thread, Event
from termcolor import cprint
from math import isnan


def print_recipe(string, **kwargs):
    cprint(string, color='blue', attrs=['bold'], **kwargs)


# TODO: Turn the backup functions into a contextmanager.

def _backup_name(path):
    return "." + path + "~pymake_backup"


def _try_backup(path):
    logging.debug("attempting to backup '{path}' if it exists".format(path=path))
    backup_path = _backup_name(path)
    try:
        os.rename(path, backup_path)
    except FileNotFoundError:
        logging.debug("'{path}' not found in order to be backed up".format(path=path))
        return False
    else:
        logging.debug("'{path}' backed up to '{backup_path}'"\
                          .format(path=path, backup_path=backup_path))
        return True

def _try_recover(path, or_remove=False):
    backup_path = _backup_name(path)
    logging.debug("attempting to recover '{path}' from '{backup_path}'".\
                      format(path=path, backup_path=backup_path))
    try:
        os.rename(backup_path, path)
    except FileNotFoundError:
        logging.debug("'{backup_path}' not found and therefore not recovered".\
                          format(backup_path=backup_path))
        if or_remove:
            try:
                os.remove(path)
            except FileNotFoundError:
                logging.debug("'{path}' not found".format(path=path))
                pass
            else:
                logging.debug(("'{path}' removed since recovery of backup "
                               "could not be completed.").format(path=path))
                pass
        return False
    else:
        return True

def _try_rmv_backup(path):
    try:
        os.remove(_backup_name(path))
    except FileNotFoundError:
        pass



class Rule():
    """A task construction and dependency rule.

    A rule is a template for a task, defining:

    *trgt* - a target pattern; a regular expression matching targets
             of the rule
    *preqs* - a list of prerequisite templates
    *recipe* - a recipe template

    Rules construct Tasks.

    """

    def __init__(self, trgt, preqs=[], recipe=None,
                 order_only=False, **env):
        self.env = env
        self.target_template = trgt
        self.prerequisite_templates = [template.strip() for template in preqs]
        self.recipe_template = recipe
        if self.recipe_template == '':
            self.recipe_template = None
        self.order_only = order_only

    def __repr__(self):
        return ("Rule(trgt={self.target_template!r}, "
                "preqs={self.prerequisite_templates!r}, "
                "recipe={self.recipe_template!r}, "
                "**{self.env!r})").format(self=self)

    def __str__(self):
        return self.target_template
#        return ("{self.target_template} : {self.prerequisite_templates}\n"
#                "{self.recipe_template}").format(self=self)

    def set_env(self, env):
        self.env = env

    def update_env(self, env_update):
        self.set_env(dict(list(self.env.items()) + list(env_update.items())))

    def get_target(self):
        return self.target_template

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
        groups = self._make_target_groups(trgt)
        prerequisites = [template.format(*groups, trgt=trgt, **self.env)
                         for template in self.prerequisite_templates]
        return prerequisites

    def _make_recipe(self, trgt):
        """Return the recipe for the target.

        Construct the recipe by matching the rule's target
        pattern to the *trgt* string.

        """
        assert self.recipe_template is not None
        groups = self._make_target_groups(trgt)
        preqs = self._make_preqs(trgt)
        all_preqs = " ".join(preqs)
        return self.recipe_template.format(*groups, trgt=trgt,
                                           preqs=preqs, all_preqs=all_preqs,
                                           **self.env)

    def make_task(self, trgt):
        """Return a task reprisentation of rule applied to *trgt*."""
        # The trgt should always match the pattern.
        assert self.applies(trgt)
        if self.recipe_template is None:
            return DummyReq(trgt, self._make_preqs(trgt))
        else:
            return TaskReq(trgt, self._make_preqs(trgt),
                           self._make_recipe(trgt), self.order_only)

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

        float('nan') should be returned when the time of last update cannot
        be determined.

        """
        raise NotImplementedError("The base Requirement class has not "
                                  "implemented last_update, but it *should* "
                                  "be implemented in all functioning "
                                  "sub-classes")


class FileReq(Requirement):
    """A Requirement with a target that is a file."""

    def __init__(self, trgt):
        super(FileReq, self).__init__(trgt=trgt)

    def last_update(self):
        if os.path.exists(self.target):
            return os.path.getmtime(self.target)
        else:
            return float('nan')


class TaskReq(FileReq):
    """A requirement which defines how to make the target file."""

    def __init__(self, trgt, preqs, recipe, order_only=False):
        super(TaskReq, self).__init__(trgt=trgt)
        self.prerequisites = preqs
        self.recipe = recipe
        self.order_only = order_only

    def __repr__(self):
        return ("{self.__class__.__name__}(trgt={self.target!r}, "
                "preqs={self.prerequisites!r}, "
                "recipe={self.recipe!r})").format(self=self)

    def __str__(self):
        return self.target

    def __hash__(self):
        return hash(self.recipe)

    def __eq__(self, other):
        # But for TaskReq objects, the recipe itself determines identity.
        return self.recipe == other.recipe

    def last_update(self):
        if self.order_only and os.path.exists(self.target):
            # If it exists, those for which it is a pre-requisite
            # (either directly or indirectly) should not be considered
            # out of date, regardless of updates to this file.
            return 0.0
        else:
            return super(TaskReq, self).last_update()

    def run(self, verbose=1, execute=True, exc_event=None, **kwargs):
        """Run the task to create the target."""
        logging.debug("running task for {self.target}".format(self=self))
        logging.info("\n{self.recipe}".format(self=self))
#        if verbose >= 1:
#            print_recipe(self.recipe, file=sys.stderr)
        if execute:
            logging.debug("executing {self.target}".format(self=self))
            _try_backup(self.target)
            try:
                subprocess.check_call(self.recipe, shell=True)
            except subprocess.CalledProcessError as err:
                _try_recover(self.target, or_remove=True)
                exc_event.set()
                raise err
            _try_rmv_backup(self.target)


class DummyReq(Requirement):
    """A requirement which only points to other requirements."""

    def __init__(self, trgt, preqs):
        super(DummyReq, self).__init__(trgt=trgt)
        self.prerequisites = preqs

    def last_update(self):
        return float('nan')

    def run(self, verbose=1, **kwargs):
        logging.info(("\nDummyReq '{self.target}' running, which usually "
                      "indicates that all sub-tasks are completed.").format(self=self))
#        if verbose >= 1:
#            print_recipe("Nothing left to do for dummy-requirement '{trgt}'"
#                         .format(trgt=self.target))


def build_dep_graph(trgt, rules):
    """Return the root and a dependency graph.

    A dependency graph is a direction network linking tasks to their
    pre-requisites.

    This function encodes the graph as a recursive dictionary of Requirement
    objects.  Each requirement points to it's pre-requisites, which
    themselves point to their own pre-requisites, etc.

    The returned graph is guarenteed to be acyclic.

    Operates recursively.

    """
    logging.debug("entered build_dep_graph for '{trgt}'".format(trgt=trgt))
    rules = list(rules)
    trgt_rule = None
    for i, rule in enumerate(rules):
        if rule.applies(trgt):
            trgt_rule = rules.pop(i)
            logging.debug("'{trgt_rule!s}' applies to {trgt}".\
                              format(trgt_rule=trgt_rule, trgt=trgt))
            break
    if trgt_rule is None:
        logging.debug("no rule found which applies to {trgt}".format(trgt=trgt))
        if os.path.exists(trgt):
            logging.debug("'{trgt}' exists".format(trgt=trgt))
            requirement = FileReq(trgt)
            return requirement, {requirement: set()}
        else:
            raise ValueError(("No rule defined for {trgt!r}, the required "
                              "file doesn't exist, or there is a "
                              "cycle in the dependency graph.")
                             .format(trgt=trgt))
    trgt_task = trgt_rule.make_task(trgt)
    preq_trgts = trgt_task.prerequisites
    preq_tasks = set()
    trgt_graph = {}
    for preq_trgt in preq_trgts:
        preq_task, preq_graph = build_dep_graph(preq_trgt, rules)
        preq_tasks.add(preq_task)
        trgt_graph = dict(list(trgt_graph.items()) + list(preq_graph.items()))
    trgt_graph[trgt_task] = preq_tasks
    return trgt_task, trgt_graph


def merge_orders(*iters):
    """Yield merged sets from *iters*.

    Takes any number of iterators of sets and merges sets from the front.
    Where any given entry in a set only occurs once.

    This function is meant to deal with the semi-ordered (i.e. priority
    ordered, but with ties) lists of requirements which must be merged
    together.

    """
    returned_set = set()
    for priority_orders in itertools.zip_longest(*iters, fillvalue=set()):
        priority_set = set.union(*priority_orders)
        priority_set -= returned_set
        returned_set |= priority_set
        if priority_set != set():
            yield priority_set


def build_orders(req, graph):
    """Return a list of requirements in priority order.

    Given a dependency graph and a root requirement, returns a list
    of sets.  The requirements in every set only depend on requirements
    further down the orders list.

    Operates recursively.

    """
    last_req_update = req.last_update()
    if (req not in graph) or (len(graph[req]) == 0):
        logging.debug("'{req!s}' is a leaf requirement".format(req=req))
        if not hasattr(req, 'run'):
            logging.debug("'{req!s}' is not runnable".format(req=req))
            return [set()], last_req_update
        elif not isnan(last_req_update):  # The target already exists:
            logging.debug("'{req!s}' last updated at {last_update}".\
                              format(req=req, last_update=last_req_update))
            return [set()], last_req_update
        else:  # The target does not exist and the task is runnable:
            logging.debug(("'{req!s}' does not exist; the task to create "
                           "it has been added to the build orders").format(req=req))
            return [{req}], last_req_update
    preq_update_times = []
    preq_orders_lists = []
    for preq in graph[req]:
        orders_list, update_time = build_orders(preq, graph)
        preq_orders_lists.append(orders_list)
        preq_update_times.append(update_time)
    last_graph_update = max(preq_update_times)
    logging.debug(("the most recent update of a pre-requisite for "
                   "'{req!s}' was at {last_update}").\
                       format(req=req, last_update=last_graph_update))
    preq_orders_list = list(merge_orders(*preq_orders_lists))
    # Remember that last_graph_update is *nan* if _any_ prereq is nan.
    # last_req_update is nan if the target file does not currently exist.
    # Therefore, a set of orders will be returned when either of these
    # possibilities occurs (plus the canonical case, when any precursor
    # was updated more recently than the focal requirement.)
    if last_graph_update < last_req_update:
        logging.debug("'{req!s}' is up-to-date".format(req=req))
        return [set()], last_req_update
    else:
        logging.debug("'{req!s}' is not up-to-date and will be updated.".format(req=req))
        return [{req}] + preq_orders_list, last_graph_update


def run_orders(orders, parallel=False, **kwargs):
    """Execute each requirement in a dependency list in order.

    If *parallel* == True, a requirement set is run in parallel.

    """
    kwargs['exc_event'] = exc_event = Event()
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
        if exc_event.is_set():
            raise Exception("At least one order failed in this set.  No more "
                            "orders will be excecuted.")


def make(trgt, rules, env={}, **kwargs):
    """Construct the dependency graph and run it."""
    for rule in rules:
        rule.update_env(env)
    root, graph = build_dep_graph(trgt, rules)
    orders, newest_order_update = build_orders(root, graph)
    run_orders(orders, **kwargs)


def get_default_fig_outpath():
    import __main__
    return ".".join([os.path.splitext(__main__.__file__)[0], 'png'])


def visualize_graph(trgt, rules, outpath=None):
    """Draw a figure representing the dependency graph.

    By default writes the graph to a file named the same as the calling
    script.

    """
    if outpath is None:
        outpath = get_default_fig_outpath()
    import pydot
    root, graph = build_dep_graph(trgt, rules)
    orders, newester_order_update = build_orders(root, graph)
    dot = pydot.Dot(graph_name="Dependency", graph_type='digraph',
                    labelloc='r', rankdir="BT")
    dot.set_node_defaults(shape='ellipse', fontsize=24)
    for req in graph:
        for preq in graph[req]:
            dot.add_edge(pydot.Edge(preq.target, req.target))
    for rank, rank_reqs in enumerate(reversed(orders), 1):
        rank_plate = pydot.Cluster(graph_name=str(rank),
                                   label="Order set {r}".format(r=rank))
        for req in rank_reqs:
            rank_plate.add_node(pydot.Node(req.target))
        dot.add_subgraph(rank_plate)
    return dot.write_png(outpath)


def maker(rules):
    usage = "usage: %prog [options] [TARGET]"
    parser = optparse.OptionParser(usage=usage)
    parser.add_option("-q", "--quiet", action="store_const",
                      const=0, dest="verbose",
                      help=("don't print recipes. "
                            "DEFAULT: print recipes"))
    parser.add_option("-v", "--verbose", action="count",
                      dest="verbose", default=1,
                      help=("print recipes. "
                            "Increment the logging level by 1. "
                            "DEFAULT: verbosity level 1 ('INFO')"))
    parser.add_option("-n", "--dry", action="store_false",
                      dest="execute", default=True,
                      help=("Dry run.  Don't execute the recipes. "
                            "DEFAULT: execute recipes"))
    parser.add_option("--figure", dest="fig_outpath",
                      help=("Visualize the graph."))
    parser.add_option("-p", "--parallel", action="store_true",
                      dest="parallel", default=True,
                      help=("execute the recipes in parallel processes. "
                            "DEFAULT: parallel"))
    parser.add_option("-s", "--series", "--not-parallel",
                      action="store_false", dest="parallel", default=True,
                      help=("execute the recipes in series. "
                            "DEFAULT: parallel"))
    parser.add_option("-V", "--var", "--additional-var", dest="env_items",
                      default=[], action="append",
                      nargs=2, metavar="[KEY] [VALUE]",
                      help=("add the desired variable to the environment. "
                            "Additional variables can be passed with "
                            "more '-V' flags. Variables passed in this "
                            "fasion override variables defined in any other "
                            "way"))
    opts, args = parser.parse_args()

    logging.basicConfig(level=[logging.ERROR, logging.INFO, logging.DEBUG][opts.verbose])

    if len(args) > 0:
        target = args[0]
    elif len(args) == 0:
        # If no target specified, use the first target.  This will not take into account
        # environmental variables passed with the '-V' flag.
        target = rules[0].get_target()
    else:
        ValueError("Wrong number of positional arguments passed to pymake.")
    if opts.fig_outpath:
        visualize_graph(target, rules, opts.fig_outpath)
    make(target, rules, env=dict(opts.env_items), verbose=opts.verbose,
         execute=opts.execute, parallel=opts.parallel)
    # TODO: Take a parser option with additional environmental variables.
