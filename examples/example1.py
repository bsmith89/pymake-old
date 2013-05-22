import sys
from pymake import Rule, visualize_graph, make, maker
from time import sleep

EXT = "test"
primary_req_path = "example1.txt"

rules = [Rule("all", preqs=["branch1", "branch2"]),
         Rule("branch([0-9])",
              preqs=["branch{1}/final1.{EXT}",
                     "branch{1}/final2.{EXT}"],
              EXT=EXT),
         Rule("branch([0-9])/final([0-9]).{EXT}",
              preqs=["branch{1}/pre{2}1.{EXT}",
                     "branch{1}/pre{2}2.{EXT}"],
              recipe="cat {all_preqs} > {trgt}; sleep 1",
              EXT=EXT),
         Rule("branch([0-9])/pre([0-9])([0-9]).{EXT}",
              preqs=[primary_req_path, "branch{1}/"],
              recipe=("echo {preqs[0]} branch{1} pre{2} other{3} | \\\n"
                      "cat - {preqs[0]} > {trgt} \n"
                      "sleep 1"),
              EXT=EXT),
         Rule(".*/", recipe="mkdir {trgt} \nsleep 1", order_only=True),
         Rule("clean", recipe="rm -r branch*/")]

if __name__ == '__main__':
    maker(rules)
