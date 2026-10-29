"""Everything the game says, in English and Chinese.

The engine never builds sentences itself. It records a message (`M`): a key plus arguments, where
an argument can be a player (`S`), a character (`R`), a list (`L`) or another message. Messages are
rendered in whichever language the reader picked, so a game can switch language at any time.
Some keys have several phrasings; the engine picks one by seed, so games stay reproducible.
"""

LANGS = ("en", "zh")


class M:
    __slots__ = ("key", "args", "v")

    def __init__(self, key, v=0, **args):
        self.key, self.args, self.v = key, args, v

    def __repr__(self):
        return f"M({self.key!r}, {self.args!r})"


class S:
    """A player, rendered as their name."""
    __slots__ = ("seat",)

    def __init__(self, seat):
        self.seat = seat


class R:
    """A character, rendered in the reader's language."""
    __slots__ = ("role",)

    def __init__(self, role):
        self.role = role


class AbilityText:
    """A character's ability text, in the reader's language."""
    __slots__ = ("role",)

    def __init__(self, role):
        self.role = role


class L:
    """A list. `conj`: 'A, B and C'. `paren`: ' (A, B)', or nothing if empty."""
    __slots__ = ("items", "conj", "paren")

    def __init__(self, items, conj=False, paren=False):
        self.items, self.conj, self.paren = list(items), conj, paren


ROLE_NAMES = {
    "en": {
        "washerwoman": "Washerwoman", "librarian": "Librarian", "investigator": "Investigator", "chef": "Chef",
        "empath": "Empath", "fortune_teller": "Fortune Teller", "undertaker": "Undertaker", "monk": "Monk",
        "ravenkeeper": "Ravenkeeper", "virgin": "Virgin", "slayer": "Slayer", "soldier": "Soldier", "mayor": "Mayor",
        "butler": "Butler", "drunk": "Drunk", "recluse": "Recluse", "saint": "Saint",
        "poisoner": "Poisoner", "spy": "Spy", "scarlet_woman": "Scarlet Woman", "baron": "Baron", "imp": "Imp",
        "?townsfolk": "unknown Townsfolk", "?outsider": "unknown Outsider",
    },
    "zh": {
        "washerwoman": "洗衣妇", "librarian": "图书管理员", "investigator": "调查员", "chef": "厨师",
        "empath": "共情者", "fortune_teller": "占卜师", "undertaker": "送葬者", "monk": "僧侣",
        "ravenkeeper": "守鸦人", "virgin": "贞洁者", "slayer": "猎手", "soldier": "士兵", "mayor": "镇长",
        "butler": "管家", "drunk": "酒鬼", "recluse": "隐士", "saint": "圣徒",
        "poisoner": "投毒者", "spy": "间谍", "scarlet_woman": "红唇女郎", "baron": "男爵", "imp": "小恶魔",
        "?townsfolk": "未知镇民", "?outsider": "未知外来者",
    },
}

KIND_NAMES = {
    "en": {"townsfolk": "Townsfolk", "outsider": "Outsider", "minion": "Minion", "demon": "Demon"},
    "zh": {"townsfolk": "镇民", "outsider": "外来者", "minion": "爪牙", "demon": "恶魔"},
}

