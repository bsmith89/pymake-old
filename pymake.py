import subprocess
import re
import os
import shutil


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
    def __init__(self, trgt_pat, preq_pats="", recipe_pat="", env={}):
        # Immediately replace all format identifiers in trgt and preqs.
        self.env = env
        self.target_pattern = "^" + trgt_pat.format_map(env) + "$"
        if isinstance(preq_pats, str):
            self.prerequisite_patterns = [preq_pats.format_map(env)]
        else:
            self.prerequisite_patterns = [pattern.format_map(env)
                                          for pattern in preq_pats]
        self.prerequisite_patterns = clean_strings(self.prerequisite_patterns)
        self.recipe_pattern = recipe_pat

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
        return Task(trgt, self._make_preqs(trgt), self._make_recipe(trgt))


class Task():
    def __init__(self, trgt, preqs, recipe):
        self.target = trgt
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
    """Build a task dependency tree by walking it recursively."""
    rules = list(rules)  # Copy the rules list so that functions are indep.
    trgt = trgt.strip()
    if trgt is None:
        return None
    if trgt is "":
        return None
    target_rule = None
    for i, rule in enumerate(rules):
        if rule.applies(trgt):
            target_rule = rule
            rules.pop(i)
            break
    if target_rule is None:
        if os.path.exists(trgt):
            return trgt
        else:
            raise ValueError(("No rule defined for {trgt!r}, or there is a "
                              "cycle in the dependency graph.")
                             .format(trgt=trgt))
    task = target_rule.make_task(trgt)
    preqs = task.prerequisites
    preq_trees = [build_task_tree(rules, preq_trgt)
                  for preq_trgt in preqs]
    branch = (task, preq_trees)
    return branch

def run_task_tree(tree):
    task = tree[0]
    preq_trees = tree[1]
    for preq in preq_trees:
        run_task_tree(preq)
    task.run()

def make(trgt, rules):
    tree = build_task_tree(trgt, rules)




if __name__ == "__main__":
    rules = [Rule('all', ['this.txt', 'that.txt', 'theother.txt']),
             Rule('(.*).txt', '', 'echo {1} > {trgt}')]
    tree = build_task_tree(rules, 'all')
    print(tree)
