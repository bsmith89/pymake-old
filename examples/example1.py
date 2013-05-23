import sys
from pymake import Rule, visualize_graph, make, maker
from time import sleep

EXT = "test"
primary_req_path = "example1.txt"

rules = [Rule("all", preqs=["branch1", "branch2"]),
         Rule("branch([0-9])",
              preqs=["branch{0}/final1.{EXT}",
                     "branch{0}/final2.{EXT}"],
              EXT=EXT),
         Rule("branch([0-9])/final([0-9]).{EXT}",
              preqs=["branch{0}/pre{1}1.{EXT}",
                     "branch{0}/pre{1}2.{EXT}"],
              recipe="cat {all_preqs} > {trgt}; sleep 1",
              EXT=EXT),
         Rule("branch([0-9])/pre([0-9])([0-9]).{EXT}",
              preqs=[primary_req_path, "branch{0}/"],
              recipe=("echo {preqs[0]} branch{0} pre{1} other{2} | \\\n"
                      "cat - {preqs[0]} > {trgt} \n"
                      "sleep 1"),
              EXT=EXT),
         Rule(".*/", recipe="mkdir {trgt} \nsleep 1", order_only=True),
         Rule("clean", recipe="rm -r branch*/")]

if __name__ == '__main__':
    maker(rules)
