"""Turn one business's info into a full static website (Cloudflare Pages ready).

Same SEO/AEO setup as kljunkremoval.com: a page per service and per town,
answer-first intros, fact grids, FAQ blocks, JSON-LD (LocalBusiness, Service,
BreadcrumbList, FAQPage), llms.txt, sitemap with lastmod, robots.txt,
canonical + Open Graph tags, and clean /folder/ URLs.

    from sitebuilder.generator import build_site
    build_site(raw_input_dict, out_dir, log=print)
"""
from __future__ import annotations

import html
import json
import re
import shutil
import zipfile
from datetime import date
from pathlib import Path

from . import stock, writer
from .icons import ICONS

HERE = Path(__file__).resolve().parent

# form_type -> (page route, button label, phrase used in copy, verb for CTA headings)
FORM_TYPES = {
    "quote": ("get-a-quote", "Get a Quote", "request a quote online", "Get a quote"),
    "appointment": ("book", "Book Now", "book online", "Book an appointment"),
    "contact": ("contact", "Contact Us", "send us a message online", "Get in touch"),
    "call": ("contact", "Call Now", "", "Give us a call"),
}
PHOTO_WIDTHS = (480, 960, 1600)

DAYS = [("Mo", "Monday", "Mon"), ("Tu", "Tuesday", "Tue"), ("We", "Wednesday", "Wed"), ("Th", "Thursday", "Thu"),
        ("Fr", "Friday", "Fri"), ("Sa", "Saturday", "Sat"), ("Su", "Sunday", "Sun")]

FONTS = {
    "Montserrat": ("Montserrat:wght@600;700;800", False),
    "Oswald": ("Oswald:wght@500;600;700", True),
    "Anton": ("Anton", True),
    "Bebas Neue": ("Bebas+Neue", True),
    "Poppins": ("Poppins:wght@600;700;800", False),
    "Archivo": ("Archivo:wght@600;700;800", False),
    "Playfair Display": ("Playfair+Display:wght@600;700;800", False),
    "DM Serif Display": ("DM+Serif+Display", False),
}
BODY_FONTS = {
    "Inter": "Inter:wght@400;500;600;700",
    "DM Sans": "DM+Sans:wght@400;500;600;700",
    "Lato": "Lato:wght@400;700",
    "Nunito Sans": "Nunito+Sans:wght@400;600;700",
    "Source Sans 3": "Source+Sans+3:wght@400;600;700",
    "Work Sans": "Work+Sans:wght@400;500;600;700",
}

# Look-and-feel choices; the first value is the default. Each becomes a class on <body> (see theme.css).
STYLE_CHOICES = {
    "hero_style": ("photo", "dark", "light", "centered", "split"),
    "corners": ("rounded", "sharp", "soft"),
    "buttons": ("pill", "rounded", "square"),
    "cards": ("border", "shadow", "flat"),
    "header_style": ("light", "dark", "brand"),
    "footer_style": ("dark", "brand", "light"),
    "section_tint": ("gray", "brand", "none"),
    "density": ("normal", "compact", "airy"),
    "service_layout": ("photo", "plain", "list"),
    "head_case": ("auto", "normal", "upper"),
    "page_bg": ("cream", "white"),
    "section_heads": ("center", "left"),
}

# Service and step icons come from sitebuilder/icons.py (Tabler); picked by keywords in the name.
_ICON_WORDS = [  # first match wins, most specific first
    (("detail", "car", "auto", "brake", "oil", "tire", "mechanic", "engine"), "car"),
    (("janitor", "office", "commercial", "business"), "building"),
    (("paint", "stain", "drywall"), "brush"),
    (("lawn", "landscap", "mulch", "leaf", "yard", "tree", "garden", "shrub", "plant", "sod"), "leaf"),
    (("junk", "haul", "move", "moving", "debris", "delivery"), "truck"),
    (("removal", "trash", "dumpster", "cleanout"), "trash"),
    (("recurring", "weekly", "monthly", "schedule", "plan", "maintenance"), "calendar"),
    (("wash", "pressure", "soft", "gutter", "water", "pool", "plumb", "drain"), "drop"),
    (("repair", "handyman", "install", "fix", "assembly", "carpentr"), "tool"),
    (("roof", "house", "home", "deck", "fence", "patio", "driveway", "concrete", "siding"), "home"),
    (("clean", "maid", "sanitiz", "disinfect"), "sparkle"),
]


def icon(name: str, cls: str = "ico") -> str:
    key = name if name in ICONS else next((i for words, i in _ICON_WORDS if any(w in name.lower() for w in words)), "sparkle")
    return (f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[key]}</svg>')

# On/off switches and their defaults.
TOGGLES = {
    "show_trust": True, "show_facts": True, "show_hours_hero": False, "show_testimonials": True, "show_gallery": True,
    "show_town_pages": True, "show_about_page": True, "show_faq_page": True, "show_pricing_page": True,
    "show_breadcrumbs": True, "show_toc": True, "show_related": True, "show_nearby": True, "show_cta_bands": True,
    "show_updated": True, "show_header_phone": True, "show_text_buttons": True, "show_mobile_bar": True,
    "show_social": True, "sms_consent": True, "photo_upload": False, "animations": True,
}


def _bool(v, default: bool) -> bool:
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "on", "yes")


def e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower().replace("&", " and ")).strip("-")


# ---------------------------------------------------------------- input

def _lines(text: str) -> list[str]:
    return [l.strip(" -•\t") for l in (text or "").splitlines() if l.strip(" -•\t")]


def _pairs(text: str, a: str, b: str) -> list[dict]:
    out = []
    for l in _lines(text):
        left, _, right = l.partition("|")
        out.append({a: left.strip(), b: right.strip()})
    return out


def _phone(raw: str) -> tuple[str, str]:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    if len(digits) != 10:
        return raw, "+" + digits if digits else ""
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}", "+1" + digits


def _time(t: str) -> str:
    h, m = (int(x) for x in t.split(":"))
    suffix = "AM" if h < 12 else "PM"
    h = h % 12 or 12
    return f"{h} {suffix}" if m == 0 else f"{h}:{m:02d} {suffix}"


def _days_text(days: list[str]) -> str:
    idx = sorted(i for i, d in enumerate(DAYS) if d[0] in days)
    runs, start = [], None
    for n, i in enumerate(idx):
        if start is None:
            start = i
        if n == len(idx) - 1 or idx[n + 1] != i + 1:
            runs.append(DAYS[start][2] if start == i else f"{DAYS[start][2]}–{DAYS[i][2]}")
            start = None
    return ", ".join(runs)


def normalize(raw: dict) -> dict:
    """Clean the form input into the dict every page builder reads."""
    d = dict(raw)
    d["name"] = raw["name"].strip()
    d["slug"] = raw.get("slug") or slugify(d["name"])
    d["industry"] = raw.get("industry", "").strip() or "Local Services"
    d["trade"] = raw.get("trade", "").strip() or d["industry"].lower()
    d["city"], d["state"] = raw["city"].strip(), raw["state"].strip().upper()
    d["region"] = raw.get("region", "").strip() or f"{d['city']} and nearby areas"
    d["phone"], d["tel"] = _phone(raw.get("phone", ""))
    d["email"] = raw.get("email", "").strip()
    dom = re.sub(r"^https?://", "", raw.get("domain", "").strip()).strip("/") or f"{d['slug']}.pages.dev"
    d["domain"], d["base"] = dom, f"https://{dom}"

    d["services"] = [{"name": s["name"], "desc": s["desc"], "slug": slugify(s["name"])}
                     for s in _pairs(raw.get("services_text", ""), "name", "desc") if s["name"]]
    if not d["services"]:
        raise ValueError("Add at least one service.")
    areas = _lines(raw.get("areas_text", ""))
    if d["city"] not in areas:
        areas.insert(0, d["city"])
    d["areas"] = [{"name": a, "slug": slugify(f"{a} {d['state']}")} for a in areas]
    d["pricing"] = [p for p in _pairs(raw.get("pricing_text", ""), "item", "price") if p["item"]]
    d["faqs"] = [f for f in _pairs(raw.get("faqs_text", ""), "q", "a") if f["q"] and f["a"]]
    d["trust"] = _lines(raw.get("trust_text", ""))[:4]
    d["estimate_label"] = raw.get("estimate_label", "").strip() or "Free estimates"

    d["days"] = raw.get("days") or ["Mo", "Tu", "We", "Th", "Fr"]
    d["opens"], d["closes"] = raw.get("opens") or "08:00", raw.get("closes") or "17:00"
    d["hours_text"] = f"{_days_text(d['days'])}, {_time(d['opens'])}–{_time(d['closes'])}"
    if raw.get("hours_note"):
        d["hours_text"] += f" ({raw['hours_note'].strip()})"

    d["primary"] = raw.get("primary") or "#1f6feb"
    d["accent"] = raw.get("accent") or d["primary"]
    d["dark"] = raw.get("dark") or _mix(d["primary"], "#0e1013", 0.86)
    d["font_head"] = raw.get("font_head") if raw.get("font_head") in FONTS else "Montserrat"
    d["schema_type"] = raw.get("schema_type") or "LocalBusiness"
    d["form_type"] = raw.get("form_type") if raw.get("form_type") in FORM_TYPES else "quote"
    if d["form_type"] == "call" and not d["tel"]:
        d["form_type"] = "contact"
    d["cta_route"], d["cta_label"], d["cta_phrase"], d["cta_verb"] = FORM_TYPES[d["form_type"]]
    d["opt"] = {k: _bool(raw.get(k), default) for k, default in TOGGLES.items()}
    d["style"] = {k: raw.get(k) if raw.get(k) in choices else choices[0] for k, choices in STYLE_CHOICES.items()}
    d["body_font"] = raw.get("body_font") if raw.get("body_font") in BODY_FONTS else "DM Sans"
    d["testimonials"] = [t for t in _pairs(raw.get("testimonials_text", ""), "name", "quote") if t["name"] and t["quote"]]
    d["announcement"] = (raw.get("announcement") or "").strip()
    # Optional extra sections. Typed values only: nothing here is ever made up.
    d["stats"] = [s for s in _pairs(raw.get("stats_text", ""), "value", "label") if s["value"] and s["label"]][:4]
    d["badges"] = _lines(raw.get("badges_text", ""))[:6]
    d["about_points"] = _lines(raw.get("about_points_text", ""))[:6]
    d["process"] = [p for p in _pairs(raw.get("process_text", ""), "title", "text") if p["title"]][:4]
    d["ba_caption"] = (raw.get("ba_caption") or "").strip()
    d["photo_upload"] = d["opt"]["photo_upload"] and d["form_type"] in ("quote", "appointment")
    d["form_endpoint"] = (raw.get("form_endpoint") or "").strip()
    d["formsubmit"] = "formsubmit.co/" in d["form_endpoint"]
    d["socials"] = {k: raw.get(k, "").strip() for k in ("google", "facebook", "instagram", "yelp", "nextdoor")
                    if raw.get(k, "").strip()}
    d["today"] = date.today()
    return d


