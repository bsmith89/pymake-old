#! /usr/bin/env python
"""An example pymake script"""

from pymake import *  # Simple one line import statetment.
import sys

env = dict(EXT='test')

# Standard python code
# each rule is an object with several attributes
rules = [Rule(trgt="all", preqs="test_end.{EXT}", env=env),
         Rule(trgt="test_end.{EXT}",
              preqs=("second1.{EXT}", "second2.{EXT}"),
              # Recipe is just a set of bash commands
              # Leading white space is ignored by bash, so it's ignored
              # here.
              recipe=("echo {preqs}\n"
                      "echo {trgt}\n"
                      "cat {all_preqs} > {trgt}"),
              env=env),
              # Regex can be used in target (don't forget to escape
              # \'s or use raw strings.) and groups found in the target
              # can be substituted in the pre-reqs and the recipe.
         Rule(trgt=r"second(.*).{EXT}",
              preqs=(r"first\1-1.{EXT}", r"first\1-2.{EXT}"),
              # Various keywords are available to the recipes.
              recipe=("echo {preqs}\n"
                      "echo {trgt}\n"
                      "cat {all_preqs} > {trgt}"),
              env=env),
         Rule(trgt=r"first([0-9])-([0-9]).{EXT}",
              # Groups from the regex can also be used in the recipe.
              recipe=("echo {1} {2}\n"
                      "touch {trgt}"),
              env=env),
         Rule(trgt="clean", preqs="", recipe="rm *.{EXT}", env=env)]

# Make just requires a list of sequence or iterator of rules
# And takes arbitrary targets and environmental variables
# are available to recipes.

try:
    target = sys.argv[1]
except IndexError:
    target = "all"
make(target, rules, parallel=True)

# Environmental variables can not be set in recipes.
