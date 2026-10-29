"""Trouble Brewing script data: roles, kinds and setup counts."""

TOWNSFOLK = (
    "washerwoman", "librarian", "investigator", "chef", "empath", "fortune_teller",
    "undertaker", "monk", "ravenkeeper", "virgin", "slayer", "soldier", "mayor",
)
OUTSIDERS = ("butler", "drunk", "recluse", "saint")
MINIONS = ("poisoner", "spy", "scarlet_woman", "baron")
DEMONS = ("imp",)
ALL_ROLES = TOWNSFOLK + OUTSIDERS + MINIONS + DEMONS
# In a world, the role of a good player whose claim isn't taken at face value (silent, or bluffing).
WILD = ("?townsfolk", "?outsider")

KIND = {
    **{r: "townsfolk" for r in TOWNSFOLK},
    **{r: "outsider" for r in OUTSIDERS},
    **{r: "minion" for r in MINIONS},
    **{r: "demon" for r in DEMONS},
    "?townsfolk": "townsfolk",
    "?outsider": "outsider",
}

# players -> (townsfolk, outsiders, minions, demons), before the Baron's adjustment
SETUP = {
    5: (3, 0, 1, 1), 6: (3, 1, 1, 1), 7: (5, 0, 1, 1), 8: (5, 1, 1, 1), 9: (5, 2, 1, 1),
    10: (7, 0, 2, 1), 11: (7, 1, 2, 1), 12: (7, 2, 2, 1),
    13: (9, 0, 3, 1), 14: (9, 1, 3, 1), 15: (9, 2, 3, 1),
}

FIRST_NIGHT_INFO = ("washerwoman", "librarian", "investigator", "chef", "empath", "fortune_teller")


def is_evil(role):
    return KIND[role] in ("minion", "demon")


def pretty(role):
    if role in WILD:
        return "unknown " + role[1:].title()
    return role.replace("_", " ").title()
