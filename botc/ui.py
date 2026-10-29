"""The page's view of a game: everything the table, log, prompt and notebook need, rendered in
the reader's language. Shared by the local server (web.py) and the in-browser build (browser.py)."""
from .i18n import ABILITY, KIND_NAMES, M, render, role_name, roles_reference
from .roles import KIND

# Each line stays up long enough to read it: a base time plus time per character, scaled by speed.
# "step" waits for a tap after each line instead (the engine asks; see Game.step).
SPEEDS = {"slow": 1.5, "normal": 1.0, "fast": 0.5, "step": 0.0}
BASE = {"lead": 0.5, "speech": 1.0, "event": 1.2, "private": 0.8}
PER_CHAR = {"en": 0.045, "zh": 0.11}


def pacer(session_speed, lang):
    """pace(kind, chars) for a game, reading the session's current speed each time."""
    def pace(kind, chars):
        if session_speed() == "step":
            return 0.3 if kind == "lead" else 0.0
        return min(9.0, BASE[kind] + chars * PER_CHAR.get(lang, 0.06)) * SPEEDS[session_speed()]
    return pace


def roles_payload(lang):
    return {"roles": roles_reference(lang), "note": render(M("first_night_note"), lang)}


def snapshot(g, io, since, lang, speed, error=None):
    if g is None:
        return {"game": None}

    def t(m):
        return render(m, lang, g.names)

    h, over = g.human, g.phase == "over"
    claims = g.pub.claims or (None,) * g.n
    you_evil = h in g.team
    seats = []
    for s in range(g.n):
        role = g.start_roles[s] if over else g.perceived[s] if s == h else g.roles[s] if you_evil and s in g.team else None
        seats.append({
            "seat": s, "name": g.name(s), "you": s == h, "alive": s not in g.dead,
            "ghost": s in g.dead and s not in g.ghosts_used,
            "claim": role_name(claims[s], lang) if claims[s] else None, "claim_key": claims[s],
            "role": role_name(role, lang) if role else None, "role_key": role,
            "evil": (over or you_evil) and s in g.team,
            "history": [t(m) for m in g.history(s)],
        })
    log = []
    for e in g.log[since:]:
        m = e["m"]
        said = m.args.get("text") if m.key == "speech" else None
        log.append({"text": t(m), "private": e["private"], "chat": e["chat"], "speaker": e["speaker"],
                    "key": m.key, "quote": t(said) if said is not None else None,
                    "sub": said.key if hasattr(said, "key") else None})
    prompt = None
    if io.prompt:
        p = dict(io.prompt)
        p["text"] = t(p["text"]) if p.get("text") is not None else None
        if "labels" in p:
            p["labels"] = [t(x) for x in p["labels"]]
        if p.get("title") is not None:
            p["title"] = t(p["title"])
        prompt = p
    me = g.perceived[h]
    return {"game": {
        "seed": g.seed, "players": g.n, "day": g.day, "night": g.night, "phase": g.phase,
        "you": h, "role": role_name(me, lang), "role_key": me, "ability": ABILITY[lang][me],
        "kind": KIND[me], "kind_name": KIND_NAMES[lang][KIND[me]], "evil": you_evil,
        "seats": seats, "log": log, "log_len": len(g.log), "prompt": prompt,
        "notebook": [t(m) for m in g.notebook()], "winner": g.winner, "over": over,
        "speaking": g.speaking, "speed": speed, "error": error,
    }}
