"""The page's view of a game: everything the table, log, prompt and notebook need, rendered in
the reader's language. Shared by the local server (web.py) and the in-browser build (browser.py)."""
from .i18n import ABILITY, KIND_NAMES, M, render, role_name, roles_reference
from .roles import KIND

SPEEDS = {"slow": 1.7, "normal": 1.0, "fast": 0.4, "instant": 0.0}
WAIT = {"speech": 1.4, "event": 1.1, "private": 0.5}  # seconds before a line appears, at normal speed


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
        log.append({"text": t(m), "private": e["private"], "chat": e["chat"], "speaker": e["speaker"],
                    "key": m.key, "quote": t(m.args["text"]) if m.key == "speech" else None})
    prompt = None
    if io.prompt:
        p = dict(io.prompt)
        p["text"] = t(p["text"])
        if "labels" in p:
            p["labels"] = [t(x) for x in p["labels"]]
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
