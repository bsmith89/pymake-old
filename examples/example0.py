#! /usr/bin/env python
"""An example pymake script"""

from pymake import *  # Simple one line import statetment.
import sys

EXT = 'test'

# Standard python code
# each rule is an object with several attributes
rules = [Rule("all", preqs=["top"]),
        Rule(trgt="top", preqs=("test_end.{EXT}",), EXT=EXT),
         Rule(trgt="test_end.{EXT}",
              preqs=("second1.{EXT}", "second2.{EXT}"),
              # Recipe is just a set of bash commands
              # Leading white space is ignored by bash, so it's ignored
              # here.
              recipe=("echo {preqs}\n"
                      "echo {trgt}\n"
                      "cat {all_preqs} > {trgt}\n"
                      "sleep 1"),
              EXT=EXT),
              # Regex can be used in target (don't forget to escape
              # \'s or use raw strings.) and groups found in the target
              # can be substituted in the pre-reqs and the recipe.
         Rule(trgt=r"second(.*).{EXT}",
              preqs=("first{1}-1.{EXT}", r"first{1}-2.{EXT}"),
              # Various keywords are available to the recipes.
              recipe=("echo {preqs}\n"
                      "echo {trgt}\n"
                      "cat {all_preqs} > {trgt}\n"
                      "sleep 1"),
              EXT=EXT),
         Rule(trgt=r"first([0-9])-([0-9]).{EXT}",
              # Groups from the regex can also be used in the recipe.
              recipe=("echo {1} {2}\n"
                      "touch {trgt}\n"
                      "sleep 1"),
              EXT=EXT),
         Rule(trgt="clean", recipe="rm *.{EXT}", EXT=EXT)]

# Make just requires a list of sequence or iterator of rules
# And takes arbitrary targets and environmental variables
# are available to recipes.

if __name__ == '__main__':
    try:
        target = sys.argv[1]
    except IndexError:
        target = "all"
    visualize_graph(target, rules)
    make(target, rules, parallel=True)

# Environmental variables can not be set in recipes.
