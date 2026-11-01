"""Page copy for a generated site.

template_copy() always works offline. build_copy() asks Claude for unique,
page-specific copy (better for ranking, since city pages that only swap the
town name look like doorway pages to Google) and falls back to the template
for anything it can't get. Needs the `anthropic` package and ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor

MODEL = "claude-opus-5-5"


def _pick(seed: str, options: list):
    return options[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(options)]


def _list(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _reach(d: dict) -> str:
    """How customers get in touch, e.g. 'Call or text (410) 555-0123 or book online'."""
    phone = f"Call or text {d['phone']}" if d["tel"] else ""
    if not d["cta_phrase"]:
        return phone or "Contact us"
    return f"{phone} or {d['cta_phrase']}" if phone else d["cta_phrase"][0].upper() + d["cta_phrase"][1:]


def template_copy(d: dict) -> dict:
    biz, trade, city, region = d["name"], d["trade"], d["city"], d["region"]
    est = d["estimate_label"]
    svc_names = [s["name"] for s in d["services"]]
    area_names = [a["name"] for a in d["areas"]]
    trust = d["trust"]

    home = {
        "kicker": f"{d['industry']} in {region}",
        "headline": d.get("tagline") or f"{d['industry']} Done Right in",
        "accent": "" if d.get("tagline") else f"{city}.",
        "lead": d.get("description") or f"{biz} provides {trade} for homes and businesses across {region}. "
                f"{_reach(d)} and we'll get back to you fast.",
        "intro": f"{biz} is a local {trade} company based in {city}, {d['state']}, serving {region}. "
                 f"We handle {_list([n.lower() for n in svc_names[:4]])} and more. {est} on every job.",
    }

    services = {}
    for s in d["services"]:
        n, nl = s["name"], s["name"].lower()
        price = next((p for p in d["pricing"] if p["item"].lower() in nl or nl in p["item"].lower()), None)
        cost_a = (f"{n} starts at {price['price']}. The final price depends on the size and details of the job, "
                  f"and you'll get a clear quote before any work starts." if price else
                  f"Every job is different, so {nl} is priced on the size and details of the job. "
                  f"{est}: send a few details or photos and we'll give you a clear price before any work starts.")
        services[s["slug"]] = {
            "intro": f"Looking for {nl} in {city}? {biz} provides {nl} across {region}. {s['desc']}".strip(),
            "highlights": [
                {"title": "A clear quote up front",
                 "text": f"You get a straightforward price for your {nl} before we start, based on the details you share."},
                {"title": "Local scheduling",
                 "text": f"We're based in {city} and book {nl} across {region}, with your appointment confirmed ahead of time."},
                {"title": trust[0] if trust else "Careful, tidy work",
                 "text": "We treat your property with care and leave the work area clean when the job is done."},
            ],
            "estimate": f"To get an accurate {nl} quote, tell us what you need, where the job is, and share a photo if you can. "
                        f"We'll reply with a price and the next available times.",
            "faqs": [
                {"q": f"How much does {nl} cost in {city}?", "a": cost_a},
                {"q": f"Do you offer {nl} near me?",
                 "a": f"Yes. {biz} provides {nl} in {city} and nearby areas including {_list(area_names[:4])}."},
                {"q": f"How do I schedule {nl}?",
                 "a": f"{_reach(d)}. We'll confirm a date and time that works for you."},
            ],
        }

    areas = {}
    for a in d["areas"]:
        n = a["name"]
        intro = _pick(n, [
            f"Need {trade} in {n}? {biz} serves homes and businesses throughout {n}, {d['state']}, from our base in {city}.",
            f"{biz} provides {trade} in {n} and the surrounding neighborhoods. {_reach(d)}.",
            f"Local {trade} for {n}, {d['state']}. {biz} handles {_list([x.lower() for x in svc_names[:3]])} and more.",
        ])
        areas[a["slug"]] = {
            "intro": intro,
            "local": [
                f"We schedule {trade} jobs in {n} regularly. When you reach out, include the address, what you need done "
                f"and any access details (gates, parking, stairs) so we can plan the visit and give you an accurate price.",
                f"Popular services in {n} include {_list([x.lower() for x in svc_names[:4]])}. "
                f"{est}, and we confirm your appointment before we arrive.",
            ],
            "faqs": [
                {"q": f"Does {biz} serve {n}?", "a": f"Yes. {n} is part of our regular service area across {region}."},
                {"q": f"How fast can you get to {n}?",
                 "a": f"It depends on the schedule that week. Call or text {d['phone']} and we'll give you the next available time."},
            ],
        }

    about = [d.get("about") or f"{biz} is a locally owned {trade} company based in {city}, {d['state']}.",
             f"We serve {region} and focus on clear pricing, showing up when we say we will, and doing the job right the first time."]
    if d.get("founded"):
        about.append(f"We've been serving the area since {d['founded']}.")

    faqs = d["faqs"] or [
        {"q": f"What areas does {biz} serve?",
         "a": f"We're based in {city}, {d['state']} and serve {region}, including {_list(area_names[:6])}."},
        {"q": f"What services does {biz} offer?", "a": f"We offer {_list([n.lower() for n in svc_names])}."},
        {"q": "How do I get started?", "a": f"{_reach(d)}. {est}."},
        {"q": "What are your hours?", "a": f"We're open {d['hours_text']}."},
    ]
    return {"home": home, "services": services, "areas": areas, "about": about, "faqs": faqs}


# ---------------------------------------------------------------- AI copy

_RULES = (
    "You write website copy for a small local business. Plain, confident, specific language a real owner would use. "
    "Write for people searching Google and asking AI assistants, so lead each answer with the direct answer in the first sentence. "
    "Hard rules: use ONLY the facts given. Never invent reviews, ratings, years in business, licenses, insurance, guarantees, "
    "awards, prices, team size or staff names. No hype words (best, #1, top-rated, premier, unmatched). No em dashes. "
    "Each city's local paragraphs must be genuinely different and describe what jobs there typically involve "
    "(housing types, access, typical requests) in general terms that are true of that town; do not invent landmarks you are unsure of."
)

_FAQ = {"type": "array", "items": {"type": "object", "properties": {"q": {"type": "string"}, "a": {"type": "string"}},
                                     "required": ["q", "a"], "additionalProperties": False}}


def _schema(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _facts(d: dict) -> str:
    keep = {k: d[k] for k in ("name", "industry", "trade", "description", "city", "state", "region", "phone",
                              "hours_text", "estimate_label", "trust", "pricing", "founded", "about", "tagline", "cta_phrase")}
    keep["how_customers_contact"] = _reach(d)
    keep["services"] = [{"name": s["name"], "desc": s["desc"]} for s in d["services"]]
    keep["areas"] = [a["name"] for a in d["areas"]]
    return json.dumps(keep, ensure_ascii=False)


def _ask(client, prompt: str, schema: dict) -> dict:
    resp = client.beta.messages.create(
        model=MODEL, max_tokens=16000, system=_RULES,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
        betas=["server-side-fallback-2026-07-01"], extra_body={"fallbacks": "default"},
    )
    if resp.stop_reason != "end_turn":
        raise RuntimeError(f"stopped: {resp.stop_reason}")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))


def ai_available() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def build_copy(d: dict, use_ai: bool, existing: dict | None = None, log=print) -> dict:
    """Template copy, with AI copy from an earlier build carried over, and (if use_ai)
    Claude writing only the pages that don't have AI copy yet. out["_ai"] records
    which pages are AI-written so the next rebuild doesn't pay for them again."""
    out = template_copy(d)
    done = {"home": False, "services": [], "areas": []}
    old = (existing or {}).get("_ai") or {}
    if old.get("home"):
        out["home"], out["about"], done["home"] = existing["home"], existing["about"], True
        if not d["faqs"]:
            out["faqs"] = existing["faqs"]
    for kind in ("services", "areas"):
        for slug in old.get(kind, []):
            if slug in out[kind] and slug in existing.get(kind, {}):
                out[kind][slug] = existing[kind][slug]
                done[kind].append(slug)
    reused = done["home"] + len(done["services"]) + len(done["areas"])
    if reused:
        log(f"Reusing AI copy already written for {reused} pages (no charge)")
    out["photo_queries"] = dict((existing or {}).get("photo_queries") or {})
    if use_ai:
        _ai_fill(d, out, done, log)
        _photo_queries(d, out["photo_queries"], log)
    out["_ai"] = done
    return out


