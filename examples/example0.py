#! /usr/bin/env python
"""An example pymake script"""

# Simple one line import statetment.
from pymake import Rule, visualize_graph, make, maker
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
              preqs=("first{0}-1.{EXT}", r"first{0}-2.{EXT}"),
              # Various keywords are available to the recipes.
              recipe=("echo {preqs}\n"
                      "echo {trgt}\n"
                      "cat {all_preqs} > {trgt}\n"
                      "sleep 1"),
              EXT=EXT),
         Rule(trgt=r"first([0-9])-([0-9]).{EXT}",
              # Groups from the regex can also be used in the recipe.
              recipe=("echo {0} {1}\n"
                      "touch {trgt}\n"
                      "sleep 1"),
              EXT=EXT),
         Rule(trgt="clean", recipe="rm *.{EXT}", EXT=EXT)]

# Make just requires a list of sequence or iterator of rules
# And takes arbitrary targets and environmental variables
# are available to recipes.

if __name__ == '__main__':
    maker(rules)

# Environmental variables can not be set in recipes.