# Ability text. * = not on the first night.
ABILITY = {
    "en": {
        "washerwoman": "You start knowing that 1 of 2 players is a particular Townsfolk.",
        "librarian": "You start knowing that 1 of 2 players is a particular Outsider. (Or that zero are in play.)",
        "investigator": "You start knowing that 1 of 2 players is a particular Minion.",
        "chef": "You start knowing how many pairs of evil players there are (sitting next to each other).",
        "empath": "Each night, you learn how many of your 2 alive neighbours are evil.",
        "fortune_teller": "Each night, choose 2 players: you learn if either is a Demon. "
                          "There is a good player that registers as a Demon to you (the red herring).",
        "undertaker": "Each night*, you learn which character died by execution today.",
        "monk": "Each night*, choose a player (not yourself): they are safe from the Demon tonight.",
        "ravenkeeper": "If you die at night, you are woken to choose a player: you learn their character.",
        "virgin": "The 1st time you are nominated, if the nominator is a Townsfolk, they are executed immediately.",
        "slayer": "Once per game, during the day, publicly choose a player: if they are the Demon, they die.",
        "soldier": "You are safe from the Demon.",
        "mayor": "If only 3 players live & no execution occurs, your team wins. "
                 "(In this version the Mayor never redirects a night kill.)",
        "butler": "Each night, choose a player (not yourself): tomorrow, you may only vote if they are voting too.",
        "drunk": "You do not know you are the Drunk. You think you are a Townsfolk character, but you are not: "
                 "your ability doesn't work and your information may be false.",
        "recluse": "You might register as evil & as a Minion or Demon, even if dead.",
        "saint": "If you die by execution, your team loses.",
        "poisoner": "Each night, choose a player: they are poisoned tonight and tomorrow day "
                    "(their ability malfunctions and their information may be false).",
        "spy": "Each night, you see the Grimoire. You might register as good & as a Townsfolk or Outsider, even if dead.",
        "scarlet_woman": "If there are 5 or more players alive & the Demon dies, you become the Demon.",
        "baron": "There are extra Outsiders in play. [+2 Outsiders]",
        "imp": "Each night*, choose a player: they die. (In this version the Imp never kills itself.)",
    },
    "zh": {
        "washerwoman": "在你的首个夜晚，你会得知两名玩家和一个镇民角色：这两名玩家之一是该角色。",
        "librarian": "在你的首个夜晚，你会得知两名玩家和一个外来者角色：这两名玩家之一是该角色。（或者你会得知没有外来者在场。）",
        "investigator": "在你的首个夜晚，你会得知两名玩家和一个爪牙角色：这两名玩家之一是该角色。",
        "chef": "在你的首个夜晚，你会得知场上邻座的邪恶玩家有多少对。",
        "empath": "每个夜晚，你会得知与你邻近的两名存活的玩家中邪恶玩家的数量。",
        "fortune_teller": "每个夜晚，你要选择两名玩家：你会得知他们之中是否有恶魔。会有一名善良玩家始终被你的能力当作恶魔（干扰项）。",
        "undertaker": "每个夜晚*，你会得知今天白天死于处决的玩家的角色。",
        "monk": "每个夜晚*，你要选择除你以外的一名玩家：当晚恶魔的负面能力对他无效。",
        "ravenkeeper": "如果你在夜晚死亡，你会被唤醒，然后你要选择一名玩家：你会得知他的角色。",
        "virgin": "当你首次被提名时，如果提名你的玩家是镇民，他立刻被处决。",
        "slayer": "每局游戏限一次，你可以在白天时公开选择一名玩家：如果他是恶魔，他死亡。",
        "soldier": "恶魔的负面能力对你无效。",
        "mayor": "如果只有三名玩家存活且白天没有人被处决，你的阵营获胜。（本版本中镇长不会转移夜晚的死亡。）",
        "butler": "每个夜晚，你要选择除你以外的一名玩家：明天白天，只有他投票时你才能投票。",
        "drunk": "你不知道你是酒鬼。你以为你是一个镇民角色，但其实你不是：你的能力无效，你得到的信息可能是错的。",
        "recluse": "你可能会被当作邪恶阵营、爪牙角色或恶魔角色，即使你已死亡。",
        "saint": "如果你死于处决，你的阵营落败。",
        "poisoner": "每个夜晚，你要选择一名玩家：他在当晚和明天白天中毒（能力失效，信息可能是错的）。",
        "spy": "每个夜晚，你能查看魔典。你可能会被当作善良阵营、镇民角色或外来者角色，即使你已死亡。",
        "scarlet_woman": "如果大于等于五名玩家存活时恶魔死亡，你变成那个恶魔。",
        "baron": "会有额外的外来者在场。[+2外来者]",
        "imp": "每个夜晚*，你要选择一名玩家：他死亡。（本版本中小恶魔不会自杀。）",
    },
}

