"""Control-flow exceptions for the agent."""


class Escalate(Exception):
    """Stop and hand the case to a person."""

    def __init__(self, field, problem, suggested_action):
        super().__init__(problem)
        self.field = field
        self.problem = problem
        self.suggested_action = suggested_action

    def to_dict(self):
        return {"field": self.field, "problem": self.problem, "suggested_action": self.suggested_action}