def _photo_queries(d: dict, queries: dict, log=print) -> None:
    """One small Claude call: a stock-photo search phrase for each service that lacks one."""
    missing = [s for s in d["services"] if s["slug"] not in queries]
    if "_hero" not in queries:  # the home page banner
        missing.append({"slug": "_hero", "name": "Home page banner photo",
                        "desc": f"wide, bright, eye-catching scene that sells {d['trade']}; no text or logos"})
    if not missing:
        return
    import anthropic
    item = _schema({"slug": {"type": "string"}, "query": {"type": "string"}})
    try:
        r = _ask(anthropic.Anthropic(),
                 f"A {d['industry']} business offers these services: "
                 + json.dumps([{"slug": s["slug"], "name": s["name"], "desc": s["desc"]} for s in missing]) +
                 "\n\nFor each, write a 2-4 word stock photo search that finds a photo of the subject itself "
                 "(e.g. 'roof shingles moss' for roof cleaning, 'wooden deck backyard' for deck cleaning). "
                 "Name concrete things a camera sees. Avoid words that match unrelated photos, like 'washing' alone.",
                 _schema({"items": {"type": "array", "items": item}}))
        for it in r["items"]:
            if it["slug"] in {s["slug"] for s in missing} and it["query"].strip():
                queries[it["slug"]] = it["query"].strip()
        log(f"  AI wrote photo searches for {len(missing)} photos")
    except Exception as e:
        log(f"  AI photo searches skipped ({type(e).__name__}: {e})")