TEXT = {
    "en": {
        "raw": "{text}",
        "speech": '{p}: "{text}"',
        "first_night_note": "* = not on the first night.",
        # setup
        "game_start": "Game #{seed}: {n} players.",
        "you_are": "You are {me}. Players clockwise: {players}.",
        "your_char": "Your character: {role}. {ability}",
        "you_good": "You are good. You may claim your character truthfully, bluff, or keep quiet; "
                    "but if you change your claim in public, people will trust you less.",
        "you_evil": "You are EVIL. Your team: {team}.",
        "seat_role": "{p} ({role})",
        "bluffs": "Demon bluffs (good characters not in play): {roles}.",
        "mates_claim": "Your teammates plan to claim: {list}.",
        "as": "{p} as {role}",
        "learn": "You learn: {info}.",
        "spy_grim": "Spy, the Grimoire: {list}.",
        "grim_entry": "{p} {role}{flags}",
        "flag_poisoned": " (poisoned)",
        "flag_thinks": " (thinks {role})",
        "now_imp": "The Demon died: you are now the Imp.",
        "was_saint": "{p} was the Saint!",
        # phases
        "night_falls": "Night {n} falls. Everyone closes their eyes.",
        "day_header": "Day {d}",
        "dawn_deaths": "Dawn: {list} died in the night.",
        "dawn_none": "Dawn: nobody died.",
        "phase_intro": "Introductions: everyone says who they are.",
        "phase_chats": "Private conversations: players may step aside in small groups.",
        "phase_discussion": "Discussion: everyone speaks once, in turn.",
        "phase_noms": "Nominations are open.",
        "phase_react": "Everyone has said who they are. Now: whom do you suspect?",
        "night_title": "Night {n}",
        "night_body": "Everyone closes their eyes. Characters with night abilities wake in turn.",
        "learn_title": "During the night you learned",
        "phase_chats_title": "Private conversations",
        "phase_chats_body": "Players step aside in small groups. Only the group hears what is said.",
        "phase_discussion_body": "Everyone speaks in turn: say who you are, share what you learned, say whom you suspect.",
        "phase_discussion_title": "Open discussion",
        "phase_noms_title": "Nominations and votes",
        "phase_noms_body": "Anyone alive may nominate once. Each nominee defends themself, then the table votes. Most votes, if at least half the living, is executed.",
        "result_title": "Today's execution",
        "slayer_title": "The Slayer fires",
        "virgin_title": "The Virgin's power",
        "over_title": "Game over",
        "q_react": "Everyone has spoken. Anything to add?",
        # speech
        "claim": ["I am the {role}.", "I'm the {role}.", "{role} here.", "I'm the {role}, for what it's worth."],
        "claim_change": ["I wasn't telling the truth. I'm not the {old}, I'm the {new}.",
                         "Time to come clean: I'm actually the {new}, not the {old}."],
        "report": ["Night {n}, my {role} ability: {info}.", "On night {n} I learned: {info}."],
        "suspect": ["I suspect {t}: {why}.", "My money's on {t}: {why}.", "Keep an eye on {t}: {why}."],
        "suspect_plain": "I suspect {t}.",
        "no_read": ["I don't have a strong read on anyone yet.", "Honestly, I can't tell yet."],
        "reply": ["That's not fair. I'm the {role}, and I'm good.", "Look elsewhere: I'm the {role}.",
                  "I'm not the Demon. I'm the {role}."],
        "reply_silent": "I'm not the Demon.",
        "defend": ["I'm good, I'm the {role}.", "You've got the wrong person. I'm the {role}.",
                   "Please don't, I really am the {role}."],
        "defend_silent": "I'm good.",
        "w_really": "Between us: I'm really the {role}.",
        "w_claim": "I'm the {role}.",
        "e_role": "I'm the {role}; my bluff is {claim}.",
        "e_poison": "I'll poison {t} tonight.",
        "e_kill": "Tonight I plan to kill {t}.",
        "e_ok": "Got it, {t} it is.",
        "s_kill": "Let's kill {t} tonight.",
        "e_bluff_for_you": "For you: claim {role}. It's one of my bluffs, so nobody good has it.",
        "counter": ["Wait. I'm the {role}. {t} is lying.", "No, I'm the real {role}. {t} is not telling the truth."],
        "stay_quiet": ["I'd rather not say my character yet. I've told the people I trust.",
                       "I'll keep my character to myself for now."],
        "no_exec_info": "Nobody was executed yesterday, so my Undertaker ability learned nothing.",
        "r_counter": "they claim my own character, the {role}",
        "r_noinfo": "they claim {role} but still haven't said what they learned",
        "lbl_given": "{role} (the Demon's bluff for you)",
        "s_poison": "Poison {t} tonight.",
        "shoot": '{p}: "I\'m the Slayer, and I shoot {t}." {result}',
        "shot_dies": "{t} dies!",
        "shot_nothing": "Nothing happens.",
        # info
        "info_ping": "one of {a}/{b} is the {role}",
        "info_zero": "there are no Outsiders",
        "info_chef": "{c} pair(s) of evil neighbours",
        "info_empath": "{c} evil neighbour(s)",
        "info_ft": "{a} or {b} the Demon? {ans}",
        "yes": "YES",
        "no": "no",
        "info_monk": "protected {a}",
        "info_undertaker": "{a} was the {role}",
        "info_ravenkeeper": "{a} is the {role}",
        "describe": "N{n} {p} ({role}): {info}",
        # reasons
        "r_silent": "they still haven't said what they are",
        "r_evilclaim": "they said they are the {role}",
        "r_twin": "{x} also claims to be the {role}",
        "r_changed": "they claimed {old} before switching to {new}",
        "r_pushed": "they pushed {x}'s execution, and {x} looks good now",
        "r_ft": "{x}'s Fortune Teller got a YES on them",
        "r_inv": "{x}'s Investigator ping says they might be the {role}",
        "r_ft_mine": "my Fortune Teller got a YES on them",
        "r_inv_mine": "my Investigator ping says they might be the {role}",
        "r_ifinfo": "if {whose} info is right, they're evil in {pct}% of the setups that fit",
        "my": "my",
        "whose": "{x}'s",
        "r_demon_pct": "they're the Demon in {pct}% of the setups I can make fit",
        "r_nothing": "nothing clears them, and I can vouch for most others",
        # nominations
        "nominates": ['{a} nominates {t}: "{why}."', '{a} nominates {t}. "{why}."'],
        "nominates_plain": "{a} nominates {t}.",
        "virgin": "{a} nominates {t}: the Virgin's power triggers and {a} is executed!",
        "vote_on": "Vote on {t}: {needed} votes needed.",
        "vote_on_block": "Vote on {t}: {needed} votes needed to replace {b} on the block.",
        "votes_block": "{k} vote(s){voters}: {t} is about to die.",
        "votes_tie": "{k} vote(s){voters}: a tie, so nobody is about to die.",
        "votes_short": "{k} vote(s){voters}: not enough.",
        "executed": "{t} is executed.",
        "no_execution": "No execution today.",
        "mayor_win": "Three players remain with no execution: the Mayor wins it for good!",
        # private conversations
        "chats_step": "{list} step aside to talk privately.",
        "you_step": "You step aside with {list}.",
        "declined": "{list} declined to talk with you.",
        "hint": "Hint ({k} possible worlds): most suspicious {list}",
        "seat_pct": "{p} {pct}",
        # end
        "winner": "*** {team} WINS after {d} day(s) ***",
        "team_good": "GOOD", "team_evil": "EVIL", "team_none": "NOBODY (day limit)",
        "grimoire": "Grimoire:",
        "grim_line": "  {p}: {role}{extra} [{who}]",
        "drunk_thought": " (thought they were the {role})",
        "red_herring": " [red herring]",
        "dead": " (dead)",
        "who_you": "you", "who_evil": "{who}, evil",
        "novice": "novice", "regular": "regular", "veteran": "veteran", "reference": "reference",
        "bluffs_end": "Demon bluffs: {roles}",
        "st_notes": "Storyteller notes:",
        "note_line": "  N{n}/D{d}: {msg}",
        "note_poison": "Poisoner poisons {t}",
        "note_survive": "Imp attacks {t}, who survives",
        "note_sw": "Scarlet Woman {t} becomes the Imp",
        "note_shown": "{p} ({why}) shown: {info}",
        "why_drunk": "drunk", "why_poisoned": "poisoned",
        # notebook
        "nb_title": "--- Notebook ---",
        "nb_claims": "Current claims: {list}",
        "seat_claim": "{p} {role}",
        "silent": "(silent)",
        "nb_night": "Night {n}: {list} died.",
        "nb_night_none": "Night {n}: no deaths.",
        "nb_report": "  {line}",
        "nb_day": "Day {n}:",
        "nb_claimed": "  {p} claimed {role}",
        "nb_claimed_changed": "  {p} claimed {role} (changed from {old})",
        "nb_shot": "  {p} shot {t}: {result}",
        "nb_shot_died": "died", "nb_shot_nothing": "nothing",
        "nb_virgin": "  {a} nominated {t}: Virgin triggered, {a} executed",
        "nb_vote": "  {a} → {t}: {k} vote(s){voters}",
        "nb_exec": "  Executed: {p}",
        "nb_noexec": "  No execution.",
        "nb_dead": "Dead: {list}",
        "nb_nobody": "nobody",
        "dead_entry": "{p}",
        "dead_entry_used": "{p} (ghost vote used)",
        "nb_chats": "Your private conversations:",
        "nb_chat_claim": "  Day {d} (with {list}): {p} claimed {role}",
        "nb_chat_report": "  Day {d} (with {list}): {line}",
        "nb_told": "Told to you privately:",
        "nb_private": "  {when}: {msg}",
        "when_setup": "Setup", "when_night": "Night {n}", "when_day": "Day {n}",
        # prompts
        "q_turn": "Your turn to speak.",
        "q_defend": "You've been nominated. What do you say?",
        "a_claim": "Claim a character",
        "a_change": "Change your claim (now: {role})",
        "a_share": "Tell what your {role} ability showed you",
        "a_accuse": "Say whom you suspect",
        "a_shoot": "Use the Slayer's shot",
        "a_done": "Done speaking",
        "q_whom_suspect": "Whom do you suspect?",
        "q_shoot": "Shoot whom?",
        "q_which_char": "Which character do you claim to be?",
        "lbl_role": "{role}",
        "lbl_yours": "{role} (your character)",
        "lbl_bluff": "{role} (Demon bluff)",
        "lbl_evil": "{role} (evil character: looks bad if you're good)",
        "q_which_night": "Which night?",
        "lbl_night": "Night {n}",
        "q_ft_pick": "Night {n}: which two players did you choose?",
        "q_ft_answer": "And the answer you got?",
        "q_monk_pick": "Night {n}: whom did you protect?",
        "q_info": "Night {n}: what do you say your {role} ability showed you?",
        "lbl_real": "{info} (what you really learned)",
        "lbl_else": "Something else...",
        "q_two": "Which two players?",
        "q_as_which": "As which character?",
        "q_chat": "You're talking privately. What do you say?",
        "c_claim": "Tell them your character",
        "c_share": "Tell them what your {role} ability showed you",
        "c_accuse": "Tell them whom you suspect",
        "c_kill": "Suggest tonight's kill",
        "c_poison": "Suggest tonight's poison target",
        "c_done": "Done talking",
        "q_kill_suggest": "Whom should the Demon kill tonight?",
        "q_poison_suggest": "Whom should the Poisoner poison tonight?",
        "q_intro": "Introductions: what do you tell the table?",
        "i_claim": "Claim a character",
        "i_silent": "Stay silent for now",
        "q_ft": "Fortune Teller: choose two players to ask about.",
        "q_monk": "Monk: whom do you protect tonight?",
        "q_rk": "Ravenkeeper: you died tonight. Whose character do you learn?",
        "q_butler": "Butler: choose your master (you may only vote when they do).",
        "q_poison": "Poisoner: whom do you poison tonight?",
        "q_kill": "Imp: whom do you kill tonight?",
        "q_nominate": "Do you want to nominate someone? Pick a player, or pass.",
        "q_vote": "Raise your hand? Vote to execute {t} with {kind}. ({yes} so far, {needed} needed)",
        "your_vote": "your vote",
        "your_ghost_vote": "your ghost vote (you only get one)",
        "q_aside": "Private conversations: do you want to take someone aside?",
        "aside_no": "No", "aside_one": "Talk with one player", "aside_two": "Talk with two players",
        "q_invite": "Whom do you invite?",
        "q_accept": "{p} wants to talk with you privately{extra}. Join them?",
        "together": " (together with {list})",
    },
    "zh": {
        "raw": "{text}",
        "speech": "{p}：“{text}”",
        "first_night_note": "* = 首个夜晚除外。",
        "game_start": "第{seed}局：{n}名玩家。",
        "you_are": "你是{me}。座位顺时针依次为：{players}。",
        "your_char": "你的角色：{role}。{ability}",
        "you_good": "你是善良阵营。你可以如实报出身份、伪装成别的角色，或者暂时沉默；但如果你之后公开改口，大家会更不信任你。",
        "you_evil": "你是邪恶阵营。你的队友：{team}。",
        "seat_role": "{p}（{role}）",
        "bluffs": "恶魔的伪装身份（不在场的善良角色）：{roles}。",
        "mates_claim": "你的队友打算这样报身份：{list}。",
        "as": "{p}报{role}",
        "learn": "你得知：{info}。",
        "spy_grim": "间谍查看魔典：{list}。",
        "grim_entry": "{p} {role}{flags}",
        "flag_poisoned": "（中毒）",
        "flag_thinks": "（以为自己是{role}）",
        "now_imp": "恶魔死了：你现在是小恶魔。",
        "was_saint": "{p}是圣徒！",
        "night_falls": "第{n}夜降临。所有人闭眼。",
        "day_header": "第{d}天",
        "dawn_deaths": "天亮了：{list}在夜里死亡。",
        "dawn_none": "天亮了：昨晚是平安夜。",
        "phase_intro": "自我介绍：每人说出自己的身份。",
        "phase_chats": "私聊时间：玩家可以分成小组私下交谈。",
        "phase_discussion": "公开讨论：每人依次发言一次。",
        "phase_noms": "提名开始。",
        "phase_react": "大家都报过身份了。现在说说你怀疑谁。",
        "night_title": "第{n}夜",
        "night_body": "所有人闭眼。有夜间能力的角色依次醒来。",
        "learn_title": "你在夜里得知",
        "phase_chats_title": "私聊时间",
        "phase_chats_body": "玩家分成小组私下交谈，只有组内的人能听到。",
        "phase_discussion_body": "每人依次发言：报身份、报信息、说出你怀疑谁。",
        "phase_discussion_title": "公开讨论",
        "phase_noms_title": "提名与投票",
        "phase_noms_body": "每位存活玩家可以提名一次。被提名者先辩解，然后全桌投票。票数最多且不少于存活人数一半的人将被处决。",
        "result_title": "今天的处决",
        "slayer_title": "猎手开枪",
        "virgin_title": "贞洁者的能力",
        "over_title": "游戏结束",
        "q_react": "大家都发过言了。你还有什么要说的吗？",
        "claim": ["我是{role}。", "我的身份是{role}。", "我报{role}。", "我是{role}，大家可以信我。"],
        "claim_change": ["之前我没说实话。我不是{old}，我是{new}。", "我得坦白：我其实是{new}，不是{old}。"],
        "report": ["第{n}夜，我的{role}能力：{info}。", "第{n}夜我得知：{info}。"],
        "suspect": ["我怀疑{t}：{why}。", "我觉得{t}有问题：{why}。", "大家注意{t}：{why}。"],
        "suspect_plain": "我怀疑{t}。",
        "no_read": ["我暂时还看不出谁有问题。", "说实话，我现在还判断不了。"],
        "reply": ["这不公平。我是{role}，我是好人。", "看看别人吧：我是{role}。", "我不是恶魔，我是{role}。"],
        "reply_silent": "我不是恶魔。",
        "defend": ["我是好人，我是{role}。", "你们找错人了，我是{role}。", "别处决我，我真的是{role}。"],
        "defend_silent": "我是好人。",
        "w_really": "私下跟你们说：我其实是{role}。",
        "w_claim": "我是{role}。",
        "e_role": "我是{role}，我对外报{claim}。",
        "e_poison": "今晚我毒{t}。",
        "e_kill": "今晚我打算杀{t}。",
        "e_ok": "明白，就{t}。",
        "s_kill": "今晚杀{t}吧。",
        "e_bluff_for_you": "给你件衣服：你报{role}。这是我的伪装身份之一，不会有好人撞上。",
        "counter": ["等等，我才是{role}。{t}在说谎。", "不对，真正的{role}是我。{t}没说实话。"],
        "stay_quiet": ["我暂时不公开身份，已经私下告诉我信任的人了。", "我先不报身份。"],
        "no_exec_info": "昨天没人被处决，所以我的送葬者能力没有得到信息。",
        "r_counter": "他跳了我的身份{role}",
        "r_noinfo": "他报了{role}，却一直没说得到了什么信息",
        "lbl_given": "{role}（恶魔给你的衣服）",
        "s_poison": "今晚毒{t}。",
        "shoot": "{p}：“我是猎手，我对{t}开枪。”{result}",
        "shot_dies": "{t}死了！",
        "shot_nothing": "什么都没有发生。",
        "info_ping": "{a}和{b}之中有一位是{role}",
        "info_zero": "场上没有外来者",
        "info_chef": "有{c}对邪恶玩家相邻",
        "info_empath": "{c}名邪恶邻座",
        "info_ft": "{a}或{b}是恶魔吗？{ans}",
        "yes": "是",
        "no": "否",
        "info_monk": "保护了{a}",
        "info_undertaker": "{a}的角色是{role}",
        "info_ravenkeeper": "{a}是{role}",
        "describe": "第{n}夜 {p}（{role}）：{info}",
        "r_silent": "他至今没说自己的身份",
        "r_evilclaim": "他自己说是{role}",
        "r_twin": "{x}也声称自己是{role}",
        "r_changed": "他先报{old}，后来又改成了{new}",
        "r_pushed": "他推动了处决{x}，而{x}现在看起来是好人",
        "r_ft": "{x}的占卜对他得到了“是”",
        "r_inv": "{x}的调查员信息显示他可能是{role}",
        "r_ft_mine": "我的占卜对他得到了“是”",
        "r_inv_mine": "我的调查员信息显示他可能是{role}",
        "r_ifinfo": "如果{whose}信息是对的，在说得通的配置里他有{pct}%是邪恶的",
        "my": "我的",
        "whose": "{x}的",
        "r_demon_pct": "在我能推出的配置里，他有{pct}%是恶魔",
        "r_nothing": "没有什么能证明他清白，而其他人我大多能担保",
        "nominates": ["{a}提名{t}：“{why}。”", "{a}提名了{t}。“{why}。”"],
        "nominates_plain": "{a}提名{t}。",
        "virgin": "{a}提名{t}：贞洁者的能力生效，{a}立刻被处决！",
        "vote_on": "对{t}投票：需要{needed}票。",
        "vote_on_block": "对{t}投票：需要{needed}票才能取代{b}上处决台。",
        "votes_block": "{k}票{voters}：{t}将被处决。",
        "votes_tie": "{k}票{voters}：平票，没有人将被处决。",
        "votes_short": "{k}票{voters}：票数不够。",
        "executed": "{t}被处决。",
        "no_execution": "今天没有人被处决。",
        "mayor_win": "只剩三人且无人被处决：镇长为善良阵营赢得胜利！",
        "chats_step": "{list}走到一边私下交谈。",
        "you_step": "你和{list}走到一边私聊。",
        "declined": "{list}拒绝了和你私聊。",
        "hint": "提示（{k}种可能的配置）：最可疑的是{list}",
        "seat_pct": "{p} {pct}",
        "winner": "*** {team}获胜，共进行了{d}天 ***",
        "team_good": "善良阵营", "team_evil": "邪恶阵营", "team_none": "无人（达到天数上限）",
        "grimoire": "魔典：",
        "grim_line": "  {p}：{role}{extra}［{who}］",
        "drunk_thought": "（以为自己是{role}）",
        "red_herring": "［干扰项］",
        "dead": "（已死亡）",
        "who_you": "你", "who_evil": "{who}，邪恶",
        "novice": "新手", "regular": "普通", "veteran": "老手", "reference": "参考",
        "bluffs_end": "恶魔的伪装身份：{roles}",
        "st_notes": "说书人笔记：",
        "note_line": "  第{n}夜/第{d}天：{msg}",
        "note_poison": "投毒者毒了{t}",
        "note_survive": "小恶魔袭击了{t}，但他活了下来",
        "note_sw": "红唇女郎{t}变成了小恶魔",
        "note_shown": "{p}（{why}）得到的信息：{info}",
        "why_drunk": "酒鬼", "why_poisoned": "中毒",
        "nb_title": "--- 笔记 ---",
        "nb_claims": "当前身份：{list}",
        "seat_claim": "{p} {role}",
        "silent": "（未发言）",
        "nb_night": "第{n}夜：{list}死亡。",
        "nb_night_none": "第{n}夜：平安夜。",
        "nb_report": "  {line}",
        "nb_day": "第{n}天：",
        "nb_claimed": "  {p}报了{role}",
        "nb_claimed_changed": "  {p}报了{role}（原先报{old}）",
        "nb_shot": "  {p}对{t}开枪：{result}",
        "nb_shot_died": "死亡", "nb_shot_nothing": "无事发生",
        "nb_virgin": "  {a}提名{t}：贞洁者生效，{a}被处决",
        "nb_vote": "  {a} → {t}：{k}票{voters}",
        "nb_exec": "  被处决：{p}",
        "nb_noexec": "  无人被处决。",
        "nb_dead": "已死亡：{list}",
        "nb_nobody": "无",
        "dead_entry": "{p}",
        "dead_entry_used": "{p}（已用掉死人票）",
        "nb_chats": "你参与的私聊：",
        "nb_chat_claim": "  第{d}天（与{list}）：{p}报了{role}",
        "nb_chat_report": "  第{d}天（与{list}）：{line}",
        "nb_told": "说书人私下告诉你的：",
        "nb_private": "  {when}：{msg}",
        "when_setup": "开局", "when_night": "第{n}夜", "when_day": "第{n}天",
        "q_turn": "轮到你发言了。",
        "q_defend": "你被提名了。你要说什么？",
        "a_claim": "报出身份",
        "a_change": "改报身份（当前：{role}）",
        "a_share": "说出你的{role}能力得到的信息",
        "a_accuse": "说出你怀疑谁",
        "a_shoot": "使用猎手的能力开枪",
        "a_done": "发言结束",
        "q_whom_suspect": "你怀疑谁？",
        "q_shoot": "对谁开枪？",
        "q_which_char": "你要报什么身份？",
        "lbl_role": "{role}",
        "lbl_yours": "{role}（你的角色）",
        "lbl_bluff": "{role}（恶魔伪装身份）",
        "lbl_evil": "{role}（邪恶角色：如果你是好人，这样报会很可疑）",
        "q_which_night": "哪一夜？",
        "lbl_night": "第{n}夜",
        "q_ft_pick": "第{n}夜：你选了哪两名玩家？",
        "q_ft_answer": "你得到的结果是？",
        "q_monk_pick": "第{n}夜：你保护了谁？",
        "q_info": "第{n}夜：你要说你的{role}能力得到了什么信息？",
        "lbl_real": "{info}（你真正得到的信息）",
        "lbl_else": "其他……",
        "q_two": "哪两名玩家？",
        "q_as_which": "是哪个角色？",
        "q_chat": "你正在私聊。你要说什么？",
        "c_claim": "告诉他们你的身份",
        "c_share": "告诉他们你的{role}能力得到的信息",
        "c_accuse": "告诉他们你怀疑谁",
        "c_kill": "建议今晚杀谁",
        "c_poison": "建议今晚毒谁",
        "c_done": "结束私聊",
        "q_kill_suggest": "今晚恶魔应该杀谁？",
        "q_poison_suggest": "今晚投毒者应该毒谁？",
        "q_intro": "自我介绍：你要对大家说什么？",
        "i_claim": "报出身份",
        "i_silent": "暂时保持沉默",
        "q_ft": "占卜师：选择两名玩家进行占卜。",
        "q_monk": "僧侣：今晚你要保护谁？",
        "q_rk": "守鸦人：你今晚死了。你要查看谁的角色？",
        "q_butler": "管家：选择你的主人（只有他投票时你才能投票）。",
        "q_poison": "投毒者：今晚你要毒谁？",
        "q_kill": "小恶魔：今晚你要杀谁？",
        "q_nominate": "你要提名谁吗？选择一名玩家，或者跳过。",
        "q_vote": "举手吗？用{kind}投票处决{t}。（目前{yes}票，需要{needed}票）",
        "your_vote": "你的一票",
        "your_ghost_vote": "你的死人票（只有一次）",
        "q_aside": "私聊时间：你要找人私下聊聊吗？",
        "aside_no": "不了", "aside_one": "和一名玩家私聊", "aside_two": "和两名玩家私聊",
        "q_invite": "你要邀请谁？",
        "q_accept": "{p}想和你私聊{extra}。要加入吗？",
        "together": "（还有{list}）",
    },
}


