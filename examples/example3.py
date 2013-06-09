#! /usr/bin/env python
"""An example pymake script"""

# Simple one line import statetment.
from pymake import Rule, maker
import sys


rules = [Rule("all",
              recipe=("echo environmental variables [this, that, other] \n"
                      "echo equal [{this} {that} {other}]. \n"
                      "echo DEFAULT [1 2 3]"),
              this=1, that=2, other=3)]


if __name__ == '__main__':
    maker(rules)