def _ai_fill(d: dict, out: dict, done: dict, log=print) -> None:
    """Have Claude write every section not already in done; template copy stays where it fails."""
    import anthropic
    client = anthropic.Anthropic()
    facts = _facts(d)

    def home():
        r = _ask(client, f"Business facts: {facts}\n\nWrite the home page hero and intro, the About page "
                         "(2-3 short paragraphs) and 6 general FAQs.",
                 _schema({"kicker": {"type": "string", "description": "SEO line: '<service> in <region>'"},
                          "headline": {"type": "string", "description": "first part of the hero headline sentence"},
                          "accent": {"type": "string", "description": "the last 2-4 words of that same sentence, shown highlighted. "
                                     "headline + ' ' + accent must read as ONE sentence under 9 words, e.g. headline "
                                     "'A cleaner home,' accent 'without harsh chemicals.'"},
                          "lead": {"type": "string", "description": "1-2 sentences"},
                          "intro": {"type": "string", "description": "2 sentences: who, what, where"},
                          "about": {"type": "array", "items": {"type": "string"}}, "faqs": _FAQ}))
        about, faqs = r.pop("about"), r.pop("faqs")
        out["about"] = about or out["about"]
        if not d["faqs"] and faqs:
            out["faqs"] = faqs
        out["home"].update({k: v for k, v in r.items() if v})
        done["home"] = True

    def service(s):
        r = _ask(client, f"Business facts: {facts}\n\nWrite the service page for: {s['name']}.",
                 _schema({"intro": {"type": "string", "description": "2-3 sentences, direct answer first"},
                          "highlights": {"type": "array", "items": _schema({"title": {"type": "string"}, "text": {"type": "string"}}),
                                         "description": "exactly 3 things this service covers"},
                          "estimate": {"type": "string", "description": "how quotes for this service work, 2 sentences"},
                          "faqs": _FAQ}))
        out["services"][s["slug"]].update({k: v for k, v in r.items() if v})
        done["services"].append(s["slug"])

    def area(a):
        r = _ask(client, f"Business facts: {facts}\n\nWrite the service-area page for {a['name']}, {d['state']}.",
                 _schema({"intro": {"type": "string"},
                          "local": {"type": "array", "items": {"type": "string"}, "description": "2 paragraphs unique to this town"},
                          "faqs": _FAQ}))
        out["areas"][a["slug"]].update({k: v for k, v in r.items() if v})
        done["areas"].append(a["slug"])

    jobs = ([] if done["home"] else [("home page", home, None)]) + \
           [(s["name"], service, s) for s in d["services"] if s["slug"] not in done["services"]] + \
           [(a["name"], area, a) for a in d["areas"] if a["slug"] not in done["areas"]]
    if not jobs:
        return
    log(f"Writing unique copy with Claude for {len(jobs)} pages…")

    def run(job):
        label, fn, arg = job
        try:
            fn(arg) if arg is not None else fn()
            log(f"  AI wrote: {label}")
        except Exception as e:  # keep the template copy for this page
            log(f"  AI skipped {label} ({type(e).__name__}: {e}); using template copy")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(run, jobs))
