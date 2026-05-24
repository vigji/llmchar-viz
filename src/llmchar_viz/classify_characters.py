"""Tag each canonical character on three categorical axes via a cheap LLM, so the
viz can show whether models pick different *kinds* of characters.

  alignment : good | gray | evil | na
  expertise : science | arts_letters | polymath | leadership | other
  nature    : human | artificial | nonhuman | abstract

Reads the character list (+ wiki snippet for disambiguation) from llmchar.db,
classifies in batches via OpenRouter, and writes data/char_specs.json (committed,
so a rebuild is offline). Resumable: only unclassified names are sent.
Run: `uv run python -m llmchar_viz.classify_characters`
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time

import httpx
import json5

from llmchar.config import PROJECT_ROOT, Settings

MODEL = "openai/gpt-5.4-mini"
URL = "https://openrouter.ai/api/v1/chat/completions"
BATCH = 40
COST_CAP = 2.0
OUT = PROJECT_ROOT / "data" / "char_specs.json"

ALIGN = {"good", "gray", "evil", "na"}
ROLE = {"sage_mentor", "thinker_scientist", "creator_artist", "detective",
        "hero_protector", "rebel_revolutionary", "antihero_villain", "trickster",
        "explorer_outsider", "keeper_knowledge", "ruler_leader", "other"}
NATURE = {"human", "artificial", "nonhuman", "abstract"}

SYS = (
    "You label fictional and real characters on three axes. Reply ONLY with a JSON "
    "array, one object per input line, in order, each: "
    '{"name": <verbatim>, "alignment": one of [good,gray,evil,na], '
    '"role": one of [sage_mentor,thinker_scientist,creator_artist,detective,hero_protector,'
    'rebel_revolutionary,antihero_villain,trickster,explorer_outsider,keeper_knowledge,ruler_leader,other], '
    '"nature": one of [human,artificial,nonhuman,abstract]}. '
    "alignment (judge by GENERAL CULTURAL PERCEPTION, not historical biography): "
    "good = ONLY characters culturally seen as clearly virtuous, heroic, or pro-social "
    "(protectors, helpers, moral exemplars) — do NOT mark someone good merely for being famous, "
    "brilliant, or accomplished; "
    "gray = morally ambiguous, antiheroic, rebellious, or controversial; "
    "evil = villainous; "
    "na = everyone else — figures not primarily defined by moral alignment (most scientists, "
    "philosophers, writers, artists, leaders, neutral/ordinary characters, and all abstract concepts). "
    "When unsure between good and na, choose na. "
    "role = the character's primary narrative archetype (pick the single best fit): "
    "sage_mentor=wise guide/teacher (Gandalf, Yoda, Athena); "
    "thinker_scientist=philosopher/scientist/intellectual (Socrates, Einstein, Curie); "
    "creator_artist=writer/artist/inventor/maker (da Vinci, Woolf, Frida Kahlo); "
    "detective=investigator/solver of mysteries (Holmes, Poirot, House); "
    "hero_protector=courageous protector/champion (Samwise, Atticus Finch, Superman); "
    "rebel_revolutionary=fights authority or overturns the order (V, Prometheus, Magneto); "
    "antihero_villain=morally dark, criminal, or villainous (Hannibal Lecter, Walter White, Loki); "
    "trickster=mischievous, cunning, rule-bending (Hermes, Ford Prefect, Lupin); "
    "explorer_outsider=wanderer/adventurer or alienated outsider (Odysseus, Meursault, Gatsby); "
    "keeper_knowledge=librarian/oracle/archive/keeper of information (the Oracle, a Librarian); "
    "ruler_leader=king/politician/commander (Marcus Aurelius, Lincoln); other=none of these. "
    "nature: human=a person (real or fictional human); "
    "artificial=an IN-STORY synthetic/mechanical being — AI, robot, android, software agent, "
    "simulation, golem, automaton (e.g. JARVIS, Data, HAL, Marvin). Being a fictional CREATION does "
    "NOT make a character artificial; "
    "nonhuman=a non-human natural or fantastical being — god, mythological figure, monster, animal, "
    "anthropomorphic/cartoon animal, alien, elf (e.g. Mickey Mouse, Aslan, Loki, Hermes); "
    "abstract=a concept/idea/archetype, not a specific entity."
)


def _coerce(o: dict) -> dict:
    a = str(o.get("alignment", "")).lower().strip()
    r = str(o.get("role", "")).lower().strip()
    n = str(o.get("nature", "")).lower().strip()
    return {
        "alignment": a if a in ALIGN else "na",
        "role": r if r in ROLE else "other",
        "nature": n if n in NATURE else "abstract",
    }


def main() -> int:
    Settings.from_env()
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("OPENROUTER_API_KEY missing")
    db = PROJECT_ROOT / "llmchar.db"
    if not db.is_file():
        sys.exit("llmchar.db not found — run the build first")
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT canonical, substr(COALESCE(wiki_summary,''),1,160) FROM characters "
        "WHERE pick_count > 0 ORDER BY pick_count DESC"
    ).fetchall()

    specs: dict = json.loads(OUT.read_text()) if OUT.is_file() else {}
    todo = [(c, s) for c, s in rows if "role" not in specs.get(c, {})]
    print(f"{len(rows)} characters, {len(todo)} to classify", flush=True)

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    spent = 0.0
    with httpx.Client(timeout=120) as client:
        for i in range(0, len(todo), BATCH):
            if spent >= COST_CAP:
                print(f"[cap] ${spent:.3f}", flush=True)
                break
            batch = todo[i:i + BATCH]
            lines = "\n".join(f"{c}" + (f" — {s}" if s else "") for c, s in batch)
            body = {"model": MODEL, "temperature": 0,
                    "messages": [{"role": "system", "content": SYS},
                                 {"role": "user", "content": lines}],
                    "usage": {"include": True}, "max_tokens": 4000}
            try:
                r = client.post(URL, headers=headers, json=body)
                r.raise_for_status()
                rj = r.json()
                content = rj["choices"][0]["message"]["content"]
                spent += float((rj.get("usage") or {}).get("cost") or 0)
                m = content[content.find("["):content.rfind("]") + 1]
                arr = json5.loads(m)
                for (c, _), o in zip(batch, arr):
                    specs[c] = _coerce(o if isinstance(o, dict) else {})
            except Exception as e:
                print(f"  batch {i} err: {str(e)[:140]}", flush=True)
                time.sleep(2)
                continue
            OUT.write_text(json.dumps(specs, ensure_ascii=False, indent=0))
            print(f"  {min(i+BATCH,len(todo))}/{len(todo)}  ${spent:.3f}", flush=True)

    OUT.write_text(json.dumps(specs, ensure_ascii=False, indent=0))
    print(f"DONE: {len(specs)} classified, spent ${spent:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