# ---------------------------------------------------------------- colors

def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _mix(a: str, b: str, t: float) -> str:
    return _hex([x + (y - x) * t for x, y in zip(_rgb(a), _rgb(b))])


def _lum(h: str) -> float:
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ink(bg: str) -> str:
    """Black or white text, whichever reads better on bg."""
    return "#111316" if _lum(bg) > 0.36 else "#ffffff"


def _readable_on_white(c: str) -> str:
    """Darken a brand color until it passes 4.5:1 on white (for links/accents in body text)."""
    for _ in range(20):
        if (1.05) / (_lum(c) + 0.05) >= 4.5:
            return c
        c = _mix(c, "#000000", 0.12)
    return c


# ---------------------------------------------------------------- page shell

class Site:
    def __init__(self, d: dict, copy: dict, assets: dict):
        self.d, self.c, self.a = d, copy, assets
        self.o = d["opt"]                 # on/off switches from the builder
        self.preload = ""                 # home page hero image preload tag
        self.pages: dict[str, str] = {}   # route ("" = home) -> html

    def url(self, route: str) -> str:
        return f"{self.d['base']}/{route + '/' if route else ''}"

    def reach(self, plain: bool = False) -> str:
        """'Call or text X or <book online>' sentence for this business's contact options."""
        d = self.d
        phone = f"Call or text {d['phone']}" if d["tel"] else ""
        if not d["cta_phrase"]:
            return phone or "Contact us"
        link = d["cta_phrase"] if plain else f'<a href="{self.cta_href}">{e(d["cta_phrase"])}</a>'
        return f"{e(phone)} or {link}" if phone else link[0].upper() + link[1:]

    @property
    def cta_href(self) -> str:
        return f"tel:{self.d['tel']}" if self.d["form_type"] == "call" else f"/{self.d['cta_route']}/"

    def cta_btn(self, label: str | None = None, cls: str = "btn btn-accent", arrow: bool = False) -> str:
        arr = icon("arrow", "arr") if arrow else ""
        return f'<a class="{cls}" href="{self.cta_href}">{e(label or self.d["cta_label"])}{arr}</a>'

    def img(self, p: dict, alt: str, sizes: str = "(max-width: 760px) 100vw, 50vw", eager: bool = False) -> str:
        srcset = ", ".join(f"/assets/{p['name']}-{w}.webp {w}w" for w, _, _ in p["sizes"])
        mid = p["sizes"][min(1, len(p["sizes"]) - 1)]
        _, w, h = p["sizes"][-1]
        load = 'fetchpriority="high"' if eager else 'loading="lazy"'
        return (f'<img src="/assets/{p["name"]}-{mid[0]}.webp" srcset="{srcset}" sizes="{sizes}" width="{w}" height="{h}" '
                f'alt="{e(alt)}" {load} decoding="async">')

    def svc_photo(self, s: dict, sizes: str, eager: bool = False) -> str:
        """Service photo (real or stock), or a brand-colored panel when there's neither."""
        ph = self.a["svc"].get(s["slug"])
        if not ph:
            return f'<div class="ph" aria-hidden="true"><span>{e(s["name"][:1])}</span></div>'
        alt = s["name"] if ph["stock"] else f"{s['name']} in {self.d['city']}, {self.d['state']}"
        return self.img(ph["photo"], alt, sizes, eager)

    def gallery(self, photos: list, title: str) -> str:
        if not photos or not self.o["show_gallery"]:
            return ""
        d = self.d
        figs = "".join(f'<figure>{self.img(p, f"{d["industry"]} job by {d["name"]} in {d["city"]}, {d["state"]}", "(max-width: 760px) 50vw, 33vw")}</figure>'
                       for p in photos)
        return (f'<section class="sec" id="gallery"><div class="wrap">{self.sec_head(e(title))}'
                f'<div class="gallery">{figs}</div></div></section>')

    # JSON-LD building blocks ------------------------------------------
    def business(self) -> dict:
        d = self.d
        biz = {"@type": d["schema_type"], "@id": f"{d['base']}/#business", "name": d["name"], "url": self.url(""),
               "description": self.c["home"]["intro"],
               "areaServed": [{"@type": "City", "name": f"{a['name']}, {d['state']}"} for a in d["areas"]],
               "openingHoursSpecification": [{"@type": "OpeningHoursSpecification",
                                              "dayOfWeek": [full for code, full, _ in DAYS if code in d["days"]],
                                              "opens": d["opens"], "closes": d["closes"]}],
               "hasOfferCatalog": {"@type": "OfferCatalog", "name": f"{d['industry']} services",
                                   "itemListElement": [{"@type": "Offer", "itemOffered": {
                                       "@type": "Service", "name": s["name"], "url": self.url(f"services/{s['slug']}")}}
                                       for s in d["services"]]},
               "knowsAbout": [d["industry"]] + [s["name"] for s in d["services"]][:8]}
        if d["tel"]:
            biz["telephone"] = d["tel"]
        if d["email"]:
            biz["email"] = d["email"]
        if self.a.get("logo"):
            biz["logo"] = biz["image"] = f"{d['base']}/assets/{self.a['logo']}"
        addr = {"@type": "PostalAddress", "addressLocality": d["city"], "addressRegion": d["state"], "addressCountry": "US"}
        if d.get("street"):
            addr["streetAddress"] = d["street"]
        if d.get("zip"):
            addr["postalCode"] = d["zip"]
        biz["address"] = addr
        if d["socials"]:
            biz["sameAs"] = list(d["socials"].values())
        if d["socials"].get("google"):
            biz["hasMap"] = d["socials"]["google"]
        if d["pricing"]:
            biz["priceRange"] = "$$"
        return biz

    def webpage(self, route, title, desc) -> dict:
        return {"@type": "WebPage", "@id": self.url(route) + "#webpage", "url": self.url(route), "name": title,
                "description": desc, "isPartOf": {"@id": f"{self.d['base']}/#website"},
                "about": {"@id": f"{self.d['base']}/#business"}, "dateModified": self.d["today"].isoformat()}

    def crumbs_ld(self, crumbs) -> dict:
        return {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": self.url(r)} for i, (n, r) in enumerate(crumbs)]}

    @staticmethod
    def faq_ld(faqs) -> dict:
        return {"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faqs]}

    # HTML pieces ---------------------------------------------------------
    def nav(self, active: str) -> str:
        d = self.d
        # Desktop nav stays short (the logo is Home, the button is the main action); the phone menu adds Contact.
        items = [("Services", "services"), ("Areas", "service-areas")]
        if d["pricing"] and self.o["show_pricing_page"]:
            items.append(("Pricing", "pricing"))
        if self.o["show_about_page"]:
            items.append(("About", "about"))
        if self.o["show_faq_page"]:
            items.append(("FAQ", "faq"))
        drop = "".join(f'<a href="/services/{s["slug"]}/">{e(s["name"])}</a>' for s in d["services"])
        li = []
        for name, r in items:
            cls = ' aria-current="page"' if r == active else ""
            if r == "services":
                li.append(f'<li class="has-drop"><a href="/services/"{cls}>Services</a><div class="drop">{drop}</div></li>')
            else:
                li.append(f'<li><a href="/{r + "/" if r else ""}"{cls}>{name}</a></li>')
        mobile = "".join(f'<a href="/{r + "/" if r else ""}">{n}</a>' for n, r in [("Home", "")] + items + [("Contact", "contact")])
        brand = (f'<img src="/assets/{self.a["logo"]}" alt="{e(d["name"])}" width="{self.a["logo_w"]}" height="{self.a["logo_h"]}">'
                 if self.a.get("logo") else f'<span class="wordmark">{e(d["name"])}</span>')
        call = f'<a class="btn btn-ghost" href="tel:{d["tel"]}">Call {e(d["phone"])}</a>' if d["tel"] else ""
        return (f'<a class="skip" href="#main">Skip to content</a>'
                f'<header class="hdr"><div class="wrap hdr-in"><a class="brand" href="/" aria-label="{e(d["name"])} home">{brand}</a>'
                f'<nav aria-label="Main"><ul class="nav">{"".join(li)}</ul></nav>'
                f'<div class="hdr-cta">{call if d["form_type"] != "call" and self.o["show_header_phone"] else ""}{self.cta_btn()}</div>'
                f'<button class="burger" aria-label="Open menu" aria-expanded="false" aria-controls="mnav"><span></span><span></span><span></span></button></div>'
                f'<div class="mnav" id="mnav" hidden>{mobile}{self.cta_btn()}</div></header>')

    def footer(self) -> str:
        d = self.d
        svc = "".join(f'<li><a href="/services/{s["slug"]}/">{e(s["name"])}</a></li>' for s in d["services"][:8])
        areas = "".join(f'<li><a href="/service-areas/{a["slug"]}/">{e(a["name"])}</a></li>' if self.o["show_town_pages"]
                        else f'<li>{e(a["name"])}</li>' for a in d["areas"][:8])
        soc_names = {"google": "Google", "facebook": "Facebook", "instagram": "Instagram", "yelp": "Yelp", "nextdoor": "Nextdoor"}
        soc = "".join(f'<a href="{e(u)}" target="_blank" rel="noopener">{soc_names[k]}</a>' for k, u in d["socials"].items()
                      ) if self.o["show_social"] else ""
        texting = self.o["show_text_buttons"]
        contact = []
        if d["tel"]:
            contact.append(f'<li><a href="tel:{d["tel"]}">{e(d["phone"])}</a></li>')
            if texting:
                contact.append(f'<li><a href="sms:{d["tel"]}">Text us</a></li>')
        if d["email"]:
            contact.append(f'<li><a href="mailto:{e(d["email"])}">{e(d["email"])}</a></li>')
        addr = e(d.get("street") + ", " if d.get("street") else "") + f'{e(d["city"])}, {e(d["state"])} {e(d.get("zip", ""))}'
        return (f'<footer class="ftr"><div class="wrap ftr-grid">'
                f'<div><p class="ftr-name">{e(d["name"])}</p><p>{e(d["industry"])} serving {e(d["region"])}.</p>'
                f'<p class="muted">{addr}</p><div class="soc">{soc}</div></div>'
                f'<div><h2>Services</h2><ul>{svc}<li><a href="/services/">All services</a></li></ul></div>'
                f'<div><h2>Service Areas</h2><ul>{areas}<li><a href="/service-areas/">All areas</a></li></ul></div>'
                f'<div><h2>Contact</h2><ul>{"".join(contact)}<li>{e(d["hours_text"])}</li></ul></div></div>'
                f'<div class="wrap ftr-bot"><span>© {d["today"].year} {e(d["name"])}</span>'
                f'<span><a href="/privacy-policy/">Privacy Policy</a> · <a href="/terms/">Terms</a></span></div></footer>'
                + (f'<div class="mbar{"" if texting else " no-text"}"><a href="tel:{d["tel"]}">Call</a>'
                   + (f'<a href="sms:{d["tel"]}">Text</a>' if texting else "")
                   + (f'<a class="q" href="/contact/">Contact</a>' if d["form_type"] == "call" else
                      f'<a class="q" href="{self.cta_href}">{e(d["cta_label"])}</a>') + '</div>'
                   if d["tel"] and self.o["show_mobile_bar"] else ""))

    def body_classes(self) -> str:
        cls = [f"{k.split('_')[0]}-{v}" for k, v in self.d["style"].items()]
        if self.o["animations"]:
            cls.append("anim")
        return " ".join(cls)

    def page(self, route: str, title: str, desc: str, body: str, ld: list, active: str = "", robots="index,follow"):
        d = self.d
        fam, _ = FONTS[d["font_head"]]
        canonical = self.url(route)
        graph = {"@context": "https://schema.org", "@graph": ld}
        og_img = f'{d["base"]}/assets/og.png'
        ga = (f'<script async src="https://www.googletagmanager.com/gtag/js?id={e(d["ga_id"])}"></script>'
              f'<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}'
              f'gtag("js",new Date());gtag("config","{e(d["ga_id"])}");</script>' if d.get("ga_id") else "")
        self.pages[route] = f"""<!DOCTYPE html>
<html lang="en">
<head>
{ga}<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<meta name="robots" content="{robots},max-image-preview:large,max-snippet:-1">
<meta name="theme-color" content="{d['dark']}">
<link rel="canonical" href="{canonical}">
<link rel="icon" href="/favicon.png" type="image/png">
<link rel="shortcut icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/favicon.png">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{e(d['name'])}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{og_img}">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family={fam}&family={BODY_FONTS[d['body_font']]}&display=swap">
<link rel="stylesheet" href="/assets/site.css?v={d['asset_v']}">
{self.preload if route == "" else ""}
<script type="application/ld+json">{json.dumps(graph, ensure_ascii=False)}</script>
</head>
<body class="{self.body_classes()}">
{f'<div class="announce">{e(d["announcement"])}</div>' if d["announcement"] else ""}
{self.nav(active)}
<main id="main">
{body}
</main>
{self.footer()}
<script src="/assets/site.js?v={d['asset_v']}" defer></script>
</body>
</html>
"""

    # Reusable sections ----------------------------------------------------
    def crumbs_html(self, crumbs) -> str:
        if not self.o["show_breadcrumbs"]:
            return ""
        parts = [f'<a href="/{r + "/" if r else ""}">{e(n)}</a>' for n, r in crumbs[:-1]] + [f'<span>{e(crumbs[-1][0])}</span>']
        return f'<nav class="crumbs" aria-label="Breadcrumb">{"<i>/</i>".join(parts)}</nav>'

    def facts(self, area: str | None = None, price: str | None = None) -> str:
        if not self.o["show_facts"]:
            return ""
        d = self.d
        rows = [("Service", d["industry"]), ("Service area", area or d["region"]),
                ("Estimates", price or d["estimate_label"]), ("Hours", d["hours_text"])]
        if d["tel"]:
            rows.append(("Call or text", f'<a href="tel:{d["tel"]}">{e(d["phone"])}</a>'))
        cells = "".join(f'<div><dt>{k}</dt><dd>{v if k == "Call or text" else e(v)}</dd></div>' for k, v in rows)
        return f'<dl class="facts">{cells}</dl>'

    def faq_html(self, faqs, title="Common Questions") -> str:
        items = "".join(f'<details><summary>{e(f["q"])}</summary><p>{e(f["a"])}</p></details>' for f in faqs)
        return (f'<section class="sec" id="faq"><div class="wrap narrow">{self.sec_head(e(title))}'
                f'<div class="faq">{items}</div></div></section>')

    def cta(self, heading: str, text: str) -> str:
        d = self.d
        if not self.o["show_cta_bands"]:
            return ""
        if d["form_type"] == "call":
            btns = self.cta_btn(f"Call {d['phone']}") + (
                f'<a class="btn btn-light" href="sms:{d["tel"]}">Text us</a>' if self.o["show_text_buttons"] else "")
        else:
            btns = self.cta_btn() + (f'<a class="btn btn-light" href="tel:{d["tel"]}">Call {e(d["phone"])}</a>' if d["tel"] else "")
        return (f'<section class="cta"><div class="wrap cta-in"><div><h2>{e(heading)}</h2><p>{e(text)}</p></div>'
                f'<div class="cta-btns">{btns}</div></div></section>')

    def updated(self) -> str:
        if not self.o["show_updated"]:
            return ""
        t = self.d["today"]
        return f'<p class="updated">Last updated {t.strftime("%B")} {t.day}, {t.year}</p>'

    def service_cards(self, suffix: str = "") -> str:
        cards = "".join(
            f'<a class="card has-img" href="/services/{s["slug"]}/"><div class="card-img">'
            f'{self.svc_photo(s, "(max-width: 600px) 100vw, (max-width: 1100px) 50vw, 380px")}</div>'
            f'<div class="card-body"><span class="card-ico">{icon(s["name"])}</span><h3>{e(s["name"])}{e(suffix)}</h3>'
            f'<p>{e(s["desc"] or self.c["services"][s["slug"]]["intro"][:140])}</p><span class="more">Learn more →</span></div></a>'
            for s in self.d["services"])
        return f'<div class="cards">{cards}</div>'

    def area_chips(self, areas=None) -> str:
        areas = areas or self.d["areas"]
        if not self.o["show_town_pages"]:  # no per-town pages: list the towns without links
            return '<div class="chips">' + "".join(f'<span>{e(a["name"])}</span>' for a in areas) + "</div>"
        return '<div class="chips">' + "".join(
            f'<a href="/service-areas/{a["slug"]}/">{e(a["name"])}</a>' for a in areas) + "</div>"

    def testimonials(self) -> str:
        """Real customer quotes typed into the builder. No review schema: Google ignores self-posted reviews."""
        t = self.d["testimonials"]
        if not t or not self.o["show_testimonials"]:
            return ""
        cards = "".join(f'<figure class="quote"><blockquote>“{e(x["quote"])}”</blockquote><figcaption>{e(x["name"])}</figcaption></figure>'
                        for x in t[:6])
        return (f'<section class="sec"><div class="wrap">{self.sec_head("What customers say")}'
                f'<div class="quotes">{cards}</div></div></section>')

    def quote_form(self) -> str:
        """The lead form for this business's form type (quote, appointment or contact)."""
        d, kind = self.d, self.d["form_type"]
        if kind == "call":
            text = f'<a class="btn btn-light" href="sms:{d["tel"]}">Text {e(d["phone"])}</a>'
            return (f'<div class="callbox"><h2>Call or text us</h2><p>The fastest way to reach {e(d["name"])}.</p>'
                    f'{self.cta_btn("Call " + d["phone"], "btn btn-accent btn-block")}{text}'
                    f'<p class="muted">{e(d["hours_text"])}</p></div>')
        opts = "".join(f'<option>{e(s["name"])}</option>' for s in d["services"]) + "<option>Something else</option>"
        endpoint = e(d["form_endpoint"])
        key = f'<input type="hidden" name="access_key" value="{e(d["form_key"])}">' if d.get("form_key") else ""
        if d["formsubmit"]:  # FormSubmit emails the request (photos attached), then sends the visitor to /thank-you/
            key += (f'<input type="hidden" name="_next" value="{d["base"]}/thank-you/">'
                    '<input type="hidden" name="_template" value="table">')
        photos = ""
        if d["photo_upload"]:
            what = "the space" if kind == "quote" else "what you need done"
            photos = (f'<div class="photo-up"><label class="photo-drop"><input type="file" name="attachment" accept="image/*" multiple>'
                      f'<span class="photo-ico" aria-hidden="true">📷</span><span><b>Add photos of {what}</b>'
                      '<small>Optional, up to 6. Photos get you the most accurate price.</small></span></label>'
                      '<div class="photo-thumbs" aria-live="polite"></div></div>')
        about = {"quote": "my quote and appointment", "appointment": "my appointment", "contact": "my inquiry"}[kind]
        consent = (f'<label class="check"><input type="checkbox" name="sms_consent" value="yes"><span>I agree to receive '
                   f'text messages from {e(d["name"])} about {about}. Message and data rates may apply. '
                   f'Reply STOP to opt out. Consent is not a condition of purchase. See our <a href="/privacy-policy/">Privacy Policy</a>.</span></label>'
                   ) if self.o["sms_consent"] else ""
        name_phone = ('<div class="row2"><label>Name<input name="name" autocomplete="name" required></label>'
                      '<label>Phone<input name="phone" type="tel" autocomplete="tel" inputmode="tel" required></label></div>')
        service = f'<label>Service<select name="service">{opts}</select></label>'
        if kind == "quote":
            subject, button = "New quote request from your website", "Send My Quote Request"
            fields = (f'{name_phone}<div class="row2"><label>Email <small>(optional)</small><input name="email" type="email" autocomplete="email"></label>'
                      f'{service}</div><label>Address or town<input name="address" autocomplete="street-address"></label>'
                      '<label>What do you need done?<textarea name="message" rows="4"></textarea></label>')
        elif kind == "appointment":
            subject, button = "New appointment request from your website", "Request Appointment"
            fields = (f'{name_phone}{service}<div class="row2"><label>Preferred day<input name="date" type="date" required></label>'
                      '<label>Preferred time<select name="time"><option>Morning</option><option>Afternoon</option>'
                      '<option>Evening</option><option>Any time</option></select></label></div>'
                      '<label>Anything we should know? <small>(optional)</small><textarea name="message" rows="3"></textarea></label>')
        else:
            subject, button = "New message from your website", "Send Message"
            fields = (f'{name_phone}<label>Email<input name="email" type="email" autocomplete="email" required></label>'
                      '<label>How can we help?<textarea name="message" rows="5" required></textarea></label>')
        native = f' action="{endpoint}" method="POST" enctype="multipart/form-data"' if d["formsubmit"] else ""
        return f"""<form class="qform"{native} data-endpoint="{endpoint}" data-native="{'1' if d['formsubmit'] else ''}" data-tel="{d['tel']}" data-email="{e(d['email'])}" data-biz="{e(d['name'])}" novalidate>
{key}<input type="hidden" name="subject" value="{subject}"><input type="hidden" name="_subject" value="{subject}">
{fields}
{photos}
{consent}
<input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">
<button class="btn btn-accent btn-block" type="submit">{button}</button>
<p class="fstatus" role="status" aria-live="polite"></p>
</form>"""

    # Home page sections ------------------------------------------------
    @staticmethod
    def sec_head(title: str, sub: str = "", eyebrow: str = "") -> str:
        eb = f'<p class="eyebrow">{e(eyebrow)}</p>' if eyebrow else ""
        return f'<header class="shead">{eb}<h2>{title}</h2>{f"<p>{sub}</p>" if sub else ""}</header>'

    def stats_items(self) -> list[tuple[str, str]]:
        """Typed stats, else true numbers from what was entered (never invented)."""
        d = self.d
        if d["stats"]:
            return [(s["value"], s["label"]) for s in d["stats"]]
        items = [(str(len(d["services"])), "Services offered" if len(d["services"]) > 1 else "Service offered"),
                 (str(len(d["areas"])), "Towns served" if len(d["areas"]) > 1 else "Town served"),
                 (f'{len(d["days"])} days', "A week")]
        est = d["estimate_label"]
        items.append(("Free", "Estimates") if est.lower().startswith("free") else ("Local", f'{d["city"]}-based'))
        return items

    def stats_bar(self) -> str:
        cells = "".join(f'<div><b>{e(v)}</b><span>{e(l)}</span></div>' for v, l in self.stats_items())
        return f'<div class="stats" role="list">{cells}</div>'

    def badges_row(self, trust: list[str]) -> str:
        if not self.o["show_trust"]:
            return ""
        items = self.d["badges"] or trust
        cells = "".join(f'<li>{icon("check", "bi")}{e(t)}</li>' for t in items)
        return (f'<section class="badges"><div class="wrap"><p class="badges-cap">Trusted across {e(self.d["region"])}</p>'
                f'<ul>{cells}</ul></div></section>')

    def process(self) -> str:
        d = self.d
        steps = d["process"] or {
            "quote": [("Tell us about the job", "Send a few details and photos online, or call or text."),
                      ("Get a clear price", f"{d['estimate_label']}. You know the cost before any work starts."),
                      ("We do the work", "We show up when we say we will and take care of everything."),
                      ("Enjoy the results", "You get the finished job and a clean space, nothing left behind.")],
            "appointment": [("Pick a time", "Choose a service and a day that works for you."),
                            ("We confirm", "We confirm your appointment by text or call."),
                            ("We show up", "Right on time, ready to work."),
                            ("You're all set", "Book your next visit whenever you need us.")],
        }.get(d["form_type"], [("Reach out", "Call, text or send a message."),
                               ("We talk it through", "We listen, answer questions and explain your options."),
                               ("We get to work", "Clear next steps and no surprises."),
                               ("You're taken care of", "We follow up to make sure you're happy.")])
        steps = [(s["title"], s["text"]) if isinstance(s, dict) else s for s in steps]
        icons = ["chat", "price", "tool", "star"]
        cards = "".join(f'<li><span class="step-ico">{icon(icons[i % 4], "si")}</span><h3>{e(t)}</h3><p>{e(x)}</p></li>'
                        for i, (t, x) in enumerate(steps))
        return (f'<section class="sec"><div class="wrap">{self.sec_head("How it works", "Simple from first call to finished job.", "Our process")}'
                f'<ol class="steps">{cards}</ol></div></section>')

    def about_band(self, trust: list[str]) -> str:
        d, a = self.d, self.a
        photo = ""
        if a.get("about"):
            photo = self.img(a["about"], f"{d['name']} in {d['city']}, {d['state']}", "(max-width: 900px) 100vw, 560px")
        elif a["gallery"]:
            photo = self.img(a["gallery"][0], f"{d['industry']} job by {d['name']}", "(max-width: 900px) 100vw, 560px")
        elif a.get("hero"):
            photo = f'<img src="/assets/{a["hero"]}" alt="{e(d["industry"])} by {e(d["name"])}" loading="lazy" decoding="async">'
        elif len(d["services"]) > 1 and a["svc"].get(d["services"][1]["slug"]):
            photo = self.svc_photo(d["services"][1], "(max-width: 900px) 100vw, 560px")
        points = d["about_points"] or trust
        paras = "".join(f"<p>{e(p)}</p>" for p in self.c["about"][:2])
        checks = "".join(f'<li>{icon("check", "ci")}{e(p)}</li>' for p in points[:4])
        media = f'<figure class="about-media">{photo}</figure>' if photo else ""
        return (f'<section class="about-band{" no-media" if not photo else ""}"><div class="wrap about-grid">{media}'
                f'<div class="about-copy"><p class="eyebrow">About {e(d["name"])}</p><h2>Local to {e(d["city"])}.<br>Focused on you.</h2>'
                f'{paras}<ul class="checks">{checks}</ul>{self.cta_btn(arrow=True)}</div></div></section>')

    def before_after(self) -> str:
        a, d = self.a, self.d
        if not (a.get("before") and a.get("after")):
            return ""
        cap = f'<p class="ba-cap">{e(d["ba_caption"])}</p>' if d["ba_caption"] else ""
        b = self.img(a["before"], "Before", "(max-width: 900px) 100vw, 900px")
        af = self.img(a["after"], "After", "(max-width: 900px) 100vw, 900px")
        return (f'<section class="sec" id="work"><div class="wrap">{self.sec_head("Before &amp; after", "Drag the slider to see the difference.")}'
                f'<div class="ba" style="--pos:50%"><div class="ba-after">{af}</div><div class="ba-before">{b}</div>'
                f'<span class="ba-tag l">Before</span><span class="ba-tag r">After</span><span class="ba-line" aria-hidden="true"></span>'
                f'<input type="range" min="0" max="100" value="50" aria-label="Before and after slider"></div>{cap}</div></section>')

    # Pages -------------------------------------------------------------
    def build_home(self):
        d, h = self.d, self.c["home"]
        trust = d["trust"] or [d["estimate_label"], "Local & owner-operated", f"Serving {d['region']}", "Call or text"]
        hero_bg = f' style="--hero-img:url(/assets/{self.a["hero"]})"' if self.a.get("hero") else ""
        if d["form_type"] == "call":
            call = self.cta_btn(f"Call {d['phone']}") + (
                f'<a class="btn btn-light" href="sms:{d["tel"]}">Text us</a>' if self.o["show_text_buttons"] else "")
        else:
            label = {"quote": f"Get a {d['estimate_label'].split()[0]} Quote" if d["estimate_label"].lower().startswith("free")
                     else "Get a Quote", "appointment": "Book an Appointment", "contact": "Contact Us"}[d["form_type"]]
            call = self.cta_btn(label, arrow=True) + (f'<a class="btn btn-light" href="tel:{d["tel"]}">{icon("phone", "arr")}Call {e(d["phone"])}</a>' if d["tel"] else "")
        accent = f' <span class="hl">{e(h["accent"])}</span>' if h.get("accent") else ""
        split = d["style"]["hero_style"] == "split"
        media = ""
        if split:  # photo beside the headline: their hero photo, else the first service photo, else a brand panel
            if self.a.get("hero"):
                media = f'<img src="/assets/{self.a["hero"]}" alt="{e(d["name"])}" fetchpriority="high">'
            else:
                media = self.svc_photo(d["services"][0], "(max-width: 860px) 100vw, 560px", eager=True)
            media = f'<div class="hero-media">{media}</div>'
        img_cls = " has-img" if self.a.get("hero") and not split else ""
        if img_cls:  # preload the background photo so the first screen paints fast (LCP)
            self.preload = f'<link rel="preload" as="image" href="/assets/{self.a["hero"]}" fetchpriority="high">'
        meta = f'<p class="hero-meta">{e(d["hours_text"])}</p>' if self.o["show_hours_hero"] else ""
        trust_html = (f'<section class="trust"><div class="wrap trust-in">{"".join(f"<span>{e(t)}</span>" for t in trust)}</div></section>'
                      if self.o["show_trust"] else "")
        del trust_html  # the trust strip is now the badges row below the hero
        body = f"""<section class="hero{img_cls}"{hero_bg if img_cls else ""}><div class="wrap hero-grid"><div class="hero-copy">
<h1><span class="kicker">{e(h['kicker'])}</span>{e(h['headline'])}{accent}</h1>
<p class="lead">{e(h['lead'])}</p>
<div class="hero-btns">{call}</div>
{meta}</div>{media}</div>
<div class="wrap hero-stats">{self.stats_bar()}</div></section>
{self.badges_row(trust)}
<section class="sec alt" id="services"><div class="wrap">{self.sec_head(f"{e(d['industry'])} services, start to finish", f"Everything {e(d['name'])} does, across {e(d['region'])}.", "What we do")}{self.service_cards()}</div></section>
{self.about_band(trust)}
{self.process()}
{self.before_after()}
{self.testimonials()}
{self.gallery(self.a['gallery'][:9], "Recent work")}
<section class="sec alt"><div class="wrap">{self.sec_head(f"Serving {e(d['region'])}", e(h['intro']) + (" Choose your town for local details." if self.o["show_town_pages"] else ""))}
{self.area_chips()}{self.facts()}</div></section>
{self.faq_html(self.c['faqs'][:6], f"{d['industry']} questions")}
{self.cta(f"Ready to {d['cta_verb'][0].lower() + d['cta_verb'][1:]}?", f"Tell us what you need and we'll get right back to you. {d['estimate_label']}.")}"""
        title = f"{d['industry']} in {d['city']}, {d['state']} | {d['name']}"
        desc = f"{d['name']} provides {d['trade']} in {d['region']}. {d['estimate_label']}. {self.reach(plain=True)}."
        biz = self.business()
        if self.a["gallery"]:
            biz["image"] = [f"{d['base']}/assets/{p['name']}-{p['sizes'][-1][0]}.webp" for p in self.a["gallery"][:6]]
        ld = [{"@type": "WebSite", "@id": f"{d['base']}/#website", "url": self.url(""), "name": d["name"],
               "publisher": {"@id": f"{d['base']}/#business"}},
              self.webpage("", title, desc), biz, self.faq_ld(self.c["faqs"][:6])]
        self.page("", title[:70], desc[:160], body, ld, active="")

    def build_services(self):
        d = self.d
        crumbs = [("Home", ""), ("Services", "services")]
        body = (f'<section class="phero"><div class="wrap">{self.crumbs_html(crumbs)}<h1>{e(d["industry"])} Services</h1>'
                f'<p>Everything {e(d["name"])} offers across {e(d["region"])}.</p></div></section>'
                f'<section class="sec"><div class="wrap">{self.service_cards()}{self.updated()}</div></section>'
                + self.cta("Not sure which service you need?", "Call or text and describe the job. We'll point you in the right direction."))
        title, desc = f"{d['industry']} Services | {d['name']}", f"All {d['trade']} services from {d['name']} in {d['region']}."
        self.page("services", title, desc, body, [self.webpage("services", title, desc), self.crumbs_ld(crumbs)], "services")

        for s in d["services"]:
            c = self.c["services"][s["slug"]]
            route = f"services/{s['slug']}"
            crumbs = [("Home", ""), ("Services", "services"), (s["name"], route)]
            price = next((p["price"] for p in d["pricing"] if p["item"].lower() in s["name"].lower()
                          or s["name"].lower() in p["item"].lower()), None)
            hl = "".join(f'<div class="tcard"><h3>{e(x["title"])}</h3><p>{e(x["text"])}</p></div>' for x in c["highlights"][:3])
            others = [x for x in d["services"] if x["slug"] != s["slug"]][:6]
            other_html = "".join(f'<a href="/services/{x["slug"]}/">{e(x["name"])}</a>' for x in others)
            toc = ('<nav class="toc" aria-label="On this page"><strong>On this page</strong><a href="#included">What&#39;s included</a>'
                   '<a href="#quote">Pricing &amp; quotes</a><a href="#areas">Service areas</a><a href="#faq">FAQ</a></nav>'
                   if self.o["show_toc"] else "")
            related = (f'<section class="sec"><div class="wrap"><h2>Related services</h2><div class="chips">{other_html}</div>'
                       f'{self.updated()}</div></section>' if self.o["show_related"] and others
                       else f'<div class="wrap">{self.updated()}</div>')
            body = f"""<section class="phero"><div class="wrap">{self.crumbs_html(crumbs)}<p class="kicker">{e(d['industry'])} in {e(d['city'])}, {e(d['state'])}</p>
<h1>{e(s['name'])}</h1><p>Serving {e(d['region'])}</p></div></section>
<section class="sec"><div class="wrap"><div class="split"><p class="answer"><strong>{e(c['intro'])}</strong></p>
<figure class="split-img">{self.svc_photo(s, "(max-width: 860px) 100vw, 520px", eager=True)}</figure></div>{self.facts(price=f"From {price}" if price else None)}
{toc}</div></section>
<section class="sec alt" id="included"><div class="wrap"><p class="eyebrow">What's Included</p><h2>{e(s['name'])} from {e(d['name'])}</h2><div class="tcards">{hl}</div></div></section>
<section class="sec" id="quote"><div class="wrap narrow"><h2>{e(s['name'])} pricing &amp; quotes</h2><p>{e(c['estimate'])}</p>
<div class="answerbox"><strong>Quick answer:</strong> {e(d['estimate_label'])}. {self.reach()}.</div></div></section>
<section class="sec alt" id="areas"><div class="wrap"><p class="eyebrow">Where We Work</p><h2>{e(s['name'])} service areas</h2>{self.area_chips()}</div></section>
{self.faq_html(c['faqs'], f"{s['name']} FAQ")}
{related}
{self.cta(f"{d['cta_verb']} for {s['name'].lower()}", "Tell us a few details and we'll get right back to you.")}"""
            title = f"{s['name']} in {d['city']}, {d['state']} | {d['name']}"
            desc = (c["intro"][:155] + "…") if len(c["intro"]) > 158 else c["intro"]
            ld = [self.webpage(route, title, desc), self.crumbs_ld(crumbs),
                  {"@type": "Service", "@id": self.url(route) + "#service", "name": s["name"], "serviceType": s["name"],
                   "description": c["intro"], "provider": {"@id": f"{d['base']}/#business"}, "url": self.url(route),
                   "areaServed": [{"@type": "City", "name": f"{a['name']}, {d['state']}"} for a in d["areas"]]},
                  self.faq_ld(c["faqs"])]
            ph = self.a["svc"].get(s["slug"])
            if ph and not ph["stock"]:
                ld[2]["image"] = f"{d['base']}/assets/{ph['photo']['name']}-{ph['photo']['sizes'][-1][0]}.webp"
            self.page(route, title[:70], desc, body, ld, "services")

    def build_areas(self):
        d = self.d
        crumbs = [("Home", ""), ("Service Areas", "service-areas")]
        body = (f'<section class="phero"><div class="wrap">{self.crumbs_html(crumbs)}<h1>Service Areas</h1>'
                f'<p>{e(d["name"])} is based in {e(d["city"])}, {e(d["state"])} and serves {e(d["region"])}.</p></div></section>'
                f'<section class="sec"><div class="wrap">{self.area_chips()}{self.updated()}</div></section>'
                + self.cta("Don't see your town?", "Call or text. We may still be able to help."))
        title, desc = f"Service Areas | {d['name']}", f"Towns {d['name']} serves for {d['trade']} in {d['region']}."
        self.page("service-areas", title, desc, body, [self.webpage("service-areas", title, desc), self.crumbs_ld(crumbs)],
                  "service-areas")

        for i, a in enumerate(d["areas"] if self.o["show_town_pages"] else []):
            c = self.c["areas"][a["slug"]]
            route = f"service-areas/{a['slug']}"
            crumbs = [("Home", ""), ("Service Areas", "service-areas"), (a["name"], route)]
            near = [x for j, x in enumerate(d["areas"]) if j != i and abs(j - i) <= 3][:6]
            links = "".join(f'<a class="card slim" href="/services/{s["slug"]}/"><h3>{e(s["name"])} in {e(a["name"])}</h3></a>'
                            for s in d["services"])
            local = "".join(f"<p>{e(p)}</p>" for p in c["local"])
            nearby = (f'<section class="sec"><div class="wrap"><h2>Nearby areas we serve</h2>{self.area_chips(near)}{self.updated()}</div></section>'
                      if self.o["show_nearby"] and near else f'<div class="wrap">{self.updated()}</div>')
            gal = self.a["gallery"]
            picks = list(dict.fromkeys(gal[(i * 3 + k) % len(gal)]["name"] for k in range(3))) if gal else []
            photos = self.gallery([p for p in gal if p["name"] in picks], f"Recent {d['trade']} work")
            body = f"""<section class="phero"><div class="wrap">{self.crumbs_html(crumbs)}<p class="kicker">Local {e(d['trade'])}</p>
<h1>{e(d['industry'])} in <span class="hl">{e(a['name'])}, {e(d['state'])}</span></h1><p>{e(c['intro'])}</p></div></section>
<section class="sec"><div class="wrap"><p class="answer"><strong>{e(d['name'])} serves {e(a['name'])}, {e(d['state'])} for {e(d['trade'])}. {e(d['estimate_label'])}. {self.reach(plain=True)}.</strong></p>{self.facts(area=f"{a['name']}, {d['state']}")}</div></section>
<section class="sec alt"><div class="wrap"><p class="eyebrow">Services in {e(a['name'])}</p><h2>What we do in {e(a['name'])}</h2><div class="cards">{links}</div></div></section>
<section class="sec"><div class="wrap narrow"><h2>{e(d['industry'])} jobs in {e(a['name'])}</h2>{local}</div></section>
{photos}
{self.faq_html(c['faqs'], f"{a['name']} FAQ")}
{nearby}
{self.cta(f"{d['cta_verb']} in {a['name']}", "Tell us what you need and where. We'll get back to you with the next open time.")}"""
            title = f"{d['industry']} in {a['name']}, {d['state']} | {d['name']}"
            desc = f"{d['industry']} in {a['name']}, {d['state']} from {d['name']}. {d['estimate_label']}. Call or text {d['phone']}."
            ld = [self.webpage(route, title, desc), self.crumbs_ld(crumbs),
                  {"@type": "Service", "@id": self.url(route) + "#service", "name": f"{d['industry']} in {a['name']}",
                   "serviceType": d["industry"], "provider": {"@id": f"{d['base']}/#business"},
                   "areaServed": {"@type": "City", "name": f"{a['name']}, {d['state']}"}, "url": self.url(route)},
                  self.faq_ld(c["faqs"])]
            self.page(route, title[:70], desc[:160], body, ld, "service-areas")

    def build_simple(self):
        d = self.d
        # About
        crumbs = [("Home", ""), ("About", "about")]
        if self.o["show_about_page"]:
            self._about(crumbs)
        self._rest()

    def _about(self, crumbs):
        d = self.d
        paras = "".join(f"<p>{e(p)}</p>" for p in self.c["about"])
        body = (f'<section class="phero"><div class="wrap">{self.crumbs_html(crumbs)}<h1>About {e(d["name"])}</h1></div></section>'
                f'<section class="sec"><div class="wrap narrow">{paras}{self.facts()}{self.updated()}</div></section>'
                + self.cta("Let's get you on the schedule", self.reach(plain=True) + "."))
        title, desc = f"About Us | {d['name']}", f"About {d['name']}, a local {d['trade']} company in {d['city']}, {d['state']}."
        self.page("about", title, desc, body, [self.webpage("about", title, desc), self.crumbs_ld(crumbs), self.business()], "about")

    def _rest(self):
        d = self.d
        # Quote / booking page (contact and call-only businesses use the Contact page instead)
        if d["form_type"] in ("quote", "appointment"):
            route = d["cta_route"]
            if d["form_type"] == "quote":
                h1, lead = "Get a Quote", f"{d['estimate_label']}. Tell us about the job and we'll get back to you with a price."
                steps = ["We review your request.", "We reply with a price or a few questions.",
                         "We confirm a date and time that works for you."]
                title, desc = f"Get a Quote | {d['name']}", f"Request a {d['trade']} quote from {d['name']}. {d['estimate_label']}."
            else:
                h1, lead = "Book an Appointment", "Pick a service and a time that works. We'll confirm by text or call."
                steps = ["Send your preferred day and time.", "We check the schedule.", "We confirm your appointment by text or call."]
                title, desc = f"Book an Appointment | {d['name']}", f"Book {d['trade']} with {d['name']} in {d['city']}, {d['state']}."
            crumbs = [("Home", ""), (h1, route)]
            call = (f'<p>Rather talk? <a href="tel:{d["tel"]}">Call {e(d["phone"])}</a> or <a href="sms:{d["tel"]}">text us</a>.</p>'
                    if d["tel"] else "")
            body = (f'<section class="phero"><div class="wrap">{self.crumbs_html(crumbs)}<h1>{h1}</h1><p>{e(lead)}</p></div></section>'
                    f'<section class="sec"><div class="wrap qgrid"><div class="panel">{self.quote_form()}</div>'
                    f'<aside class="side"><h2>What happens next</h2><ol>{"".join(f"<li>{x}</li>" for x in steps)}</ol>'
                    f'{call}<p class="muted">{e(d["hours_text"])}</p></aside></div></section>')
            self.page(route, title, desc, body, [self.webpage(route, title, desc), self.crumbs_ld(crumbs)], route)

        # Contact
        crumbs = [("Home", ""), ("Contact", "contact")]
        rows = []
        if d["tel"]:
            rows.append(f'<p><strong>Call or text:</strong> <a href="tel:{d["tel"]}">{e(d["phone"])}</a></p>')
        if d["email"]:
            rows.append(f'<p><strong>Email:</strong> <a href="mailto:{e(d["email"])}">{e(d["email"])}</a></p>')
        loc = (e(d["street"]) + ", " if d.get("street") else "") + f'{e(d["city"])}, {e(d["state"])} {e(d.get("zip", ""))}'
        rows += [f'<p><strong>Location:</strong> {loc}</p>', f'<p><strong>Hours:</strong> {e(d["hours_text"])}</p>',
                 f'<p><strong>Service area:</strong> {e(d["region"])}</p>']
        body = (f'<section class="phero"><div class="wrap">{self.crumbs_html(crumbs)}<h1>Contact {e(d["name"])}</h1></div></section>'
                f'<section class="sec"><div class="wrap qgrid"><div class="panel">{"".join(rows)}</div>'
                f'<div class="panel">{self.quote_form()}</div></div></section>')
        title, desc = f"Contact | {d['name']}", f"Contact {d['name']} in {d['city']}, {d['state']}. Call or text {d['phone']}."
        self.page("contact", title, desc, body, [self.webpage("contact", title, desc), self.crumbs_ld(crumbs), self.business()], "contact")

        # FAQ
        crumbs = [("Home", ""), ("FAQ", "faq")]
        if self.o["show_faq_page"]:
            self._faq(crumbs)
        self._pricing_legal()

    def _faq(self, crumbs):
        d = self.d
        svc_faqs = [f for s in d["services"] for f in self.c["services"][s["slug"]]["faqs"][:1]]
        allf = self.c["faqs"] + svc_faqs
        body = (f'<section class="phero"><div class="wrap">{self.crumbs_html(crumbs)}<h1>Frequently Asked Questions</h1>'
                f'<p>Straight answers about {e(d["trade"])} from {e(d["name"])}.</p></div></section>'
                + self.faq_html(allf, "Questions & Answers") + f'<div class="wrap">{self.updated()}</div>'
                + self.cta("Still have a question?", "Call or text and we'll answer it."))
        title, desc = f"FAQ | {d['name']}", f"Answers to common {d['trade']} questions: pricing, scheduling and service area."
        self.page("faq", title, desc, body, [self.webpage("faq", title, desc), self.crumbs_ld(crumbs), self.faq_ld(allf)], "faq")

    def _pricing_legal(self):
        d = self.d
        # Pricing
        if d["pricing"] and self.o["show_pricing_page"]:
            crumbs = [("Home", ""), ("Pricing", "pricing")]
            rows = "".join(f'<tr><th scope="row">{e(p["item"])}</th><td>{e(p["price"])}</td></tr>' for p in d["pricing"])
            body = (f'<section class="phero"><div class="wrap">{self.crumbs_html(crumbs)}<h1>Pricing</h1>'
                    f'<p>Clear starting prices for {e(d["trade"])} in {e(d["region"])}.</p></div></section>'
                    f'<section class="sec"><div class="wrap narrow"><p class="answer"><strong>{e(d["name"])} prices start at '
                    f'{e(d["pricing"][0]["price"])} for {e(d["pricing"][0]["item"].lower())}. {e(d["estimate_label"])}; '
                    f'your final price depends on the size and details of the job.</strong></p>'
                    f'<table class="ptable"><thead><tr><th>Service</th><th>Price</th></tr></thead><tbody>{rows}</tbody></table>'
                    f'{self.updated()}</div></section>' + self.cta("Want an exact price?", "Send a few details and a photo."))
            title, desc = f"Pricing | {d['name']}", f"{d['name']} pricing for {d['trade']} in {d['region']}. {d['estimate_label']}."
            self.page("pricing", title, desc, body, [self.webpage("pricing", title, desc), self.crumbs_ld(crumbs)], "pricing")

        # Legal
        t = self.d["today"]
        when = f"{t.strftime('%B')} {t.day}, {t.year}"
        contact = " or ".join(x for x in (d["phone"] if d["tel"] else "", d["email"]) if x)
        privacy = f"""<h2>Information we collect</h2><p>When you call, text, email or submit a form, we collect the details you give us, such as your name, phone number, email, address and job details, plus any photos you send.</p>
<h2>How we use it</h2><p>We use your information only to respond to you, prepare quotes, schedule and complete work, send invoices, and follow up about your job.</p>
<h2>Text messages</h2><p>If you agree to receive texts, we send messages about your inquiry, quote and appointments. Message frequency varies. Message and data rates may apply. Reply STOP to opt out or HELP for help. We do not sell or share your phone number or text-messaging consent with third parties for their marketing.</p>
<h2>Sharing</h2><p>We do not sell your personal information. We share it only with service providers who help us run the business (for example payment, scheduling or website hosting), or when required by law.</p>
<h2>Analytics and cookies</h2><p>This site may use basic analytics to understand how visitors use it. You can block cookies in your browser settings.</p>
<h2>Contact</h2><p>Questions about this policy? Contact {e(d['name'])} at {e(contact)}.</p>"""
        terms = f"""<h2>Quotes</h2><p>Quotes are based on the information and photos you provide. If the job is materially different on arrival, we will tell you the updated price before starting work.</p>
<h2>Scheduling</h2><p>Appointments are confirmed by phone, text or email. Please let us know as early as possible if you need to reschedule.</p>
<h2>Payment</h2><p>Payment is due when the work is complete unless we agree otherwise in writing.</p>
<h2>Website</h2><p>Content on this site is for general information. Prices shown are starting prices and may change. {e(d['name'])} is not liable for errors on the site or for links to third-party sites.</p>
<h2>Contact</h2><p>Questions? Contact {e(d['name'])} at {e(contact)}.</p>"""
        for route, name, content in (("privacy-policy", "Privacy Policy", privacy), ("terms", "Terms & Conditions", terms)):
            crumbs = [("Home", ""), (name, route)]
            body = (f'<section class="phero"><div class="wrap">{self.crumbs_html(crumbs)}<h1>{e(name)}</h1>'
                    f'<p>Last updated {when}</p></div></section><section class="sec"><div class="wrap narrow prose">{content}</div></section>')
            title, desc = f"{name} | {d['name']}", f"{name} for {d['name']}."
            self.page(route, title, desc, body, [self.webpage(route, title, desc), self.crumbs_ld(crumbs)])

        body = (f'<section class="phero"><div class="wrap"><h1>Page not found</h1><p>That page moved or never existed.</p>'
                f'<div class="hero-btns"><a class="btn btn-accent" href="/">Go home</a><a class="btn btn-light" href="/services/">See services</a></div></div></section>')
        self.page("__404", f"Page not found | {d['name']}", "Page not found.", body, [], robots="noindex,follow")

        call = f' Need us sooner? Call or text <a href="tel:{d["tel"]}">{e(d["phone"])}</a>.' if d["tel"] else ""
        body = (f'<section class="phero"><div class="wrap"><h1>Thank you!</h1><p>We got your request and will get back to you '
                f'shortly.{call}</p><div class="hero-btns"><a class="btn btn-accent" href="/">Back to home</a></div></div></section>')
        self.page("thank-you", f"Thank you | {d['name']}", "Request received.", body, [], robots="noindex,follow")

    # Root files ---------------------------------------------------------
    def llms_txt(self) -> str:
        d = self.d
        lines = [f"# {d['name']}", "", f"> {self.c['home']['intro']}", "",
                 f"- Business: {d['name']}", f"- Industry: {d['industry']}", f"- Based in: {d['city']}, {d['state']}",
                 f"- Service area: {d['region']}; towns: {', '.join(a['name'] for a in d['areas'])}",
                 f"- Hours: {d['hours_text']}"]
        if d["tel"]:
            lines.append(f"- Phone (call or text): {d['phone']}")
        if d["email"]:
            lines.append(f"- Email: {d['email']}")
        lines.append(f"- Estimates: {d['estimate_label']}")
        if d["pricing"]:
            lines.append("- Pricing: " + "; ".join(f"{p['item']} {p['price']}" for p in d["pricing"]))
        lines += ["", "## Main pages", ""] + [f"- [{n}]({self.url(r)})" for n, r in
                  [("Home", ""), (d["cta_label"], d["cta_route"]), ("Services", "services"), ("Service Areas", "service-areas"),
                   ("FAQ", "faq"), ("About", "about"), ("Contact", "contact"), ("Pricing", "pricing")]
                  if r in self.pages and (n, r) != (d["cta_label"], "contact")]
        lines += ["", "## Services", ""] + [f"- [{s['name']}]({self.url('services/' + s['slug'])})" for s in d["services"]]
        lines += ["", "## Service areas", ""] + [
            f"- [{a['name']}, {d['state']}]({self.url('service-areas/' + a['slug'])})" if self.o["show_town_pages"]
            else f"- {a['name']}, {d['state']}" for a in d["areas"]]
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- assets

def _theme_css(d: dict) -> str:
    _, upper = FONTS[d["font_head"]]
    vars_ = {
        "--brand": d["primary"], "--brand-ink": _ink(d["primary"]),
        "--accent": d["accent"], "--accent-ink": _ink(d["accent"]),
        "--accent-hover": _mix(d["accent"], "#000000", 0.12),
        "--link": _readable_on_white(d["primary"]),
        "--dark": d["dark"], "--dark-2": _mix(d["dark"], "#ffffff", 0.08),
        "--tint": _mix(d["primary"], "#ffffff", 0.93),
        "--font-head": f"'{d['font_head']}', system-ui, sans-serif",
        "--font-body": f"'{d['body_font']}', system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    }
    case = d["style"]["head_case"]
    upper = upper if case == "auto" else case == "upper"
    vars_["--head-case"] = "uppercase" if upper else "none"
    vars_["--head-track"] = ".01em" if upper else "-.015em"
    root = ":root{" + ";".join(f"{k}:{v}" for k, v in vars_.items()) + "}\n"
    return root + (HERE / "theme.css").read_text(encoding="utf-8")


def _photo(src: Path, assets: Path, name: str) -> dict:
    """Crop to 3:2 and save fast WebP copies at PHOTO_WIDTHS (any size in, 4K included)."""
    from PIL import Image, ImageOps

    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    w = min(im.width, round(im.height * 1.5), PHOTO_WIDTHS[-1])
    im = ImageOps.fit(im, (w, round(w / 1.5)), Image.LANCZOS)
    sizes = []
    for target in PHOTO_WIDTHS:
        if target > im.width and sizes:
            break
        r = im.resize((min(target, im.width), round(min(target, im.width) / 1.5)), Image.LANCZOS)
        r.save(assets / f"{name}-{target}.webp", "WEBP", quality=80, method=6)
        sizes.append((target, r.width, r.height))
    return {"name": name, "sizes": sizes}


def _hero_webp(src: Path, assets: Path) -> str:
    """Home page banner, 1920px wide WebP."""
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    im.thumbnail((1920, 1400))
    im.save(assets / "hero.webp", "WEBP", quality=78, method=6)
    return "hero.webp"


def _stock_hero(d: dict, assets: Path, photo_queries: dict, avoid: set, log) -> tuple[str, dict] | None:
    """A stock banner photo when the owner didn't upload one."""
    q = photo_queries.get("_hero") or ""
    hit = stock.find([(q, stock.key_words(q)), (d["industry"], stock.key_words(d["industry"])),
                      (d["trade"], stock.key_words(d["trade"]))], avoid, log)
    if not hit:
        log("  No stock banner photo found; the home page uses the brand-color hero")
        return None
    return _hero_webp(hit[0], assets), {"service": "Home page banner", **hit[1]}


def _photos(d: dict, assets: Path, svc_photos: dict, gallery: list, photo_queries: dict, log) -> tuple[dict, list, list]:
    """Service photos (real first, then stock), gallery photos, and a credits list for stock.

    Stock photos must be tagged with a specific word from the service name and are
    never repeated on one site."""
    svc, credits, used = {}, [], set()
    for s in d["services"]:
        src, is_stock = svc_photos.get(s["slug"]), False
        if not src and stock.available():
            ai_q = photo_queries.get(s["slug"]) or ""
            name_words = stock.key_words(s["name"])
            industry_words = stock.key_words(d["industry"])
            queries = [(ai_q, stock.key_words(ai_q)),                      # Claude's search, e.g. "scrubbing bathroom tile grout"
                       (s["name"].replace("&", " "), name_words),          # the service name, if it has a specific word
                       (f"{s['name'].replace('&', ' ')} {d['industry']}", industry_words)]
            hit = stock.find(queries, used, log)
            if not hit:
                log(f"  No matching stock photo for {s['name']}")
            else:
                used.add(hit[1]["id"])
                src, is_stock = hit[0], True
                credits.append({"service": s["name"], **hit[1]})
        if src:
            try:
                svc[s["slug"]] = {"photo": _photo(src, assets, f"svc-{s['slug']}"), "stock": is_stock}
            except Exception as ex:
                log(f"  Couldn't use the photo for {s['name']} ({ex})")
    gal = []
    for n, src in enumerate(gallery[:12], 1):
        try:
            gal.append(_photo(src, assets, f"work-{n}"))
        except Exception as ex:
            log(f"  Skipped gallery photo {n} ({ex})")
    return svc, gal, credits


def _images(d: dict, out: Path, logo: Path | None, hero: Path | None) -> dict:
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    a = {}
    assets = out / "assets"
    if logo:
        im = Image.open(logo)
        im.thumbnail((800, 300))
        name = "logo.png"
        im.save(assets / name, optimize=True)
        h = 52
        a.update(logo=name, logo_w=round(im.width * h / im.height), logo_h=h)
        src = im.convert("RGBA")
    else:
        src = None
    if hero:
        a["hero"] = _hero_webp(hero, assets)

    # Favicon: logo on a square, or the business initials.
    size = 512
    if src:
        fav = Image.new("RGBA", (size, size), (255, 255, 255, 0))
        s = src.copy()
        s.thumbnail((int(size * .92), int(size * .92)))
        fav.paste(s, ((size - s.width) // 2, (size - s.height) // 2), s)
    else:
        fav = Image.new("RGBA", (size, size), _rgb(d["primary"]) + (255,))
        initials = "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", d["name"])[:2]).upper() or "•"
        draw = ImageDraw.Draw(fav)
        font = ImageFont.load_default(size=240)
        draw.text((size / 2, size / 2), initials, fill=_ink(d["primary"]), font=font, anchor="mm")
    fav.save(out / "favicon.png")
    fav.save(out / "favicon.ico", sizes=[(48, 48), (32, 32), (16, 16)])

    # Social share image 1200x630.
    og = Image.new("RGB", (1200, 630), _rgb(d["dark"]))
    draw = ImageDraw.Draw(og)
    draw.rectangle([0, 600, 1200, 630], fill=_rgb(d["accent"]))
    if src:
        card = Image.new("RGBA", (760, 300), (255, 255, 255, 255))
        s = src.copy()
        s.thumbnail((680, 240))
        card.paste(s, ((760 - s.width) // 2, (300 - s.height) // 2), s)
        og.paste(card, (220, 110))
        draw.text((600, 500), f"{d['industry']} · {d['city']}, {d['state']}", fill="#ffffff",
                  font=ImageFont.load_default(size=40), anchor="mm")
    else:
        draw.text((600, 280), d["name"], fill="#ffffff", font=ImageFont.load_default(size=72), anchor="mm")
        draw.text((600, 380), f"{d['industry']} · {d['city']}, {d['state']}", fill="#dddddd",
                  font=ImageFont.load_default(size=40), anchor="mm")
    og.save(assets / "og.png", optimize=True)
    return a


def _checklist(d: dict) -> str:
    return f"""# Launch checklist: {d['name']}

Built {d['today'].isoformat()}. Upload the `site` folder (or the zip) to Cloudflare Pages.

0. **Photos**: any service marked "stock" in the builder is using a free stock photo (Pixabay). Swap in the owner's real job photos when you get them; real photos convert better and help Google.
1. **Cloudflare Pages**: Workers & Pages → Create → Pages → Upload assets → drag in the `site` folder. Project name: `{d['slug']}`.
2. **Domain**: Pages project → Custom domains → add `{d['domain']}` (and `www.`). If you change the domain, rebuild so canonical URLs, sitemap and schema match.
3. **Quote form**: {"posts to " + d['form_endpoint'] if d.get('form_endpoint') else "no form endpoint set, so the form opens the visitor's text app with the request filled in."}
   - For emailed leads **with photos**, set the form endpoint to `https://formsubmit.co/THEIR-EMAIL` (free, no account). The first real submission sends a confirmation email to that address; the owner clicks it once and leads start arriving. Test it before launch.
   - For emailed leads without photos, a free Web3Forms key (web3forms.com) also works.
4. **Google Search Console**: add the domain property, submit `{d['base']}/sitemap.xml`, request indexing for the home page.
5. **Bing Webmaster Tools**: import from Search Console (feeds ChatGPT/Copilot search too).
6. **Google Business Profile**: website = `{d['base']}/`, same name/phone/hours as the site (NAP must match exactly), categories match the services, add the service areas.
7. **Citations**: same name/phone/address on Yelp, Facebook, Apple Business Connect, Bing Places, Nextdoor, BBB.
8. **Reviews**: ask every customer for a Google review; add the review link to the builder (Google profile field) and rebuild.
9. **Analytics**: add a GA4 ID in the builder and rebuild.
10. **Check**: run the home page through https://search.google.com/test/rich-results and https://pagespeed.web.dev.
"""


def build_site(raw: dict, out_dir: Path, logo: Path | None = None, hero: Path | None = None,
               svc_photos: dict | None = None, gallery: list | None = None,
               use_ai: bool = False, rewrite_copy: bool = False, log=print,
               about: Path | None = None, before: Path | None = None, after: Path | None = None) -> dict:
    """Build the site into out_dir/site and out_dir/<slug>-site.zip.

    svc_photos maps service slug -> photo path; gallery is a list of job photo paths.
    AI copy already written for this business (copy.json) is reused unless rewrite_copy.
    Returns {"zip", "pages", "stock": [service names], "no_photo": [service names]}.
    """
    d = normalize(raw)
    out_dir = Path(out_dir)
    site_dir = out_dir / "site"
    if site_dir.exists():
        shutil.rmtree(site_dir)
    (site_dir / "assets").mkdir(parents=True)

    log(f"Building {d['name']}: {len(d['services'])} services, {len(d['areas'])} areas")
    prev = out_dir / "copy.json"
    existing = json.loads(prev.read_text(encoding="utf-8")) if prev.exists() and not rewrite_copy else None
    if use_ai and not writer.ai_available():
        log("AI copy unavailable (no anthropic package or ANTHROPIC_API_KEY); using template copy")
    copy = writer.build_copy(d, use_ai=use_ai and writer.ai_available(), existing=existing, log=log)

    assets = _images(d, site_dir, logo, hero)
    if not stock.available():
        log("Stock photos off (no PIXABAY_API_KEY); services without a photo get a brand-color panel")
    assets["svc"], assets["gallery"], credits = _photos(d, site_dir / "assets", svc_photos or {}, gallery or [],
                                                        copy.get("photo_queries") or {}, log)
    if not assets.get("hero") and stock.available():
        got = _stock_hero(d, site_dir / "assets", copy.get("photo_queries") or {}, {c["id"] for c in credits}, log)
        if got:
            assets["hero"] = got[0]
            credits.append(got[1])
    for key, src in (("about", about), ("before", before), ("after", after)):  # optional real photos
        if src:
            try:
                assets[key] = _photo(src, site_dir / "assets", key)
            except Exception as ex:
                log(f"  Couldn't use the {key} photo ({ex})")
    stock_used = [c["service"] for c in credits]
    no_photo = [x["name"] for x in d["services"] if x["slug"] not in assets["svc"]]
    if stock_used:
        log("Stock photo used for: " + ", ".join(stock_used) + " (swap in real photos when you can)")
    (out_dir / "photo-credits.json").write_text(json.dumps(credits, indent=2), encoding="utf-8")
    css = _theme_css(d)
    (site_dir / "assets" / "site.css").write_text(css, encoding="utf-8")
    # Cache-busting version from the CSS + JS contents, so browsers fetch fresh files after any change.
    import hashlib
    d["asset_v"] = hashlib.md5((css + (HERE / "site.js").read_text(encoding="utf-8")).encode()).hexdigest()[:10]
    shutil.copy2(HERE / "site.js", site_dir / "assets" / "site.js")

    s = Site(d, copy, assets)
    s.build_home()
    s.build_services()
    s.build_areas()
    s.build_simple()

    for route, page in s.pages.items():
        if route == "__404":
            (site_dir / "404.html").write_text(page, encoding="utf-8")
            continue
        dst = site_dir / route / "index.html" if route else site_dir / "index.html"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(page, encoding="utf-8")

    routes = [r for r in s.pages if r not in ("__404", "thank-you")]
    lastmod = d["today"].isoformat()
    (site_dir / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(f"  <url><loc>{s.url(r)}</loc><lastmod>{lastmod}</lastmod></url>" for r in routes)
        + "\n</urlset>\n", encoding="utf-8")
    (site_dir / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {d['base']}/sitemap.xml\n", encoding="utf-8")
    (site_dir / "llms.txt").write_text(s.llms_txt(), encoding="utf-8")
    (site_dir / "_redirects").write_text("/home / 301\n/index.html / 301\n/terms-and-conditions /terms/ 301\n"
                                         f"/privacy /privacy-policy/ 301\n/quote /{d['cta_route']}/ 301\n"
                                         + ("" if d["cta_route"] == "book" else f"/book /{d['cta_route']}/ 301\n"),
                                         encoding="utf-8")
    (site_dir / "_headers").write_text(
        "/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n"
        "/assets/*\n  Cache-Control: public, max-age=604800\n"
        "/sitemap.xml\n  X-Robots-Tag: noindex, follow\n/llms.txt\n  X-Robots-Tag: noindex, follow\n", encoding="utf-8")
    (out_dir / "LAUNCH-CHECKLIST.md").write_text(_checklist(d), encoding="utf-8")
    (out_dir / "copy.json").write_text(json.dumps(copy, indent=2, ensure_ascii=False), encoding="utf-8")

    zpath = out_dir / f"{d['slug']}-site.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in site_dir.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(site_dir))
    log(f"Done: {len(routes) + 1} pages -> {site_dir}")
    return {"zip": zpath, "pages": len(routes), "stock": stock_used, "no_photo": no_photo}