def role_name(role, lang="en"):
    return ROLE_NAMES.get(lang, ROLE_NAMES["en"]).get(role, role)


def render(m, lang="en", names=()):
    """Turn a message (or argument) into text in `lang`."""
    if isinstance(m, M):
        table = TEXT.get(lang, TEXT["en"])
        tpl = table.get(m.key, TEXT["en"].get(m.key, m.key))
        if isinstance(tpl, list):
            tpl = tpl[m.v % len(tpl)]
        return tpl.format(**{k: render(a, lang, names) for k, a in m.args.items()})
    if isinstance(m, S):
        return names[m.seat]
    if isinstance(m, R):
        return role_name(m.role, lang) if m.role else "—"
    if isinstance(m, AbilityText):
        return ABILITY.get(lang, ABILITY["en"])[m.role]
    if isinstance(m, L):
        items = [render(x, lang, names) for x in m.items]
        sep, last = ("、", "和") if lang == "zh" else (", ", " and ")
        text = sep.join(items[:-1]) + last + items[-1] if m.conj and len(items) > 1 else sep.join(items)
        if m.paren:
            return ("（" + text + "）" if lang == "zh" else " (" + text + ")") if items else ""
        return text
    if m is None:
        return ""
    return str(m)


def roles_reference(lang="en"):
    """Every Trouble Brewing character with team and ability, for the reference panel."""
    from .roles import ALL_ROLES, KIND
    return [{"role": r, "name": role_name(r, lang), "kind": KIND[r], "kind_name": KIND_NAMES[lang][KIND[r]],
             "ability": ABILITY[lang][r]} for r in ALL_ROLES]
